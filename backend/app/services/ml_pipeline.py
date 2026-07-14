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

# RAW file extensions handled by rawpy
RAW_EXTENSIONS = {'.arw', '.cr2', '.cr3', '.nef', '.dng', '.raf', '.orf', '.rw2', '.pef', '.srw'}


def _decode_image_to_bgr(image_bytes: bytes, filename: str = '') -> np.ndarray:
    """
    Decode any image format to a BGR numpy array for OpenCV/InsightFace.
    Handles: JPEG (with EXIF rotation), PNG, WEBP, TIFF, HEIC,
             and RAW camera formats (ARW, CR2, NEF, DNG, RAF, etc.).
    """
    import cv2
    from PIL import Image, ImageOps

    ext = os.path.splitext(filename.lower())[1] if filename else ''

    # ── RAW camera files ────────────────────────────────────────────────────
    if ext in RAW_EXTENSIONS:
        try:
            import rawpy
            with rawpy.imread(io.BytesIO(image_bytes)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True,
                    half_size=False,
                    no_auto_bright=False,
                    output_bps=8,
                )
            # rawpy gives RGB, convert to BGR for OpenCV
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except ImportError:
            pass  # rawpy not available, fall through to PIL attempt
        except Exception as e:
            raise ValueError(f"Failed to decode RAW file ({ext}): {e}")

    # ── HEIC / HEIF ─────────────────────────────────────────────────────────
    if ext in ('.heic', '.heif'):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise ValueError("HEIC files require pillow-heif. Please re-upload as JPEG.")

    # ── Standard formats via PIL (handles EXIF orientation) ─────────────────
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
        # Apply EXIF rotation — fixes portrait/rotated photos
        pil_img = ImageOps.exif_transpose(pil_img)
        pil_img = pil_img.convert('RGB')
        bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return bgr
    except Exception as pil_err:
        pass  # fall through to direct cv2 decode

    # ── Final fallback: raw cv2 decode ───────────────────────────────────────
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(
            f"Could not decode image — unsupported format '{ext}' or corrupted file. "
            "Please upload JPEG, PNG, WEBP, HEIC, or a RAW format (ARW, CR2, NEF, DNG)."
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
