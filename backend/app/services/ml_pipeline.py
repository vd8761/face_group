"""
ML pipeline service — face detection and embedding using InsightFace buffalo_l.
Uses the buffalo_l model pack (RetinaFace detector + ArcFace embedder).

# Memory budget on Render Pro (4 GB RAM / 2 CPU):
#   - buffalo_l model:  ~1,500 MB  (constant, loaded once per worker)
#   - Image buffer:     ~  100 MB  (capped via MAX_PROCESS_DIM)
#   - 2× concurrent:    ~3,200 MB  — safe headroom on 4 GB
#
# Key memory controls:
#   - MAX_PROCESS_DIM: images are downscaled before detection (default 1920px)
#   - RAW half_size=True: 40MP ARW → 10MP before numpy array is created
#   - gc.collect() after every image frees numpy arrays immediately
#   - Global semaphore limits concurrent face-detection runs
"""
import io
import os
import gc
import numpy as np
from typing import List
from dataclasses import dataclass

from ..config import get_settings

settings = get_settings()

# Set InsightFace cache to /tmp (always writable on Render)
os.environ.setdefault("INSIGHTFACE_HOME", "/tmp/insightface_cache")

# ── Memory safety ────────────────────────────────────────────────────────────
# Max long edge (pixels) before face detection.
# 1280 px is an optimal sweet spot for speed and accuracy. 1920 px is much slower on CPU.
MAX_PROCESS_DIM = 1280

# Memory safety: Celery worker_concurrency=2 means two SEPARATE processes
# each loading the model independently. No shared memory, no semaphore needed.
# Each worker process uses ~1.5 GB (model) + ~200 MB (buffers) = ~1.7 GB
# Two workers = ~3.4 GB — safe on 4 GB Pro.

# ── Format sets ──────────────────────────────────────────────────────────────
RAW_EXTENSIONS = {
    '.arw', '.srf', '.sr2',          # Sony
    '.cr2', '.cr3', '.crw',          # Canon
    '.nef', '.nrw',                  # Nikon
    '.dng',                          # Adobe / Universal
    '.raf',                          # Fujifilm
    '.orf',                          # Olympus / OM System
    '.rw2',                          # Panasonic
    '.pef', '.ptx',                  # Pentax / Ricoh
    '.srw',                          # Samsung
    '.3fr', '.fff',                  # Hasselblad
    '.iiq',                          # Phase One
    '.erf',                          # Epson
    '.mrw',                          # Minolta / Konica-Minolta
    '.x3f',                          # Sigma
    '.k25', '.kdc', '.dcr',          # Kodak
    '.rwl',                          # Leica
    '.mef', '.mfw', '.mos',          # Mamiya
}
HEIC_EXTENSIONS = {'.heic', '.heif', '.avif'}


# ── Image decoder ────────────────────────────────────────────────────────────
def _decode_image_to_bgr(image_bytes: bytes, filename: str = '') -> np.ndarray:
    """
    Decode any supported image format to a BGR uint8 numpy array.

    Memory-optimised:
    - RAW files decoded at half_size=True  → 4× less RAM than full resolution
    - Image is downscaled to MAX_PROCESS_DIM immediately after decode
    - EXIF rotation applied so portrait photos are never sideways
    - Handles: JPEG, PNG, WEBP, TIFF, BMP, GIF, HEIC/HEIF/AVIF, all major RAW formats
    """
    import cv2
    from PIL import Image, ImageOps

    ext = os.path.splitext(filename.lower())[1] if filename else ''

    # ── 1. RAW camera files ──────────────────────────────────────────────────
    if ext in RAW_EXTENSIONS:
        try:
            import rawpy
            with rawpy.imread(io.BytesIO(image_bytes)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True,
                    half_size=True,      # KEY: cuts RAM use by 4× (40MP → 10MP)
                    no_auto_bright=False,
                    output_bps=8,
                )
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            del rgb
            return bgr
        except ImportError:
            pass  # rawpy not installed — fall through to PIL
        except Exception as e:
            raise ValueError(
                f"Cannot decode RAW '{filename}' ({ext.upper()}): {e}. "
                "Export as JPEG or TIFF from your camera software."
            )

    # ── 2. HEIC / HEIF / AVIF ────────────────────────────────────────────────
    if ext in HEIC_EXTENSIONS:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise ValueError(
                f"'{filename}' is a HEIC/AVIF file — requires pillow-heif. "
                "Re-upload as JPEG or PNG."
            )
        # Fall through to PIL path below

    # ── 3. Standard formats via PIL (EXIF-aware) ─────────────────────────────
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        try:
            pil_img = ImageOps.exif_transpose(pil_img)
        except Exception:
            pass
        pil_img = pil_img.convert('RGB')
        arr = np.array(pil_img, dtype=np.uint8)
        del pil_img
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        del arr
        if bgr is not None and bgr.size > 0:
            return bgr
    except Exception:
        pass

    # ── 4. Final fallback: OpenCV direct decode ───────────────────────────────
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    del nparr
    if img is None:
        raise ValueError(
            f"Cannot decode '{filename}' (ext: '{ext}'). "
            "Supported: JPEG, PNG, WEBP, TIFF, HEIC, BMP, "
            "and all major RAW formats (ARW, CR2/CR3, NEF, DNG, RAF, ORF, RW2 …)."
        )
    return img


