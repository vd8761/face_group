"""
Photos router — bulk upload, listing with status, and signed URL serving.
"""
import uuid
import hashlib
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

    created_ids  = []
    file_bytes_list = []
    total_bytes  = 0
    duplicates   = []   # files skipped because hash already exists
    skipped_fmt  = []   # files skipped due to bad format/size

    for file in files:
        # Validate type
        if file.content_type not in settings.ALLOWED_IMAGE_TYPES:
            skipped_fmt.append(file.filename)
            continue

        data = await file.read()

        # Validate size
        if len(data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            skipped_fmt.append(file.filename)
            continue

        # ── SHA-256 duplicate check ──────────────────────────────────────────
        content_hash = hashlib.sha256(data).hexdigest()

        existing = await db.execute(
            select(Photo).where(
                Photo.event_id == event_id,
                Photo.content_hash == content_hash,
            )
        )
        if existing.scalar_one_or_none():
            duplicates.append(file.filename)
            continue   # Skip — exact same file already in this event
        # ────────────────────────────────────────────────────────────────────

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
            content_hash=content_hash,          # ← store hash for future dedup
            status=PhotoStatus.processing,
        )
        db.add(photo)
        total_bytes += len(data)
        created_ids.append(str(photo_id))
        file_bytes_list.append(data)

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
        payload={"count": len(created_ids)},
    ))

    # Process ML pipeline immediately (synchronously in threadpool)
    # We do not use Celery anymore to prevent OOM and ensure immediate processing
    from fastapi.concurrency import run_in_threadpool
    from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes
    from ..services.clustering import assign_to_cluster, create_new_cluster
    from ..models import FaceDetection

    for pid, data_bytes in zip(created_ids, file_bytes_list):
        photo_uuid = uuid.UUID(pid)
        try:
            # 1. Detect faces
            detected_faces = await run_in_threadpool(detect_and_embed, data_bytes)
            
            # 2. Store detections & assign clusters
            for face in detected_faces:
                detection = FaceDetection(
                    photo_id=photo_uuid,
                    bbox={"x1": face.bbox[0], "y1": face.bbox[1], "x2": face.bbox[2], "y2": face.bbox[3]},
                    detection_confidence=face.confidence,
                    quality_score=face.quality_score,
                    embedding=embedding_to_bytes(face.embedding),
                    is_low_quality=face.is_low_quality,
                )
                db.add(detection)
                await db.flush()

                if not face.is_low_quality:
                    cluster_id = await assign_to_cluster(
                        detection.id, face.embedding, event_id, db
                    )
                    if cluster_id is None:
                        await create_new_cluster(
                            detection.id, face.embedding, event_id, db
                        )
            
            # 3. Mark as done
            result = await db.execute(select(Photo).where(Photo.id == photo_uuid))
            photo_obj = result.scalar_one()
            photo_obj.status = PhotoStatus.done
            await db.commit()
            
        except Exception as e:
            await db.rollback()
            # Update to failed on error
            result = await db.execute(select(Photo).where(Photo.id == photo_uuid))
            photo_obj = result.scalar_one_or_none()
            if photo_obj:
                photo_obj.status = PhotoStatus.failed
                photo_obj.error_message = str(e)[:500]
                await db.commit()


    return {
        "accepted":        len(created_ids),
        "skipped_format":  len(skipped_fmt),
        "duplicates":      len(duplicates),
        "duplicate_names": duplicates,          # filenames that were exact duplicates
        "photo_ids":       created_ids,
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
# Delete photos (bulk clear)
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/events/{event_id}/clear")
async def clear_event_photos(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
    status_filter: str = "all" # 'all', 'failed', 'queued'
):
    """
    Deletes photos from the database for an event. 
    In a real app, this should also delete objects from R2. 
    Here we delete DB rows to clear UI state.
    """
    await _get_event_or_404(event_id, current_user.tenant_id, db)

    query = select(Photo).where(Photo.event_id == event_id)
    if status_filter != "all":
        query = query.where(Photo.status == status_filter)

    from ..services.storage import delete_objects
    from fastapi.concurrency import run_in_threadpool

    result = await db.execute(query)
    photos = result.scalars().all()

    keys_to_delete = []
    for p in photos:
        if p.original_key:
            keys_to_delete.append(p.original_key)
        if p.thumbnail_key:
            keys_to_delete.append(p.thumbnail_key)
        await db.delete(p)
    
    if keys_to_delete:
        # Boto3 delete_objects takes max 1000 keys per request
        for i in range(0, len(keys_to_delete), 1000):
            await run_in_threadpool(delete_objects, keys_to_delete[i:i+1000])
    
    # Also delete face clusters if we are clearing all photos
    if status_filter == "all":
        from ..models import FaceCluster
        clusters_res = await db.execute(select(FaceCluster).where(FaceCluster.event_id == event_id))
        for c in clusters_res.scalars().all():
            await db.delete(c)

    await db.commit()
    return MessageResponse(message=f"Deleted {len(photos)} photos.")


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
