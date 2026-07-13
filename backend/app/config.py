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

    # ── Upstash Redis (Celery broker + result backend) ────────────────────────
    REDIS_URL: str  # rediss://default:token@host:6380

    @field_validator("REDIS_URL", mode="after")
    @classmethod
    def check_redis_url(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("REDIS_URL cannot be empty. Please set it in your environment variables.")
        return v

    # ── ML Pipeline ───────────────────────────────────────────────────────────
    INSIGHTFACE_MODEL: str = "buffalo_l"          # RetinaFace + ArcFace
    FACE_DETECTION_THRESHOLD: float = 0.7        # Min confidence to accept a detection
    FACE_MIN_SIZE: int = 40                       # Min face bounding box width/height (px)
    EMBEDDING_DIM: int = 512                     # ArcFace output dimension

    # ── HDBSCAN Clustering ────────────────────────────────────────────────────
    HDBSCAN_MIN_CLUSTER_SIZE: int = 2
    COSINE_MATCH_THRESHOLD: float = 0.35          # < this = same person (lower = stricter)

    # ── File size limits ──────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 25                  # Per-photo max
    ALLOWED_IMAGE_TYPES: list[str] = ["image/jpeg", "image/png", "image/heic", "image/webp"]

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