def _downscale_if_needed(img: np.ndarray, max_dim: int = MAX_PROCESS_DIM) -> np.ndarray:
    """Resize image so its longest edge ≤ max_dim. Returns same array if already small enough."""
    import cv2
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return img
    scale = max_dim / longest
    resized = cv2.resize(
        img,
        (int(w * scale), int(h * scale)),
        interpolation=cv2.INTER_AREA,
    )
    del img
    return resized


# ── InsightFace model (singleton, loaded lazily) ─────────────────────────────
_app = None


def _get_insightface_app():
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        import onnxruntime as ort
        
        providers = ["CPUExecutionProvider"]
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            
        _app = FaceAnalysis(
            name="buffalo_s",
            providers=providers,
        )
        # det_size=(640,640) is the standard input size — don't increase it
        _app.prepare(ctx_id=0, det_size=(640, 640))
    return _app


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class DetectedFace:
    bbox: list
    confidence: float
    embedding: np.ndarray   # 512-dim float32, already L2-normalised
    quality_score: float
    is_low_quality: bool
    face_crop_bytes: bytes  # JPEG-encoded face crop (with margin)


# ── Main detection function ───────────────────────────────────────────────────
def detect_and_embed(image_bytes: bytes, filename: str = '') -> List[DetectedFace]:
    """
    Run face detection + ArcFace embedding on raw image bytes.

    Memory-safe:
    - Decodes at half_size for RAW files
    - Downscales to MAX_PROCESS_DIM (1920 px) before detection
    - Deletes large arrays and calls gc.collect() before returning
    - Returns lightweight DetectedFace objects (no full image retained)

    This function is synchronous and should be called via run_in_threadpool.
    """
    import cv2

    img = None
    try:
        app = _get_insightface_app()

        # Decode + rotate
        img = _decode_image_to_bgr(image_bytes, filename)

        if img is None or img.size == 0:
            raise ValueError("Decoded image is empty — file may be corrupted.")

        img_h, img_w = img.shape[:2]
        if img_h < 10 or img_w < 10:
            raise ValueError(f"Image too small: {img_w}×{img_h} px")

        # Downscale to MAX_PROCESS_DIM — saves RAM, speeds up inference
        img = _downscale_if_needed(img)
        img_h, img_w = img.shape[:2]

        # Run detection
        faces = app.get(img)
        results: List[DetectedFace] = []

        for face in faces:
            raw_bbox = face.bbox.astype(int).tolist()
            confidence = float(face.det_score)
            # Copy embedding immediately so InsightFace's internal buffer can be freed
            embedding = face.normed_embedding.copy()

            # Clamp bbox to image bounds
            x1 = max(0, min(raw_bbox[0], img_w - 1))
            y1 = max(0, min(raw_bbox[1], img_h - 1))
            x2 = max(0, min(raw_bbox[2], img_w))
            y2 = max(0, min(raw_bbox[3], img_h))
            bbox = [x1, y1, x2, y2]

            w_f = x2 - x1
            h_f = y2 - y1
            if w_f <= 0 or h_f <= 0:
                continue

            face_size_ok  = w_f >= settings.FACE_MIN_SIZE and h_f >= settings.FACE_MIN_SIZE
            confidence_ok = confidence >= settings.FACE_DETECTION_THRESHOLD
            
            # Check face rotation (yaw) to reject extreme side profiles
            pose_ok = True
            if hasattr(face, 'pose') and face.pose is not None and len(face.pose) >= 2:
                pitch, yaw, roll = face.pose[:3]
                if abs(yaw) > 45:
                    pose_ok = False

            is_low_quality = not (face_size_ok and confidence_ok and pose_ok)

            size_score    = min(1.0, min(w_f, h_f) / 150.0)
            quality_score = float(np.sqrt(confidence * size_score))

            # Face crop with 25 % margin
            mx = int(w_f * 0.25)
            my = int(h_f * 0.25)
            cx1 = max(0, x1 - mx);  cy1 = max(0, y1 - my)
            cx2 = min(img_w, x2 + mx); cy2 = min(img_h, y2 + my)

            crop = img[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue

            _, buf = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            face_crop_bytes = buf.tobytes()
            del crop, buf

            results.append(DetectedFace(
                bbox=bbox,
                confidence=confidence,
                embedding=embedding,
                quality_score=quality_score,
                is_low_quality=is_low_quality,
                face_crop_bytes=face_crop_bytes,
            ))

        return results

    finally:
        # Always free the image array, even on exception
        if img is not None:
            del img
        gc.collect()


# ── Utilities ─────────────────────────────────────────────────────────────────
def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialise a float32 embedding to bytes for DB storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialise bytes back to a float32 numpy array."""
    return np.frombuffer(data, dtype=np.float32).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised embeddings (range −1 to 1)."""
    return float(np.dot(a, b))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (0 = identical, 2 = opposite)."""
    return 1.0 - cosine_similarity(a, b)
