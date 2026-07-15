"""
Photos router — bulk upload, listing with status, retry, and signed URL serving.
"""
import uuid
import hashlib
import asyncio
import os
import io
import gc
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db, async_session_maker
from ..models import Photo, PhotoStatus, Event, Subscription, User, AuditLog, FaceDetection, FaceCluster
from ..auth import require_organizer, require_attendee, get_current_user
from ..services.storage import (
    upload_original, upload_thumbnail, upload_face_crop,
    generate_presigned_url, delete_objects, stream_object
)
from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes
from ..services.clustering import assign_to_cluster, create_new_cluster
from ..schemas import PhotoResponse, PhotoListResponse, MessageResponse
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
# Background face processing — runs AFTER the HTTP response is already sent
# ─────────────────────────────────────────────────────────────────────────────
async def _process_photos_background(
    photo_ids: List[str],
    file_bytes_list: List[bytes],
    filenames: List[str],
    event_id: uuid.UUID,
    event: Event,
):
    """
    Run face detection + clustering on each photo after the HTTP 202 response
    is already sent to the client. Uses its own DB session so it won't affect
    the response session.
    Photos are processed ONE AT A TIME to keep memory usage within 2 GB.
    The image bytes are deleted after each photo to free RAM immediately.
    """

    for pid, data_bytes, fname in zip(photo_ids, file_bytes_list, filenames):
        photo_uuid = uuid.UUID(pid)
        async with async_session_maker() as db:
            try:
                detected_faces = await run_in_threadpool(detect_and_embed, data_bytes, fname)
                # Free the raw image bytes immediately — they can be 50-100 MB for RAW files
                del data_bytes
                gc.collect()

                for face in detected_faces:
                    detection = FaceDetection(
                        photo_id=photo_uuid,
                        bbox={"x1": face.bbox[0], "y1": face.bbox[1],
                              "x2": face.bbox[2], "y2": face.bbox[3]},
                        detection_confidence=face.confidence,
                        quality_score=face.quality_score,
                        embedding=embedding_to_bytes(face.embedding),
                        is_low_quality=face.is_low_quality,
                    )
                    db.add(detection)
                    await db.flush()

                    if not face.is_low_quality:
                        face_key = await upload_face_crop(
                            face.face_crop_bytes,
                            event.tenant_id,
                            event_id,
                            detection.id
                        )
                        detection.face_key = face_key
                        await db.flush()

                        cluster_id = await assign_to_cluster(
                            detection.id, face.embedding, event_id, db
                        )
                        if cluster_id is None:
                            await create_new_cluster(
                                detection.id, face.embedding, event_id, db
                            )

                result = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                photo_obj = result.scalar_one_or_none()
                if photo_obj:
                    photo_obj.status = PhotoStatus.done
                await db.commit()

            except Exception as e:
                gc.collect()
                await db.rollback()
                try:
                    result = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                    photo_obj = result.scalar_one_or_none()
                    if photo_obj:
                        photo_obj.status = PhotoStatus.failed
                        photo_obj.error_message = str(e)[:500]
                        await db.commit()
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# Upload
# ─────────────────────────────────────────────────────────────────────────────
MAX_FILES_PER_REQUEST = 200  # Server-side batch cap — frontend may chunk larger uploads

