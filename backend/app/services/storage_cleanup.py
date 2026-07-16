"""Helpers for removing photo assets from Cloudflare R2."""
from collections.abc import Sequence

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FaceDetection, Photo
from .storage import delete_objects


async def collect_photo_assets(
    db: AsyncSession,
    photos: Sequence[Photo],
) -> tuple[list[str], int]:
    """Collect object keys and accounted bytes without mutating storage."""
    if not photos:
        return [], 0

    photo_ids = [photo.id for photo in photos]
    keys = {
        key
        for photo in photos
        for key in (photo.original_key, photo.thumbnail_key)
        if key
    }

    for offset in range(0, len(photo_ids), 500):
        result = await db.execute(
            select(FaceDetection.face_key).where(
                FaceDetection.photo_id.in_(photo_ids[offset:offset + 500]),
                FaceDetection.face_key.is_not(None),
            )
        )
        keys.update(key for key in result.scalars().all() if key)

    return list(keys), sum(photo.original_size_bytes or 0 for photo in photos)


async def delete_asset_keys(key_list: Sequence[str]) -> None:
    """Delete already-collected keys, normally after the DB commit succeeds."""
    for offset in range(0, len(key_list), 1000):
        await run_in_threadpool(delete_objects, key_list[offset:offset + 1000])
