"""
ML pipeline service — face detection and embedding using face_recognition (dlib).

Why face_recognition instead of InsightFace:
  - InsightFace (buffalo_l) requires ~1-2 GB RAM → OOM on Render free tier (512MB)
  - face_recognition (dlib HOG) uses ~120 MB RAM → fits comfortably on free tier
  - 128-dim embeddings are sufficient for face grouping/clustering
"""
import io
import numpy as np
from typing import List
from dataclasses import dataclass

from ..config import get_settings

settings = get_settings()


@dataclass
class DetectedFace:
    bbox: list           # [x1, y1, x2, y2]
    confidence: float    # always 1.0 for dlib (binary detection)
    embedding: np.ndarray  # 128-dim float64
    quality_score: float
    is_low_quality: bool


def detect_and_embed(image_bytes: bytes) -> List[DetectedFace]:
    """
    Run face detection + embedding on raw image bytes using face_recognition (dlib).
    Returns a list of DetectedFace objects, one per detected face.
    """
    import face_recognition

    # Decode image via Pillow (avoids OpenCV dependency)
    from PIL import Image
    img_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Downscale large images to prevent OOM during face detection
    MAX_DIM = 1280
    w, h = img_pil.size
    if max(w, h) > MAX_DIM:
        scale = MAX_DIM / max(w, h)
        img_pil = img_pil.resize(
            (int(w * scale), int(h * scale)),
            Image.LANCZOS
        )

    img_array = np.array(img_pil)

    # Detect face locations (HOG model is CPU-friendly, ~80MB RAM)
    locations = face_recognition.face_locations(img_array, model="hog")

    if not locations:
        return []

    # Compute 128-dim embeddings for each face
    encodings = face_recognition.face_encodings(img_array, locations)

    results: List[DetectedFace] = []
    for (top, right, bottom, left), encoding in zip(locations, encodings):
        w_face = right - left
        h_face = bottom - top
        face_size_ok = (w_face >= settings.FACE_MIN_SIZE and h_face >= settings.FACE_MIN_SIZE)
        is_low_quality = not face_size_ok

        # Quality score: normalised face area
        size_score = min(1.0, min(w_face, h_face) / 200.0)
        quality_score = float(size_score)

        results.append(DetectedFace(
            bbox=[left, top, right, bottom],  # [x1, y1, x2, y2]
            confidence=1.0,                   # dlib gives binary yes/no
            embedding=encoding,               # already L2-normalised
            quality_score=quality_score,
            is_low_quality=is_low_quality,
        ))

    return results


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialise a float64 embedding numpy array to bytes for DB storage."""
    return embedding.astype(np.float64).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialise bytes back to a float64 numpy array."""
    return np.frombuffer(data, dtype=np.float64).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embeddings (range -1 to 1)."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (0 = identical, 2 = opposite)."""
    return 1.0 - cosine_similarity(a, b)
