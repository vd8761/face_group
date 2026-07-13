"""
Photos router — bulk upload, listing with status, and signed URL serving.
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import Photo, PhotoStatus, Event, Subscription, User, AuditLog
from ..auth import require_organizer, require_attendee, get_current_user
from ..services.storage import upload_original, upload_thumbnail, generate_presigned_url
from ..schemas import PhotoResponse, PhotoListResponse, MessageResponse
from ..workers.tasks import process_photo
from ..config import get_settings

settings = get_settings()
router = APIRouter(prefix="/photos", tags=["Photos"])


async def _get_event_or_404(event_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession) -> Event:
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


# ─────────────────────────────────────────────────────────────────────────────
# Upload
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/events/{event_id}/upload", status_code=202)
async def upload_photos(
    event_id: uuid.UUID,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk photo upload. Returns immediately (202 Accepted).
    Face processing happens asynchronously via Celery.
    """
    event = await _get_event_or_404(event_id, current_user.tenant_id, db)

    # Subscription photo-count guard
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
    )
    sub = sub_result.scalar_one_or_none()
    current_count = (await db.execute(
        select(func.count(Photo.id)).where(Photo.event_id == event_id)
    )).scalar()

    if sub and (current_count + len(files)) > sub.max_photos_per_event:
        raise HTTPException(
            status_code=403,
            detail=f"Photo limit for this plan is {sub.max_photos_per_event} per event. "
                   f"Already have {current_count}.",
        )

    created_ids = []
    total_bytes = 0

    for file in files:
        # Validate
        if file.content_type not in settings.ALLOWED_IMAGE_TYPES:
            continue  # Skip unsupported types silently; client handles validation

        data = await file.read()
        if len(data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            continue

        photo_id = uuid.uuid4()

        # Upload original + thumbnail to R2
        original_key = await upload_original(
            data, current_user.tenant_id, event_id, photo_id,
            file.filename or f"{photo_id}.jpg", file.content_type
        )
        thumbnail_key = await upload_thumbnail(
            data, current_user.tenant_id, event_id, photo_id
        )

        photo = Photo(
            id=photo_id,
            event_id=event_id,
            tenant_id=current_user.tenant_id,
            original_key=original_key,
            thumbnail_key=thumbnail_key,
            original_size_bytes=len(data),
            filename=file.filename or f"{photo_id}.jpg",
            mime_type=file.content_type,
            status=PhotoStatus.queued,
        )
        db.add(photo)
        total_bytes += len(data)
        created_ids.append(str(photo_id))

    await db.flush()

    # Update storage usage
    if sub:
        sub.current_storage_bytes = (sub.current_storage_bytes or 0) + total_bytes

    # Audit log
    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="photo.upload",
        resource_type="event",
        resource_id=str(event_id),
        metadata={"count": len(created_ids)},
    ))

    await db.commit()

    # Dispatch Celery tasks (one per photo)
    for pid in created_ids:
        process_photo.apply_async(
            args=[pid, str(current_user.tenant_id), str(event_id)],
            countdown=0,
        )

    return {
        "accepted": len(created_ids),
        "skipped": len(files) - len(created_ids),
        "photo_ids": created_ids,
    }


# ─────────────────────────────────────────────────────────────────────────────
# List photos
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/events/{event_id}", response_model=PhotoListResponse)
async def list_event_photos(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
):
    await _get_event_or_404(event_id, current_user.tenant_id, db)

    total = (await db.execute(
        select(func.count(Photo.id)).where(Photo.event_id == event_id)
    )).scalar()

    result = await db.execute(
        select(Photo)
        .where(Photo.event_id == event_id)
        .order_by(Photo.uploaded_at.desc())
        .offset(skip).limit(limit)
    )
    photos = result.scalars().all()

    out = []
    for p in photos:
        thumb_url = generate_presigned_url(p.thumbnail_key, expires_in=3600) if p.thumbnail_key else None
        out.append(PhotoResponse(
            id=p.id,
            filename=p.filename,
            status=p.status,
            error_message=p.error_message,
            uploaded_at=p.uploaded_at,
            thumbnail_url=thumb_url,
        ))

    return PhotoListResponse(photos=out, total=total)


# ─────────────────────────────────────────────────────────────────────────────
# Serve individual photo (signed URL)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{photo_id}/thumbnail")
async def get_thumbnail(
    photo_id: uuid.UUID,
    current_user: User = Depends(require_attendee),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Photo).where(Photo.id == photo_id))
    photo = result.scalar_one_or_none()
    if not photo or photo.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"url": generate_presigned_url(photo.thumbnail_key, expires_in=1800)}


@router.get("/{photo_id}/download")
async def get_original(
    photo_id: uuid.UUID,
    current_user: User = Depends(require_attendee),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Photo).where(Photo.id == photo_id))
    photo = result.scalar_one_or_none()
    if not photo or photo.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Audit
    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="photo.download",
        resource_type="photo",
        resource_id=str(photo_id),
    ))
    await db.commit()

    return {"url": generate_presigned_url(photo.original_key, expires_in=300)}