@router.post("/events/{event_id}/upload", status_code=202)
async def upload_photos(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk photo upload — memory-safe version without Celery.

    For each file:
      1. Upload original + thumbnail to R2
      2. Save Photo DB row (status=queued)
      3. FREE bytes from RAM immediately

    Response is sent after all files are enqueued.
    Face detection runs via BackgroundTasks, downloading from R2 one by one.
    """
    import os as _os

    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum {MAX_FILES_PER_REQUEST} files per request. "
                   f"Split your upload into smaller batches.",
        )

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
    total_bytes  = 0
    duplicates   = []
    skipped_fmt  = []
    
    import traceback

    try:
        for file in files:
            fname = (file.filename or '').strip()
        ext   = _os.path.splitext(fname.lower())[1]

        # Extension whitelist (MIME types unreliable for RAW/TIFF)
        if ext not in settings.ALLOWED_IMAGE_EXTENSIONS:
            skipped_fmt.append(fname)
            continue

        data = await file.read()

        if len(data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            skipped_fmt.append(fname)
            del data
            continue

        # SHA-256 duplicate check
        content_hash = hashlib.sha256(data).hexdigest()
        existing = await db.execute(
            select(Photo).where(
                Photo.event_id == event_id,
                Photo.content_hash == content_hash,
            )
        )
        if existing.scalar_one_or_none():
            duplicates.append(fname)
            del data
            continue

        photo_id = uuid.uuid4()
        mime     = file.content_type or "application/octet-stream"

        # ── Upload to R2 ─────────────────────────────────────────────────────
        original_key  = await upload_original(
            data, current_user.tenant_id, event_id, photo_id,
            fname or f"{photo_id}{ext}", mime,
        )
        thumbnail_key = await upload_thumbnail(
            data, current_user.tenant_id, event_id, photo_id, filename=fname,
        )

        # ── Free image bytes IMMEDIATELY after R2 upload ──────────────────────
        # This is the critical fix: we do NOT buffer data in a list.
        # Each file's bytes are freed before moving to the next file.
        total_bytes += len(data)
        del data
        gc.collect()

        # ── Save DB row ───────────────────────────────────────────────────────
        photo = Photo(
            id=photo_id,
            event_id=event_id,
            tenant_id=current_user.tenant_id,
            original_key=original_key,
            thumbnail_key=thumbnail_key,
            original_size_bytes=0,   # bytes already freed
            filename=fname or f"{photo_id}{ext}",
            mime_type=mime,
            content_hash=content_hash,
            status=PhotoStatus.queued,
        )
        db.add(photo)
        await db.flush()   # get photo.id assigned before Celery dispatch

        # ── Dispatch to BackgroundTasks — zero RAM held in this process ─────────
        created_ids.append(str(photo_id))

    except Exception as e:
        import traceback
        err_msg = str(e)
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail={"error": err_msg, "traceback": tb})

    if sub and total_bytes:
        sub.current_storage_bytes = (sub.current_storage_bytes or 0) + total_bytes

    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="photo.upload",
        resource_type="event",
        resource_id=str(event_id),
        payload={"count": len(created_ids)},
    ))

    await db.commit()
    
    if created_ids:
        background_tasks.add_task(
            _reprocess_failed_background,
            photo_ids=created_ids,
            event=event,
        )

    return {
        "accepted":        len(created_ids),
        "skipped_format":  len(skipped_fmt),
        "duplicates":      len(duplicates),
        "duplicate_names": duplicates,
        "photo_ids":       created_ids,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Google Drive folder import
# ─────────────────────────────────────────────────────────────────────────────

def _parse_drive_folder_id(url: str) -> str:
    """
    Extract the folder ID from any Google Drive folder URL format:
      https://drive.google.com/drive/folders/FOLDER_ID
      https://drive.google.com/drive/folders/FOLDER_ID?usp=sharing
    """
    import re
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError("Could not parse a Google Drive folder ID from the URL provided.")
    return match.group(1)


@router.post("/events/{event_id}/import-drive", status_code=202)
async def import_from_drive(
    event_id: uuid.UUID,
    body: dict,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """
    Import all images from a public Google Drive folder.
    - Parses the folder ID from the shared URL
    - Lists image files via Google Drive API v3 (no OAuth needed for public folders)
    - Downloads & uploads each image to R2 + DB
    - Triggers background face detection
    Requires GOOGLE_DRIVE_API_KEY env var to be set.
    """
    if not settings.GOOGLE_DRIVE_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Google Drive import is not configured. Ask the admin to set GOOGLE_DRIVE_API_KEY.",
        )

    folder_url: str = body.get("folder_url", "").strip()
    if not folder_url:
        raise HTTPException(status_code=422, detail="folder_url is required.")

    try:
        folder_id = _parse_drive_folder_id(folder_url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await _get_event_or_404(event_id, current_user.tenant_id, db)

    # ── List all image files in the folder via Drive API v3 ──────────────────
    import httpx
    api_key = settings.GOOGLE_DRIVE_API_KEY
    drive_files = []
    page_token = None

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            params = {
                "q": f"'{folder_id}' in parents and trashed = false and (mimeType contains 'image/')",
                "key": api_key,
                "fields": "nextPageToken, files(id, name, mimeType, size)",
                "pageSize": 1000,
                "orderBy": "name",
            }
            if page_token:
                params["pageToken"] = page_token

            resp = await client.get(
                "https://www.googleapis.com/drive/v3/files",
                params=params,
            )
            if resp.status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="Google Drive folder is private. Make it public: Share → Anyone with the link → Viewer.",
                )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Google Drive API error {resp.status_code}: {resp.text[:200]}",
                )

            data = resp.json()
            drive_files.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    if not drive_files:
        return {"queued": 0, "message": "No image files found in this folder."}

    # ── Check subscription limit ──────────────────────────────────────────────
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
    )
    sub = sub_result.scalar_one_or_none()
    current_count = (await db.execute(
        select(func.count(Photo.id)).where(Photo.event_id == event_id)
    )).scalar()

    if sub and (current_count + len(drive_files)) > sub.max_photos_per_event:
        raise HTTPException(
            status_code=403,
            detail=f"Importing {len(drive_files)} photos would exceed your plan limit of {sub.max_photos_per_event}.",
        )

    # ── Create placeholder DB rows immediately (status=queued) ────────────────
    queued_items = []   # [(photo_id, file_id, filename, mime_type)]
    for f in drive_files:
        photo_id = uuid.uuid4()
        photo = Photo(
            id=photo_id,
            event_id=event_id,
            tenant_id=current_user.tenant_id,
            original_key="",       # filled in by background task
            thumbnail_key="",
            original_size_bytes=int(f.get("size") or 0),
            filename=f["name"],
            mime_type=f["mimeType"],
            content_hash=None,
            status=PhotoStatus.queued,
        )
        db.add(photo)
        queued_items.append((str(photo_id), f["id"], f["name"], f["mimeType"]))

    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="photo.drive_import",
        resource_type="event",
        resource_id=str(event_id),
        payload={"folder_id": folder_id, "count": len(queued_items)},
    ))
    await db.commit()

    # ── Fire-and-forget async task: download → R2 → Celery dispatch ──────────
    asyncio.create_task(
        _process_drive_import(
            queued_items=queued_items,
            api_key=api_key,
            event_id=event_id,
            tenant_id=current_user.tenant_id,
        )
    )

    return {
        "queued": len(queued_items),
        "message": f"Importing {len(queued_items)} photos from Google Drive in the background.",
        "files": [f["name"] for f in drive_files[:10]],  # preview of first 10
    }


async def _process_drive_import(
    queued_items: list,
    api_key: str,
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
):
    """
    Background task: for each queued Drive file:
    1. Download from Google Drive (with retry + exponential backoff for 403/429)
    2. Upload original + thumbnail to R2
    3. Update DB row with keys + hash
    4. Run face detection + clustering
    """

    async with httpx.AsyncClient(timeout=120) as client:
        for photo_id_str, file_id, filename, mime_type in queued_items:
            photo_uuid = uuid.UUID(photo_id_str)

            async with async_session_maker() as db:
                try:
                    # 1. Download from Drive with retry (handles 403/429/5xx)
                    download_url = (
                        f"https://www.googleapis.com/drive/v3/files/{file_id}"
                        f"?alt=media&key={api_key}"
                    )
                    data = None
                    for attempt in range(5):
                        resp = await client.get(
                            download_url,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; UrFace/1.0)"},
                            follow_redirects=True,
                        )
                        if resp.status_code == 200:
                            data = resp.content
                            break
                        elif resp.status_code in (403, 429, 500, 502, 503):
                            wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s
                            await asyncio.sleep(wait)
                            continue
                        else:
                            raise ValueError(f"Drive download failed: HTTP {resp.status_code}")
                    if data is None:
                        raise ValueError(f"Drive download failed after 5 retries (last status {resp.status_code})")

                    # 2. SHA-256 dedup check
                    content_hash = hashlib.sha256(data).hexdigest()
                    existing = await db.execute(
                        select(Photo).where(
                            Photo.event_id == event_id,
                            Photo.content_hash == content_hash,
                            Photo.id != photo_uuid,   # don't match self
                        )
                    )
                    if existing.scalar_one_or_none():
                        # Duplicate — delete placeholder row
                        res = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                        p = res.scalar_one_or_none()
                        if p:
                            await db.delete(p)
                        await db.commit()
                        continue

                    # 3. Upload to R2
                    original_key = await upload_original(
                        data, tenant_id, event_id, photo_uuid, filename, mime_type
                    )
                    thumbnail_key = await upload_thumbnail(
                        data, tenant_id, event_id, photo_uuid
                    )

                    # 4. Update DB row
                    res = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                    photo_obj = res.scalar_one()
                    photo_obj.original_key = original_key
                    photo_obj.thumbnail_key = thumbnail_key
                    photo_obj.original_size_bytes = len(data)
                    photo_obj.content_hash = content_hash
                    photo_obj.status = PhotoStatus.processing
                    await db.commit()

                    # 5. Face detection + clustering
                    detected_faces = await run_in_threadpool(detect_and_embed, data, filename)
                    for face in detected_faces:
                        detection = FaceDetection(
                            photo_id=photo_uuid,
                            bbox={"x1": face.bbox[0], "y1": face.bbox[1],
                                  "x2": face.bbox[2], "y2": face.bbox[3]},
                            detection_confidence=face.confidence,
                            quality_score=face.quality_score,
                            embedding=embedding_to_bytes(face.embedding),
                            is_low_quality=face.is_low_quality,
                        )
                        db.add(detection)
                        await db.flush()
                        
                        if not face.is_low_quality:
                            # Upload face crop to R2
                            face_key = await upload_face_crop(
                                face.face_crop_bytes,
                                tenant_id,
                                event_id,
                                detection.id
                            )
                            detection.face_key = face_key
                            await db.flush()

                            cluster_id = await assign_to_cluster(
                                detection.id, face.embedding, event_id, db
                            )
                            if cluster_id is None:
                                await create_new_cluster(
                                    detection.id, face.embedding, event_id, db
                                )

                    photo_obj.status = PhotoStatus.done
                    await db.commit()

                except Exception as e:
                    await db.rollback()
                    try:
                        res = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                        photo_obj = res.scalar_one_or_none()
                        if photo_obj:
                            photo_obj.status = PhotoStatus.failed
                            photo_obj.error_message = str(e)[:500]
                            await db.commit()
                    except Exception:
                        pass


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


# ───────────────────────────────────────────────────────────────────────────────
# Retry failed photos
# ───────────────────────────────────────────────────────────────────────────────
async def _reprocess_failed_background(photo_ids: List[str], event: Event):
    """Re-download originals from R2 and re-run face detection for failed photos."""
    async with async_session_maker() as db:
        for pid in photo_ids:
            photo_uuid = uuid.UUID(pid)
            try:
                res = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                photo = res.scalar_one_or_none()
                if not photo or not photo.original_key:
                    continue

                # Mark as processing
                photo.status = PhotoStatus.processing
                photo.error_message = None
                await db.commit()

                # Download original from R2
                url = generate_presigned_url(photo.original_key, expires_in=300)
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        raise ValueError(f"Failed to download original from R2: {resp.status_code}")
                    image_bytes = resp.content

                fname = photo.filename or ''

                # Run face detection — image_bytes freed immediately after
                detected_faces = await run_in_threadpool(detect_and_embed, image_bytes, fname)
                del image_bytes   # Free 50-100 MB immediately
                gc.collect()

                async with async_session_maker() as db2:
                    # Remove any old (broken) face detections for this photo
                    old_dets = await db2.execute(
                        select(FaceDetection).where(FaceDetection.photo_id == photo_uuid)
                    )
                    for det in old_dets.scalars().all():
                        await db2.delete(det)
                    await db2.flush()

                    for face in detected_faces:
                        detection = FaceDetection(
                            photo_id=photo_uuid,
                            bbox={"x1": face.bbox[0], "y1": face.bbox[1],
                                  "x2": face.bbox[2], "y2": face.bbox[3]},
                            detection_confidence=face.confidence,
                            quality_score=face.quality_score,
                            embedding=embedding_to_bytes(face.embedding),
                            is_low_quality=face.is_low_quality,
                        )
                        db2.add(detection)
                        await db2.flush()

                        if not face.is_low_quality:
                            face_key = await upload_face_crop(
                                face.face_crop_bytes,
                                event.tenant_id,
                                event.id,
                                detection.id,
                            )
                            detection.face_key = face_key
                            await db2.flush()

                            cluster_id = await assign_to_cluster(
                                detection.id, face.embedding, event.id, db2
                            )
                            if cluster_id is None:
                                await create_new_cluster(
                                    detection.id, face.embedding, event.id, db2
                                )

                    # Mark done
                    photo_res = await db2.execute(select(Photo).where(Photo.id == photo_uuid))
                    photo_obj = photo_res.scalar_one_or_none()
                    if photo_obj:
                        photo_obj.status = PhotoStatus.done
                        photo_obj.error_message = None
                    await db2.commit()

                # Small pause between photos so GC can reclaim memory
                await asyncio.sleep(0.5)

            except Exception as e:

                try:
                    async with async_session_maker() as dberr:
                        photo_res = await dberr.execute(select(Photo).where(Photo.id == photo_uuid))
                        photo_obj = photo_res.scalar_one_or_none()
                        if photo_obj:
                            photo_obj.status = PhotoStatus.failed
                            photo_obj.error_message = str(e)[:500]
                        await dberr.commit()
                except Exception:
                    pass


@router.post("/events/{event_id}/retry-failed", status_code=202)
async def retry_failed_photos(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-process all failed (or stuck) photos for an event.
    Downloads originals from R2 and reruns face detection — no re-upload needed.
    """
    event = await _get_event_or_404(event_id, current_user.tenant_id, db)

    result = await db.execute(
        select(Photo).where(
            Photo.event_id == event_id,
            Photo.status.in_([PhotoStatus.failed, PhotoStatus.queued, PhotoStatus.processing])
        )
    )
    failed_photos = result.scalars().all()

    if not failed_photos:
        return {"retrying": 0, "message": "No failed photos found."}

    photo_ids = [str(p.id) for p in failed_photos]

    # Reset status to queued so UI shows them as pending
    for p in failed_photos:
        p.status = PhotoStatus.queued
        p.error_message = None
    await db.commit()

    asyncio.create_task(_reprocess_failed_background(photo_ids=photo_ids, event=event))

    return {
        "retrying": len(photo_ids),
        "message": f"Retrying {len(photo_ids)} photo(s) in the background."
    }


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
