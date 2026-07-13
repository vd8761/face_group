"""
Downloads router — single photo download and streaming ZIP for bulk download.
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import Photo, User, AuditLog
from ..auth import require_attendee
from ..services.storage import generate_presigned_url, stream_object
from ..services.zip_stream import stream_zip
from ..schemas import ZipDownloadRequest

router = APIRouter(prefix="/downloads", tags=["Downloads"])


@router.post("/zip")
async def download_zip(
    body: ZipDownloadRequest,
    current_user: User = Depends(require_attendee),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream a ZIP archive of selected photos (FR-4.3, FR-4.4).
    Memory usage is proportional to one photo — not the total archive.
    """
    # Fetch and verify photos belong to user's tenant
    result = await db.execute(
        select(Photo).where(
            Photo.id.in_(body.photo_ids),
            Photo.tenant_id == current_user.tenant_id,
        )
    )
    photos = result.scalars().all()

    if not photos:
        raise HTTPException(status_code=404, detail="No accessible photos found")

    # Build (key, filename) pairs for ZIP
    pairs = [(p.original_key, p.filename) for p in photos]

    # Audit
    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="photo.zip_download",
        resource_type="photo_set",
        resource_id=None,
        payload={"photo_count": len(photos)},
    ))
    await db.commit()

    return StreamingResponse(
        stream_zip(pairs),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=my_photos.zip"},
    )
