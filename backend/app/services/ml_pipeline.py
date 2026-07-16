"""
ML pipeline service — face detection and embedding using InsightFace buffalo_l.
Uses the buffalo_l model pack (RetinaFace detector + ArcFace embedder).

# Memory budget on a 4 GB worker:
#   - buffalo_l model:  constant, loaded once per worker process
#   - Image views:      bounded global pass plus one tile at a time
#
# Key memory controls:
#   - MAX_PROCESS_DIM: images are downscaled before detection (default 1920px)
#   - RAW half_size=True: 40MP ARW → 10MP before numpy array is created
#   - gc.collect() after every image frees numpy arrays immediately
#   - Celery worker concurrency limits simultaneous model instances
"""
import io
import os
import gc
import sys
import hashlib
import json
from pathlib import Path
import numpy as np
from typing import Iterator, List, Sequence
from dataclasses import dataclass

from ..config import get_settings

settings = get_settings()

# Keep model files in a stable local cache unless deployment overrides it.
os.environ.setdefault("INSIGHTFACE_HOME", os.path.expanduser(settings.INSIGHTFACE_HOME))

# ── Memory safety ────────────────────────────────────────────────────────────
# Max long edge for the global detector pass. Large originals also receive an
# overlapping 2x2 tiled pass so small group-photo faces retain useful detail.
MAX_PROCESS_DIM = settings.FACE_PROCESS_MAX_DIM

# Memory safety: the deployed Celery worker runs at concurrency=1, so one
# process owns the model and its detector buffers on a 4 GB instance.

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
    - Detector views are bounded later without discarding the original crop data
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
_dll_directory_handles = []
_runtime_providers: tuple[str, ...] = ()
_processing_device = "NOT_LOADED"


def _prepare_windows_gpu_runtime() -> None:
    """Keep pip-installed NVIDIA DLL directories available to cuDNN."""
    if os.name != "nt" or _dll_directory_handles:
        return

    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.is_dir():
        return

    bin_dirs = [path for path in nvidia_root.glob("*/bin") if path.is_dir()]
    if not bin_dirs:
        return

    current_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(
        [*(str(path) for path in bin_dirs), current_path]
    )
    if hasattr(os, "add_dll_directory"):
        for path in bin_dirs:
            _dll_directory_handles.append(os.add_dll_directory(str(path)))


def _get_insightface_app():
    global _app, _runtime_providers, _processing_device
    if _app is None:
        from insightface.app import FaceAnalysis
        import onnxruntime as ort

        _prepare_windows_gpu_runtime()
        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls(directory="")
        
        providers = ["CPUExecutionProvider"]
        if "CUDAExecutionProvider" in ort.get_available_providers():
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

        detector_size = int(settings.FACE_DETECTION_SIZE)

        def build_app(active_providers: list[str]):
            app = FaceAnalysis(
                name=settings.INSIGHTFACE_MODEL,
                root=os.path.expanduser(settings.INSIGHTFACE_HOME),
                providers=active_providers,
            )
            app.prepare(
                ctx_id=0 if active_providers[0] == "CUDAExecutionProvider" else -1,
                det_thresh=float(settings.FACE_HARD_DETECTION_THRESHOLD),
                det_size=(detector_size, detector_size),
            )
            return app

        try:
            app = build_app(providers)
        except Exception:
            if providers[0] != "CUDAExecutionProvider":
                raise
            # A CUDA provider can be registered while its DLL/runtime is still
            # unusable. Fall back explicitly and report CPU as the actual device.
            providers = ["CPUExecutionProvider"]
            app = build_app(providers)
        _app = app

        # Ask the constructed ONNX sessions which providers they actually use;
        # availability alone does not prove CUDA initialised successfully.
        actual: list[str] = []
        for model in getattr(_app, "models", {}).values():
            session = getattr(model, "session", None)
            if session is None or not hasattr(session, "get_providers"):
                continue
            for provider in session.get_providers():
                if provider not in actual:
                    actual.append(provider)
        _runtime_providers = tuple(actual or providers)
        primary = _runtime_providers[0] if _runtime_providers else "CPUExecutionProvider"
        _processing_device = "GPU" if primary == "CUDAExecutionProvider" else "CPU"
    return _app


