"""
ML pipeline service — face detection and embedding using InsightFace buffalo_l.
Uses the buffalo_l model pack (RetinaFace detector + ArcFace embedder).
Requires ~1.5GB RAM — use Render Standard plan (2GB) or equivalent.
Supports: JPEG, PNG, WEBP, HEIC, TIFF, and RAW formats (ARW, CR2, NEF, DNG, RAF).
"""
import io
import os
import numpy as np
from typing import List
from dataclasses import dataclass

from ..config import get_settings

settings = get_settings()

# Set InsightFace cache to /tmp (always writable on Render)
os.environ.setdefault("INSIGHTFACE_HOME", "/tmp/insightface_cache")

# All RAW extensions that rawpy can handle
RAW_EXTENSIONS = {
    # Sony
    '.arw', '.srf', '.sr2',
    # Canon
    '.cr2', '.cr3', '.crw',
    # Nikon
    '.nef', '.nrw',
    # Adobe / Universal
    '.dng',
    # Fujifilm
    '.raf',
    # Olympus / OM System
    '.orf',
    # Panasonic
    '.rw2',
    # Pentax / Ricoh
    '.pef', '.ptx',
    # Samsung
    '.srw',
    # Hasselblad
    '.3fr', '.fff',
    # Phase One
    '.iiq',
    # Epson
    '.erf',
    # Minolta / Konica-Minolta
    '.mrw',
    # Sigma
    '.x3f',
    # Kodak
    '.k25', '.kdc', '.dcr',
    # Leica
    '.rwl',
    # Mamiya
    '.mef', '.mfw', '.mos',
}

# Formats PIL handles natively with EXIF awareness
PIL_EXTENSIONS = {'.jpg', '.jpeg', '.jpe', '.jfif', '.png', '.webp', '.tif', '.tiff', '.bmp', '.gif'}
HEIC_EXTENSIONS = {'.heic', '.heif', '.avif'}


def _decode_image_to_bgr(image_bytes: bytes, filename: str = '') -> np.ndarray:
    """
    Decode ANY supported image format to a BGR numpy array for OpenCV/InsightFace.
    
    Priority chain:
    1. RAW camera files (Sony ARW, Canon CR2/CR3, Nikon NEF, DNG, Fuji RAF, etc.) via rawpy
    2. HEIC/HEIF/AVIF (iPhone, modern mobile) via pillow-heif
    3. Standard formats (JPEG+EXIF, PNG, WEBP, TIFF, BMP, GIF) via Pillow
    4. Final fallback: direct cv2 decode

    EXIF orientation is applied at every stage so portrait photos are never sideways.
    Image dimensions are clamped to valid ranges before returning.
    """
    import cv2
    from PIL import Image, ImageOps

    ext = os.path.splitext(filename.lower())[1] if filename else ''

    # ── 1. RAW camera files ─────────────────────────────────────────────────
    if ext in RAW_EXTENSIONS:
        try:
            import rawpy
            with rawpy.imread(io.BytesIO(image_bytes)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True,
                    half_size=False,         # full resolution
                    no_auto_bright=False,
                    output_bps=8,
                    demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
                )
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            return bgr
        except ImportError:
            # rawpy not installed — fall through to PIL (may fail for RAW)
            pass
        except Exception as e:
            # Some RAW files may be corrupt or use unsupported compression
            raise ValueError(
                f"Cannot decode RAW file '{filename}' ({ext.upper()}): {e}. "
                "Please export as JPEG or TIFF from your camera software."
            )

    # ── 2. HEIC / HEIF / AVIF ──────────────────────────────────────────────
    if ext in HEIC_EXTENSIONS:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise ValueError(
                f"'{filename}' is a HEIC/AVIF file which requires pillow-heif. "
                "Please re-upload as JPEG or PNG."
            )
        # Fall through to PIL path below (which can now open HEIC)

    # ── 3. Standard formats via PIL with EXIF orientation ──────────────────
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        # Apply EXIF orientation — fixes portrait/rotated JPEGs from phones & cameras
        try:
            pil_img = ImageOps.exif_transpose(pil_img)
        except Exception:
            pass  # Not all formats have EXIF; ignore silently
        # Convert to RGB (handles palette, RGBA, L, CMYK, etc.)
        pil_img = pil_img.convert('RGB')
        bgr = cv2.cvtColor(np.array(pil_img, dtype=np.uint8), cv2.COLOR_RGB2BGR)
        if bgr is not None and bgr.size > 0:
            return bgr
    except Exception:
        pass  # Fall through to cv2 decode

    # ── 4. Final fallback: direct OpenCV decode ─────────────────────────────
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(
            f"Cannot decode image '{filename}' (extension: '{ext}'). "
            "Supported formats: JPEG, PNG, WEBP, TIFF, HEIC, BMP, and all major RAW formats "
            "(ARW, CR2/CR3, NEF, DNG, RAF, ORF, RW2, PEF, and more)."
        )
    return img


