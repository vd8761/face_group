"""
Application configuration — reads from environment variables.
All secrets must be set in .env (locally) or Render environment variables (production).
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
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
    # InsightFace buffalo_l — best accuracy, requires 2GB RAM (Render Standard plan)
    FACE_DETECTION_THRESHOLD: float = 0.80
    FACE_MIN_SIZE: int = 60
    EMBEDDING_DIM: int = 512                     # ArcFace 512-dim

    # ── Agglomerative Clustering ──────────────────────────────────────────────
    AGGLOMERATIVE_DISTANCE_THRESHOLD: float = 0.75
    COSINE_MATCH_THRESHOLD: float = 0.75          # < this = same person (lower = stricter)

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

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
