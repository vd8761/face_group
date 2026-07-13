"""
Cloudflare R2 (S3-compatible) storage service.
Provides upload, presigned URL generation, deletion, and thumbnail operations.
"""
import io
import uuid
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig
from PIL import Image

from ..config import get_settings

settings = get_settings()

# R2 endpoint format
R2_ENDPOINT = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
            region_name="auto",
        )
    return _s3_client


def _make_key(tenant_id: uuid.UUID, event_id: uuid.UUID, photo_id: uuid.UUID, variant: str, ext: str) -> str:
    """
    Deterministic object key structure:
    tenants/{tenant_id}/events/{event_id}/photos/{photo_id}/{variant}.{ext}
    """
    return f"tenants/{tenant_id}/events/{event_id}/photos/{photo_id}/{variant}.{ext}"


async def upload_original(
    data: bytes,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    photo_id: uuid.UUID,
    filename: str,
    mime_type: str,
) -> str:
    """Upload original photo to R2 and return its object key."""
    ext = Path(filename).suffix.lstrip(".").lower() or "jpg"
    key = _make_key(tenant_id, event_id, photo_id, "original", ext)
    get_s3_client().put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType=mime_type,
        Metadata={
            "tenant-id": str(tenant_id),
            "event-id": str(event_id),
            "photo-id": str(photo_id),
        },
    )
    return key


async def upload_thumbnail(
    data: bytes,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    photo_id: uuid.UUID,
    target_size: tuple = (400, 400),
) -> str:
    """Generate and upload a compressed JPEG thumbnail; return its object key."""
    img = Image.open(io.BytesIO(data))
    img.thumbnail(target_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=75, optimize=True)
    buf.seek(0)

    key = _make_key(tenant_id, event_id, photo_id, "thumbnail", "jpg")
    get_s3_client().put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=buf.getvalue(),
        ContentType="image/jpeg",
    )
    return key


def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a time-limited presigned URL for a private R2 object."""
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_object(key: str) -> None:
    """Delete a single object from R2."""
    get_s3_client().delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)


def delete_objects(keys: list[str]) -> None:
    """Batch-delete up to 1000 objects from R2."""
    if not keys:
        return
    get_s3_client().delete_objects(
        Bucket=settings.R2_BUCKET_NAME,
        Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True},
    )


def stream_object(key: str):
    """Return a streaming body for a given object (for ZIP assembly)."""
    resp = get_s3_client().get_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    return resp["Body"]
