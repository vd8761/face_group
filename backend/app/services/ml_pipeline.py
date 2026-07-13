"""
ML pipeline service — face detection and embedding using InsightFace buffalo_l.
Uses the buffalo_l model pack (RetinaFace detector + ArcFace embedder).
Requires ~1.5GB RAM — use Render Standard plan (2GB) or equivalent.
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


def detect_and_embed(image_bytes: bytes) -> List[DetectedFace]:
    """
    Run face detection + embedding on raw image bytes.
    Returns a list of DetectedFace objects, one per detected face.
    Faces below confidence or size thresholds are marked as low_quality.
    """
    import cv2

    app = _get_insightface_app()

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image — unsupported format or corrupted file.")

    # Limit image size to avoid excessive RAM during inference
    h, w = img.shape[:2]
    if max(h, w) > 1920:
        scale = 1920 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    
    # Store dimensions for bounds checking
    img_h, img_w = img.shape[:2]

    faces = app.get(img)
    results: List[DetectedFace] = []

    for face in faces:
        bbox = face.bbox.astype(int).tolist()
        confidence = float(face.det_score)
        embedding = face.normed_embedding

        w_face = bbox[2] - bbox[0]
        h_face = bbox[3] - bbox[1]
        face_size_ok = (w_face >= settings.FACE_MIN_SIZE and h_face >= settings.FACE_MIN_SIZE)
        confidence_ok = confidence >= settings.FACE_DETECTION_THRESHOLD
        is_low_quality = not (face_size_ok and confidence_ok)

        size_score = min(1.0, min(w_face, h_face) / 200.0)
        quality_score = float(np.sqrt(confidence * size_score))
        
        # Extract face crop with a small margin
        margin_x = int(w_face * 0.2)
        margin_y = int(h_face * 0.2)
        x1 = max(0, bbox[0] - margin_x)
        y1 = max(0, bbox[1] - margin_y)
        x2 = min(img_w, bbox[2] + margin_x)
        y2 = min(img_h, bbox[3] + margin_y)
        
        face_crop = img[y1:y2, x1:x2]
        _, buffer = cv2.imencode('.jpg', face_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
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