def get_pipeline_version() -> str:
    """Stable identifier for embeddings produced by this exact pipeline."""
    identity = {
        "model": settings.INSIGHTFACE_MODEL,
        "embedding_dim": settings.EMBEDDING_DIM,
        "process_max_dim": settings.FACE_PROCESS_MAX_DIM,
        "detection_size": settings.FACE_DETECTION_SIZE,
        "tiling": settings.FACE_ENABLE_TILING,
        "tile_trigger": settings.FACE_TILE_TRIGGER_DIM,
        "tile_overlap": settings.FACE_TILE_OVERLAP,
        "dedup_iou": settings.FACE_DEDUP_IOU_THRESHOLD,
        "hard_detection": settings.FACE_HARD_DETECTION_THRESHOLD,
        "anchor_detection": settings.FACE_DETECTION_THRESHOLD,
        "hard_min_size": settings.FACE_HARD_MIN_SIZE,
        "anchor_min_size": settings.FACE_ANCHOR_MIN_SIZE,
        "hard_max_yaw": settings.FACE_HARD_MAX_YAW,
        "anchor_max_yaw": settings.FACE_ANCHOR_MAX_YAW,
        "anchor_quality": settings.FACE_ANCHOR_QUALITY_THRESHOLD,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"{settings.FACE_PIPELINE_VERSION}:{settings.INSIGHTFACE_MODEL}:{digest}"[:100]


def get_processing_device(*, load_model: bool = True) -> str:
    """Return the provider actually selected by the loaded ONNX sessions."""
    if load_model and _app is None:
        _get_insightface_app()
    return _processing_device


def get_ml_runtime_info(*, load_model: bool = False) -> dict:
    """Non-secret runtime metadata suitable for health/telemetry payloads."""
    if load_model and _app is None:
        _get_insightface_app()
    return {
        "pipeline_version": get_pipeline_version(),
        "model": settings.INSIGHTFACE_MODEL,
        "device": _processing_device,
        "providers": list(_runtime_providers),
        "detection_size": int(settings.FACE_DETECTION_SIZE),
        "tiled_detection": bool(settings.FACE_ENABLE_TILING),
    }


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class DetectedFace:
    bbox: list
    confidence: float
    embedding: np.ndarray   # 512-dim float32, already L2-normalised
    quality_score: float
    is_low_quality: bool
    face_crop_bytes: bytes  # JPEG-encoded face crop (with margin)
    is_anchor_quality: bool = False


@dataclass
class _FaceCandidate:
    """A detector result transformed into original-image coordinates."""
    bbox: list[float]
    confidence: float
    embedding: np.ndarray
    pose: tuple[float, float, float]
    sample_size: tuple[float, float]
    rank_score: float


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection-over-union for two ``[x1, y1, x2, y2]`` boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def non_maximum_face_indices(
    boxes: Sequence[Sequence[float]],
    scores: Sequence[float],
    iou_threshold: float,
) -> list[int]:
    """Return stable score-ordered indices after global face-box de-duplication."""
    if len(boxes) != len(scores):
        raise ValueError("boxes and scores must have the same length")
    order = sorted(range(len(boxes)), key=lambda idx: (-scores[idx], idx))
    kept: list[int] = []
    for idx in order:
        if all(bbox_iou(boxes[idx], boxes[other]) < iou_threshold for other in kept):
            kept.append(idx)
    return kept


def _resize_detection_view(view: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Resize a detector view and return x/y scale back to the supplied view."""
    import cv2

    height, width = view.shape[:2]
    longest = max(height, width)
    if longest <= MAX_PROCESS_DIM:
        contiguous = view if view.flags.c_contiguous else np.ascontiguousarray(view)
        return contiguous, 1.0, 1.0
    scale = MAX_PROCESS_DIM / longest
    resized = cv2.resize(
        view,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, width / resized.shape[1], height / resized.shape[0]


def _iter_detection_views(
    img: np.ndarray,
) -> Iterator[tuple[np.ndarray, int, int, float, float]]:
    """Yield a global view then an overlapping 2x2 grid for large originals."""
    height, width = img.shape[:2]
    global_view, sx, sy = _resize_detection_view(img)
    yield global_view, 0, 0, sx, sy

    if not settings.FACE_ENABLE_TILING or max(height, width) < settings.FACE_TILE_TRIGGER_DIM:
        return

    overlap = min(0.40, max(0.0, float(settings.FACE_TILE_OVERLAP)))
    x_mid, y_mid = width // 2, height // 2
    x_pad = int(width * overlap / 2)
    y_pad = int(height * overlap / 2)
    x_ranges = ((0, min(width, x_mid + x_pad)), (max(0, x_mid - x_pad), width))
    y_ranges = ((0, min(height, y_mid + y_pad)), (max(0, y_mid - y_pad), height))

    for y1, y2 in y_ranges:
        for x1, x2 in x_ranges:
            tile = img[y1:y2, x1:x2]
            if tile.size == 0:
                continue
            view, tile_sx, tile_sy = _resize_detection_view(tile)
            yield view, x1, y1, tile_sx, tile_sy


def _normalise_embedding(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1).copy()
    if vector.size != settings.EMBEDDING_DIM:
        raise ValueError(
            f"Unexpected embedding dimension {vector.size}; expected {settings.EMBEDDING_DIM}"
        )
    if not np.all(np.isfinite(vector)):
        raise ValueError("Embedding contains non-finite values")
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("Embedding has zero norm")
    return vector / norm


def _collect_face_candidates(app, img: np.ndarray) -> list[_FaceCandidate]:
    candidates: list[_FaceCandidate] = []
    for view, offset_x, offset_y, scale_x, scale_y in _iter_detection_views(img):
        faces = app.get(view)
        for face in faces:
            raw_bbox = np.asarray(face.bbox, dtype=float).tolist()
            raw_width = max(0.0, raw_bbox[2] - raw_bbox[0])
            raw_height = max(0.0, raw_bbox[3] - raw_bbox[1])
            if raw_width <= 0 or raw_height <= 0:
                continue
            try:
                embedding = _normalise_embedding(face.normed_embedding)
            except (TypeError, ValueError):
                continue

            confidence = float(face.det_score)
            pose_values = getattr(face, "pose", None)
            if pose_values is not None and len(pose_values) >= 3:
                pitch, yaw, roll = (float(v) for v in pose_values[:3])
            else:
                pitch, yaw, roll = 0.0, 0.0, 0.0

            bbox = [
                raw_bbox[0] * scale_x + offset_x,
                raw_bbox[1] * scale_y + offset_y,
                raw_bbox[2] * scale_x + offset_x,
                raw_bbox[3] * scale_y + offset_y,
            ]
            # Prefer a tiled result where the recognizer saw more source pixels,
            # while still favouring detector confidence.
            detail_score = min(1.0, min(raw_width, raw_height) / 112.0)
            rank_score = confidence * (0.65 + 0.35 * detail_score)
            candidates.append(_FaceCandidate(
                bbox=bbox,
                confidence=confidence,
                embedding=embedding,
                pose=(pitch, yaw, roll),
                sample_size=(raw_width, raw_height),
                rank_score=rank_score,
            ))

    kept = non_maximum_face_indices(
        [candidate.bbox for candidate in candidates],
        [candidate.rank_score for candidate in candidates],
        float(settings.FACE_DEDUP_IOU_THRESHOLD),
    )
    return [candidates[idx] for idx in kept]


def _crop_quality(crop: np.ndarray) -> tuple[float, float]:
    """Return bounded sharpness and exposure scores for a face crop."""
    import cv2

    preview = crop
    if max(preview.shape[:2]) > 160:
        scale = 160 / max(preview.shape[:2])
        preview = cv2.resize(
            preview,
            (max(1, int(preview.shape[1] * scale)), max(1, int(preview.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
    sharpness = min(1.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 120.0)
    exposure = max(0.0, 1.0 - abs(float(gray.mean()) - 127.5) / 127.5)
    return sharpness, exposure


# ── Main detection function ───────────────────────────────────────────────────
def detect_and_embed(image_bytes: bytes, filename: str = '') -> List[DetectedFace]:
    """
    Run face detection + ArcFace embedding on raw image bytes.

    Memory-safe:
    - Decodes at half_size for RAW files
    - Bounds the global view and processes one overlapping tile at a time
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

        # Global + tiled inference produces original-coordinate candidates.
        candidates = _collect_face_candidates(app, img)
        results: List[DetectedFace] = []

        for candidate in candidates:
            confidence = candidate.confidence
            embedding = candidate.embedding

            # Clamp original-coordinate bbox to image bounds.
            x1 = max(0, min(int(round(candidate.bbox[0])), img_w - 1))
            y1 = max(0, min(int(round(candidate.bbox[1])), img_h - 1))
            x2 = max(0, min(int(round(candidate.bbox[2])), img_w))
            y2 = max(0, min(int(round(candidate.bbox[3])), img_h))
            bbox = [x1, y1, x2, y2]

            w_f = x2 - x1
            h_f = y2 - y1
            if w_f <= 0 or h_f <= 0:
                continue

            # Face crop with 25 % margin
            mx = int(w_f * 0.25)
            my = int(h_f * 0.25)
            cx1 = max(0, x1 - mx);  cy1 = max(0, y1 - my)
            cx2 = min(img_w, x2 + mx); cy2 = min(img_h, y2 + my)

            crop = img[cy1:cy2, cx1:cx2]
            if crop.size == 0:
                continue

            pitch, yaw, _roll = candidate.pose
            sample_min_size = min(candidate.sample_size)
            hard_usable = (
                sample_min_size >= settings.FACE_HARD_MIN_SIZE
                and confidence >= settings.FACE_HARD_DETECTION_THRESHOLD
                and abs(yaw) <= settings.FACE_HARD_MAX_YAW
            )
            anchor_geometry = (
                hard_usable
                and sample_min_size >= settings.FACE_ANCHOR_MIN_SIZE
                and confidence >= settings.FACE_DETECTION_THRESHOLD
                and abs(yaw) <= settings.FACE_ANCHOR_MAX_YAW
            )

            sharpness_score, exposure_score = _crop_quality(crop)
            size_score = min(1.0, sample_min_size / settings.FACE_ANCHOR_MIN_SIZE)
            pose_score = max(0.0, 1.0 - (abs(yaw) + 0.5 * abs(pitch)) / 90.0)
            quality_score = float(
                np.sqrt(max(0.0, confidence) * size_score)
                * (0.70 + 0.20 * sharpness_score + 0.10 * exposure_score)
                * (0.80 + 0.20 * pose_score)
            )
            is_anchor_quality = (
                anchor_geometry
                and quality_score >= settings.FACE_ANCHOR_QUALITY_THRESHOLD
            )
            # Persisted quality_score is also the anchor signal used during a
            # later recluster; cap attach-only faces just below that boundary.
            if not is_anchor_quality:
                quality_score = min(
                    quality_score,
                    float(settings.FACE_ANCHOR_QUALITY_THRESHOLD) - 1e-3,
                )
            is_low_quality = not hard_usable

            encoded, buf = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not encoded:
                continue
            face_crop_bytes = buf.tobytes()
            del crop, buf

            results.append(DetectedFace(
                bbox=bbox,
                confidence=confidence,
                embedding=embedding,
                quality_score=quality_score,
                is_low_quality=is_low_quality,
                face_crop_bytes=face_crop_bytes,
                is_anchor_quality=is_anchor_quality,
            ))

        # Spatial order makes downstream face indices deterministic across the
        # global/tiled detector passes.
        results.sort(key=lambda face: (face.bbox[1], face.bbox[0]))
        return results

    finally:
        # Always free the image array, even on exception
        if img is not None:
            del img
        gc.collect()


# ── Utilities ─────────────────────────────────────────────────────────────────
def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialise a float32 embedding to bytes for DB storage."""
    return _normalise_embedding(embedding).astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialise bytes back to a float32 numpy array."""
    expected_bytes = settings.EMBEDDING_DIM * np.dtype(np.float32).itemsize
    if len(data) != expected_bytes:
        raise ValueError(
            f"Incompatible embedding blob ({len(data)} bytes); expected {expected_bytes} "
            f"for {get_pipeline_version()}"
        )
    return _normalise_embedding(np.frombuffer(data, dtype=np.float32))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised embeddings (range −1 to 1)."""
    left = np.asarray(a, dtype=np.float32).reshape(-1)
    right = np.asarray(b, dtype=np.float32).reshape(-1)
    if left.shape != right.shape:
        raise ValueError(f"Embedding shape mismatch: {left.shape} != {right.shape}")
    left_norm, right_norm = np.linalg.norm(left), np.linalg.norm(right)
    if left_norm <= 0 or right_norm <= 0:
        raise ValueError("Cannot compare zero-norm embeddings")
    return float(np.clip(np.dot(left, right) / (left_norm * right_norm), -1.0, 1.0))


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (0 = identical, 2 = opposite)."""
    return 1.0 - cosine_similarity(a, b)
