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
        return v

    # ── ML Pipeline ───────────────────────────────────────────────────────────
    # InsightFace buffalo_l — best accuracy, requires 2GB RAM (Render Standard plan)
    FACE_DETECTION_THRESHOLD: float = 0.7
    FACE_MIN_SIZE: int = 40
    EMBEDDING_DIM: int = 512                     # ArcFace 512-dim

    # ── HDBSCAN Clustering ────────────────────────────────────────────────────
    HDBSCAN_MIN_CLUSTER_SIZE: int = 2
    COSINE_MATCH_THRESHOLD: float = 0.35          # < this = same person (lower = stricter)

    # ── File size limits ──────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 100  # Per-photo max (RAW files can be 50-80MB)

    # Extension-based allowlist — MIME types are unreliable for RAW files.
    # Browsers often report RAW/TIFF as application/octet-stream.
    ALLOWED_IMAGE_EXTENSIONS: set = {
        # Standard web formats
        ".jpg", ".jpeg", ".jpe", ".jfif",   # JPEG variants
        ".png",                               # PNG
        ".webp",                              # WebP
        ".gif",                               # GIF (single-frame treated as still)
        ".bmp",                               # Bitmap
        ".tif", ".tiff",                      # TIFF (used by studios)
        # Apple / Mobile
        ".heic", ".heif",                     # iPhone HEIC
        ".avif",                              # AVIF (modern mobile)
        # Sony
        ".arw", ".srf", ".sr2",
        # Canon
        ".cr2", ".cr3", ".crw",
        # Nikon
        ".nef", ".nrw",
        # Adobe / Universal RAW
        ".dng",
        # Fujifilm
        ".raf",
        # Olympus / OM System
        ".orf",
        # Panasonic
        ".rw2",
        # Pentax / Ricoh
        ".pef", ".ptx",
        # Samsung
        ".srw",
        # Hasselblad
        ".3fr", ".fff",
        # Phase One
        ".iiq",
        # Epson
        ".erf",
        # Minolta / Konica-Minolta
        ".mrw",
        # Sigma
        ".x3f",
        # Kodak
        ".k25", ".kdc", ".dcr",
        # Leica
        ".rwl", ".dng",
        # Mamiya
        ".mef", ".mfw", ".mos",
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