_app = None


def _get_insightface_app():
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        _app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        _app.prepare(ctx_id=0, det_size=(640, 640))
    return _app


@dataclass
class DetectedFace:
    bbox: list
    confidence: float
    embedding: np.ndarray   # 512-dim float32
    quality_score: float
    is_low_quality: bool
    face_crop_bytes: bytes  # JPEG encoded face crop


def detect_and_embed(image_bytes: bytes, filename: str = '') -> List[DetectedFace]:
    """
    Run face detection + embedding on raw image bytes.
    Supports any image format including RAW (ARW/NEF/CR2/DNG) and HEIC.
    Automatically corrects EXIF rotation for portrait/sideways photos.
    Returns a list of DetectedFace objects, one per detected face.
    Faces below confidence or size thresholds are marked as low_quality.
    """
    import cv2

    app = _get_insightface_app()

    # Decode image — handles RAW, HEIC, EXIF rotation, all standard formats
    img = _decode_image_to_bgr(image_bytes, filename)

    # Validate decoded image
    if img is None or img.size == 0:
        raise ValueError("Decoded image is empty — file may be corrupted.")

    img_h, img_w = img.shape[:2]
    if img_h < 10 or img_w < 10:
        raise ValueError(f"Image dimensions too small: {img_w}x{img_h}")

    # Downscale very large images to limit RAM usage (keep faces detectable)
    max_dim = max(img_h, img_w)
    if max_dim > 4096:
        scale = 4096 / max_dim
        img = cv2.resize(img, (int(img_w * scale), int(img_h * scale)), interpolation=cv2.INTER_AREA)
        img_h, img_w = img.shape[:2]

    faces = app.get(img)
    results: List[DetectedFace] = []

    for face in faces:
        bbox = face.bbox.astype(int).tolist()
        confidence = float(face.det_score)
        embedding = face.normed_embedding

        # Clamp bbox to image bounds (handles edge cases)
        x1_b = max(0, min(bbox[0], img_w - 1))
        y1_b = max(0, min(bbox[1], img_h - 1))
        x2_b = max(0, min(bbox[2], img_w))
        y2_b = max(0, min(bbox[3], img_h))
        bbox = [x1_b, y1_b, x2_b, y2_b]

        w_face = x2_b - x1_b
        h_face = y2_b - y1_b

        if w_face <= 0 or h_face <= 0:
            continue  # skip degenerate detections

        face_size_ok = (w_face >= settings.FACE_MIN_SIZE and h_face >= settings.FACE_MIN_SIZE)
        confidence_ok = confidence >= settings.FACE_DETECTION_THRESHOLD
        is_low_quality = not (face_size_ok and confidence_ok)

        size_score = min(1.0, min(w_face, h_face) / 200.0)
        quality_score = float(np.sqrt(confidence * size_score))

        # Extract face crop with a 25% margin on each side
        margin_x = int(w_face * 0.25)
        margin_y = int(h_face * 0.25)
        cx1 = max(0, x1_b - margin_x)
        cy1 = max(0, y1_b - margin_y)
        cx2 = min(img_w, x2_b + margin_x)
        cy2 = min(img_h, y2_b + margin_y)

        face_crop = img[cy1:cy2, cx1:cx2]
        if face_crop.size == 0:
            continue

        _, buffer = cv2.imencode('.jpg', face_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        face_crop_bytes = buffer.tobytes()

        results.append(DetectedFace(
            bbox=bbox,
            confidence=confidence,
            embedding=embedding,
            quality_score=quality_score,
            is_low_quality=is_low_quality,
            face_crop_bytes=face_crop_bytes,
        ))

    return results


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialise a float32 embedding numpy array to bytes for DB storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialise bytes back to a float32 numpy array."""
    return np.frombuffer(data, dtype=np.float32).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised embeddings (range -1 to 1)."""
    return float(np.dot(a, b))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (0 = identical, 2 = opposite)."""
    return 1.0 - cosine_similarity(a, b)
