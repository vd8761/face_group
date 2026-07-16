"""
Application configuration — reads from environment variables.
All secrets must be set in .env (locally) or Render environment variables (production).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "PhotoGroup"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str  # Required — used for JWT signing
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    ALGORITHM: str = "HS256"

    # ── Super Admin seed credentials (created on first startup) ──────────────
    SUPER_ADMIN_EMAIL: str = "admin@photogroup.app"
    SUPER_ADMIN_PASSWORD: str  # Required — set a strong password

    # ── Neon DB ───────────────────────────────────────────────────────────────
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host/dbname

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL cannot be empty")
        # Handle Heroku/legacy style postgres:// -> postgresql://
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        # Ensure asyncpg driver is used
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Parse query string and remove unsupported arguments for asyncpg
        from urllib.parse import urlparse, urlencode, parse_qsl, urlunparse
        parsed = urlparse(v)
        if parsed.query:
            q_dict = dict(parse_qsl(parsed.query))
            # Rename sslmode to ssl
            if "sslmode" in q_dict:
                q_dict["ssl"] = q_dict.pop("sslmode")
            # Remove unsupported arguments
            q_dict.pop("channel_binding", None)
            
            # Reconstruct URL
            new_query = urlencode(q_dict)
            parsed = parsed._replace(query=new_query)
            v = urlunparse(parsed)

        return v

    # ── Cloudflare R2 (S3-compatible) ─────────────────────────────────────────
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    R2_PUBLIC_URL: Optional[str] = None  # Optional CDN URL prefix

    # ── Google Drive Import ───────────────────────────────────────────────────
    GOOGLE_DRIVE_API_KEY: Optional[str] = None  # Free API key from Google Cloud Console

    # ── Upstash Redis (Celery broker + result backend) ────────────────────────
    REDIS_URL: str  # rediss://default:token@host:6380

    @field_validator("REDIS_URL", mode="after")
    @classmethod
    def check_redis_url(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("REDIS_URL cannot be empty. Please set it in your environment variables.")
        # Auto-fix Upstash URLs to use SSL (rediss://)
        if v.startswith("redis://") and "upstash" in v.lower():
            v = v.replace("redis://", "rediss://", 1)
        return v

    # ── ML Pipeline ───────────────────────────────────────────────────────────
    # Pin the recognition model: embeddings from different model packs are not
    # comparable, even when both happen to contain 512 float32 values.
    INSIGHTFACE_MODEL: str = "buffalo_l"
    # Matches the model cache populated by backend/Dockerfile. Local GPU
    # installations can override this with an absolute persistent directory.
    INSIGHTFACE_HOME: str = "/tmp/insightface_cache"
    FACE_PIPELINE_VERSION: str = "insightface-buffalo-l-v2"
    EMBEDDING_DIM: int = 512                     # ArcFace 512-dim

    # Detector detail. A global pass is followed by an overlapping 2x2 tiled
    # pass for large images, which preserves small faces in group photographs.
    FACE_PROCESS_MAX_DIM: int = 1920
    FACE_DETECTION_SIZE: int = 1024
    FACE_ENABLE_TILING: bool = True
    FACE_TILE_TRIGGER_DIM: int = 1600
    FACE_TILE_OVERLAP: float = 0.12
    FACE_DEDUP_IOU_THRESHOLD: float = 0.40

    # Hard usability and high-quality anchor gates are deliberately separate.
    # A 24-59px face can attach to a strong identity but cannot bridge clusters.
    FACE_HARD_DETECTION_THRESHOLD: float = 0.60
    FACE_DETECTION_THRESHOLD: float = 0.80       # High-quality anchor threshold
    FACE_HARD_MIN_SIZE: int = 24
    FACE_MIN_SIZE: int = 60                      # Backwards-compatible anchor size
    FACE_ANCHOR_MIN_SIZE: int = 60
    FACE_HARD_MAX_YAW: float = 65.0
    FACE_ANCHOR_MAX_YAW: float = 45.0
    FACE_ANCHOR_QUALITY_THRESHOLD: float = 0.58

    # ── Agglomerative Clustering ──────────────────────────────────────────────
    AGGLOMERATIVE_DISTANCE_THRESHOLD: float = 0.45
    COSINE_MATCH_THRESHOLD: float = 0.45          # < this = same person (lower = stricter)
    CLUSTER_MAX_DISTANCE_THRESHOLD: float = 0.52  # Prevent average-link chaining
    FACE_ATTACH_DISTANCE_THRESHOLD: float = 0.38  # Strict low-quality attachment
    FACE_ATTACH_MARGIN: float = 0.05
    CLUSTER_ID_REUSE_MIN_OVERLAP: float = 0.50

    # Selfie search has a separate one-to-many risk profile. Moderate matches
    # need support from multiple person prototypes; very strong matches do not.
    SELFIE_MATCH_THRESHOLD: float = 0.50
    SELFIE_STRONG_MATCH_THRESHOLD: float = 0.38
    SELFIE_MATCH_MARGIN: float = 0.08
    SELFIE_PROTOTYPES_PER_CLUSTER: int = 5

    # ── File size limits ──────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 100  # Per-photo max (RAW files can be 50-80MB)

    # MIME types accepted for selfie scans (faces.py + public.py)
    # Broad format support — attendees may use phone cameras with various formats
    ALLOWED_IMAGE_TYPES: set = {
        "image/jpeg", "image/jpg", "image/png",
        "image/webp", "image/heic", "image/heif",
    }


    # Extension-based allowlist for event photo uploads (Manual + Google Drive).
    # JPEG/JPG only — simplifies processing and reduces storage costs.
    ALLOWED_IMAGE_EXTENSIONS: set = {
        ".jpg", ".jpeg", ".jpe", ".jfif",
    }

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "https://*.vercel.app"]

    # ── Rate limiting ─────────────────────────────────────────────────────────
    SCAN_RATE_LIMIT: int = 10  # Max selfie scan requests per IP per hour

    @model_validator(mode="after")
    def validate_face_pipeline(self):
        # Older deployments exposed FACE_MIN_SIZE. Honor it as the anchor size
        # unless the new explicit setting was also supplied.
        fields_set = getattr(self, "model_fields_set", set())
        if "FACE_MIN_SIZE" in fields_set and "FACE_ANCHOR_MIN_SIZE" not in fields_set:
            self.FACE_ANCHOR_MIN_SIZE = self.FACE_MIN_SIZE

        unit_interval = (
            "FACE_TILE_OVERLAP",
            "FACE_DEDUP_IOU_THRESHOLD",
            "FACE_HARD_DETECTION_THRESHOLD",
            "FACE_DETECTION_THRESHOLD",
            "FACE_ANCHOR_QUALITY_THRESHOLD",
            "AGGLOMERATIVE_DISTANCE_THRESHOLD",
            "COSINE_MATCH_THRESHOLD",
            "CLUSTER_MAX_DISTANCE_THRESHOLD",
            "FACE_ATTACH_DISTANCE_THRESHOLD",
            "FACE_ATTACH_MARGIN",
            "SELFIE_MATCH_THRESHOLD",
            "SELFIE_STRONG_MATCH_THRESHOLD",
            "SELFIE_MATCH_MARGIN",
        )
        for field_name in unit_interval:
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")

        # Old deployments commonly carry 0.65-0.75 clustering values. Keep
        # startup backward-compatible while enforcing the safer v2 ceilings.
        self.AGGLOMERATIVE_DISTANCE_THRESHOLD = min(
            self.AGGLOMERATIVE_DISTANCE_THRESHOLD, 0.45
        )
        self.COSINE_MATCH_THRESHOLD = min(self.COSINE_MATCH_THRESHOLD, 0.45)
        self.FACE_ATTACH_DISTANCE_THRESHOLD = min(
            self.FACE_ATTACH_DISTANCE_THRESHOLD,
            self.COSINE_MATCH_THRESHOLD,
            0.38,
        )
        if self.FACE_HARD_MIN_SIZE > self.FACE_ANCHOR_MIN_SIZE:
            raise ValueError("FACE_HARD_MIN_SIZE cannot exceed FACE_ANCHOR_MIN_SIZE")
        if self.FACE_HARD_DETECTION_THRESHOLD > self.FACE_DETECTION_THRESHOLD:
            raise ValueError(
                "FACE_HARD_DETECTION_THRESHOLD cannot exceed FACE_DETECTION_THRESHOLD"
            )
        if self.COSINE_MATCH_THRESHOLD > self.CLUSTER_MAX_DISTANCE_THRESHOLD:
            raise ValueError("COSINE_MATCH_THRESHOLD cannot exceed the complete-link gate")
        return self

@lru_cache()
def get_settings() -> Settings:
    return Settings()
