"""
ML pipeline service — face detection and embedding using InsightFace buffalo_sc.

Model choice: buffalo_sc (small-compact)
  - Download size: ~85 MB (vs buffalo_l at ~500 MB)
  - Runtime RAM:   ~280 MB (vs buffalo_l at 1-2 GB)
  - Fits Render free tier 512 MB limit ✅
  - Accuracy: good enough for face grouping

The model is lazy-loaded on first request and cached in /tmp/insightface_cache
(writable on Render's ephemeral filesystem).
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
            name="buffalo_sc",          # Small-compact: ~85MB, ~280MB RAM
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        _app.prepare(ctx_id=0, det_size=(320, 320))  # 320x320 uses less RAM than 640x640
    return _app


@dataclass
class DetectedFace:
    bbox: list           # [x1, y1, x2, y2]
    confidence: float
    embedding: np.ndarray  # 512-dim float32
    quality_score: float
    is_low_quality: bool


def detect_and_embed(image_bytes: bytes) -> List[DetectedFace]:
    """
    Run face detection + embedding on raw image bytes.
    Returns a list of DetectedFace objects, one per detected face.
    """
    import cv2

    app = _get_insightface_app()

    # Downscale to max 1280px to limit memory usage during inference
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image — unsupported format or corrupted file.")

    h, w = img.shape[:2]
    max_dim = 1280
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))

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

        results.append(DetectedFace(
            bbox=bbox,
            confidence=confidence,
            embedding=embedding,
            quality_score=quality_score,
            is_low_quality=is_low_quality,
        ))

    return results


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialise a float32 embedding numpy array to bytes for DB storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialise bytes back to a float32 numpy array."""
    return np.frombuffer(data, dtype=np.float32).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised embeddings."""
    return float(np.dot(a, b))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (0 = identical, 2 = opposite)."""
    return 1.0 - cosine_similarity(a, b)
