"""
Photos router — bulk upload, listing with status, retry, and signed URL serving.
"""
import uuid
import hashlib
import asyncio
import os
import io
import gc
import time
from typing import Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, BackgroundTasks, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, exists, func, select, update

from ..database import get_db, async_session_maker
from ..models import (
    Photo, PhotoStatus, Event, Subscription, User, AuditLog, FaceDetection,
    FaceCluster, BatchItemStatus, BatchSource, BatchStatus, ProcessingBatch,
    ProcessingBatchItem, PhotoIngestionStage, PhotoProcessingStage,
)
from ..auth import require_organizer, require_attendee, get_current_user
from ..services.storage import (
    upload_original, upload_thumbnail, upload_face_crop,
    generate_presigned_url, delete_objects, stream_object
)
from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes
from ..services.clustering import assign_to_cluster, create_new_cluster
from ..schemas import (
    PhotoResponse, PhotoListResponse, MessageResponse,
    ProcessingBatchCreateRequest, ProcessingBatchResponse,
)
from ..services.batch_tracking import (
    BatchStateError, append_item, append_photo_items, create_batch, mark_item_started,
    mark_item_terminal, seal_batch, TERMINAL_ITEM_STATUSES,
)
from ..services.telemetry import (
    detect_runtime_processor, record_completion_sync, set_local_processor,
)
from ..services.event_lock import lock_event_face_mutation
from ..services.photo_stages import (
    INGESTION_STAGE_VALUES,
    PHOTO_STAGE_FILTER_VALUES,
    combined_photo_stage,
    drive_stage_for_photo,
    r2_stage_for_photo,
    sanitize_stage_error,
)
from ..config import get_settings

settings = get_settings()
router = APIRouter(prefix="/photos", tags=["Photos"])


def _pipeline_version() -> str:
    try:
        from ..services.ml_pipeline import get_pipeline_version

        return str(get_pipeline_version())[:100]
    except (ImportError, AttributeError):
        return f"insightface:{settings.INSIGHTFACE_MODEL}:v1"[:100]


async def _schedule_recluster_if_idle(event_id: uuid.UUID) -> None:
    # Finalization is claimed durably in PostgreSQL before it is published.
    # The recovery loop retries a broker outage without starting heavyweight
    # clustering inside the web process or enqueueing duplicate event jobs.
    from ..services.dispatcher import dispatch_ready_finalizers

    try:
        await dispatch_ready_finalizers()
    except Exception as exc:
        print(f"Could not schedule event recluster for {event_id}: {exc}")


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
                await lock_event_face_mutation(event_id, db)

                pipeline_version = _pipeline_version()
                for face_index, face in enumerate(detected_faces):
                    detection = FaceDetection(
                        photo_id=photo_uuid,
                        bbox={"x1": face.bbox[0], "y1": face.bbox[1],
                              "x2": face.bbox[2], "y2": face.bbox[3]},
                        detection_confidence=face.confidence,
                        quality_score=face.quality_score,
                        embedding=embedding_to_bytes(face.embedding),
                        pipeline_version=pipeline_version,
                        face_index=face_index,
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


async def _dispatch_batch_items(
    *,
    items: List[tuple[str, str]],
    event: Event,
    background_tasks: BackgroundTasks,
) -> None:
    """Publish durable items; the recovery loop retries any broker outage."""
    if not items:
        return
    del event, background_tasks  # Scope is derived from the durable DB rows.
    from ..services.dispatcher import dispatch_item_ids

    await dispatch_item_ids(item_id for _photo_id, item_id in items)


@router.post(
    "/events/{event_id}/batches",
    response_model=ProcessingBatchResponse,
    status_code=201,
)
async def create_upload_batch(
    event_id: uuid.UUID,
    body: Optional[ProcessingBatchCreateRequest] = None,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    event = await _get_event_or_404(event_id, current_user.tenant_id, db)
    source = body.source if body else BatchSource.upload
    if source in (BatchSource.drive_import, BatchSource.reprocess):
        raise HTTPException(
            status_code=422,
            detail=f"{source.value} batches are created by their dedicated endpoint",
        )
    batch = await create_batch(
        db,
        tenant_id=event.tenant_id,
        event_id=event.id,
        created_by_user_id=current_user.id,
        source=source,
        expected_images=body.expected_images if body else None,
    )
    return ProcessingBatchResponse.model_validate(batch)


@router.post(
    "/batches/{batch_id}/seal",
    response_model=ProcessingBatchResponse,
)
async def seal_upload_batch(
    batch_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    try:
        batch = await seal_batch(
            db,
            batch_id=batch_id,
            tenant_id=current_user.tenant_id,
        )
    except BatchStateError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    event = await _get_event_or_404(batch.event_id, current_user.tenant_id, db)
    dispatch_rows = (await db.execute(
        select(ProcessingBatchItem.photo_id, ProcessingBatchItem.id).where(
            ProcessingBatchItem.batch_id == batch.id,
            ProcessingBatchItem.status == BatchItemStatus.queued,
            ProcessingBatchItem.photo_id.is_not(None),
        )
    )).all()
    await db.commit()
    # Reload server-managed timestamps before response serialization.
    await db.refresh(batch)
    await _dispatch_batch_items(
        items=[(str(photo_id), str(item_id)) for photo_id, item_id in dispatch_rows],
        event=event,
        background_tasks=background_tasks,
    )
    if batch.status == BatchStatus.finalizing:
        await _schedule_recluster_if_idle(event.id)
    return ProcessingBatchResponse.model_validate(batch)

@router.post("/events/{event_id}/upload", status_code=202)
async def upload_photos(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    batch_id: Optional[uuid.UUID] = Form(None),
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
    Face detection runs via Celery if available, falling back to BackgroundTasks.
    """
    import os as _os
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum {MAX_FILES_PER_REQUEST} files per request. "
                   f"Split your upload into smaller batches.",
        )

    event = await _get_event_or_404(event_id, current_user.tenant_id, db)
    explicit_batch = batch_id is not None
    if explicit_batch:
        batch_result = await db.execute(
            select(ProcessingBatch).where(
                ProcessingBatch.id == batch_id,
                ProcessingBatch.tenant_id == current_user.tenant_id,
                ProcessingBatch.event_id == event_id,
            )
        )
        processing_batch = batch_result.scalar_one_or_none()
        if not processing_batch:
            raise HTTPException(status_code=404, detail="Processing batch not found")
        if processing_batch.status != BatchStatus.receiving:
            raise HTTPException(status_code=409, detail="Processing batch is already sealed")
    else:
        processing_batch = await create_batch(
            db,
            tenant_id=current_user.tenant_id,
            event_id=event_id,
            created_by_user_id=current_user.id,
            source=BatchSource.upload,
        )

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
    created_items: List[tuple[str, str]] = []
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
                skipped_item = await append_item(
                    db,
                    batch_id=processing_batch.id,
                    photo_id=None,
                    filename=fname or None,
                )
                await mark_item_terminal(
                    db,
                    item_id=skipped_item.id,
                    status=BatchItemStatus.skipped,
                    error_message="Unsupported image format",
                )
                continue
    
            data = await file.read()
    
            if len(data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
                skipped_fmt.append(fname)
                skipped_item = await append_item(
                    db,
                    batch_id=processing_batch.id,
                    photo_id=None,
                    filename=fname or None,
                )
                await mark_item_terminal(
                    db,
                    item_id=skipped_item.id,
                    status=BatchItemStatus.skipped,
                    error_message="Image exceeds the upload size limit",
                )
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
                skipped_item = await append_item(
                    db,
                    batch_id=processing_batch.id,
                    photo_id=None,
                    filename=fname or None,
                    source_ref=content_hash,
                )
                await mark_item_terminal(
                    db,
                    item_id=skipped_item.id,
                    status=BatchItemStatus.skipped,
                    error_message="Duplicate photo",
                )
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
            file_size = len(data)
            total_bytes += file_size
            del data
            gc.collect()
    
            # ── Save DB row ───────────────────────────────────────────────────────
            photo = Photo(
                id=photo_id,
                event_id=event_id,
                tenant_id=current_user.tenant_id,
                original_key=original_key,
                thumbnail_key=thumbnail_key,
                original_size_bytes=file_size,
                filename=fname or f"{photo_id}{ext}",
                mime_type=mime,
                content_hash=content_hash,
                status=PhotoStatus.queued,
                ingestion_stage=PhotoIngestionStage.r2_uploaded,
                processing_stage=PhotoProcessingStage.queued,
                stage_error=None,
            )
            db.add(photo)
            await db.flush()   # get photo.id assigned before Celery dispatch

            item = await append_item(
                db,
                batch_id=processing_batch.id,
                photo_id=photo.id,
                filename=photo.filename,
            )
    
            # ── Dispatch to Celery ─────────
            created_ids.append(str(photo_id))
            created_items.append((str(photo_id), str(item.id)))

    except Exception as e:
        import traceback
        err_msg = str(e)
        tb = traceback.format_exc()
        print(tb)
        raise HTTPException(status_code=500, detail=f"Upload failed: {err_msg}")

    if sub and total_bytes:
        sub.current_storage_bytes = (sub.current_storage_bytes or 0) + total_bytes

    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="photo.upload",
        resource_type="event",
        resource_id=str(event_id),
        payload={"count": len(created_ids), "batch_id": str(processing_batch.id)},
    ))

    if not explicit_batch:
        processing_batch = await seal_batch(
            db,
            batch_id=processing_batch.id,
            tenant_id=current_user.tenant_id,
            event_id=event_id,
        )
    elif processing_batch.expected_images is not None:
        # Auto-seal a fully-accounted batch server-side. The explicit /seal
        # request remains an idempotent recovery path for interrupted uploads.
        await db.refresh(processing_batch)
        if processing_batch.total_images >= processing_batch.expected_images:
            processing_batch = await seal_batch(
                db,
                batch_id=processing_batch.id,
                tenant_id=current_user.tenant_id,
                event_id=event_id,
            )

    await db.commit()

    # Explicit batches remain appendable until seal, but every committed page
    # is dispatched immediately.  Seal re-dispatches any queued rows as an
    # idempotent recovery path if a broker call or client page-close was lost.
    await _dispatch_batch_items(
        items=created_items,
        event=event,
        background_tasks=background_tasks,
    )
    if processing_batch.status == BatchStatus.finalizing:
        await _schedule_recluster_if_idle(event.id)

    return {
        "accepted":        len(created_ids),
        "skipped_format":  len(skipped_fmt),
        "duplicates":      len(duplicates),
        "duplicate_names": duplicates,
        "photo_ids":       created_ids,
        "batch_id":        str(processing_batch.id),
        "batch_status":    processing_batch.status.value,
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
    background_tasks: BackgroundTasks,
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

    event = await _get_event_or_404(event_id, current_user.tenant_id, db)

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
    await lock_event_face_mutation(event_id, db)
    processing_batch = await create_batch(
        db,
        tenant_id=current_user.tenant_id,
        event_id=event_id,
        created_by_user_id=current_user.id,
        source=BatchSource.drive_import,
    )
    queued_items = []   # [(photo_id, batch_item_id, file_id, filename, mime_type)]
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
            ingestion_stage=PhotoIngestionStage.drive_queued,
            processing_stage=PhotoProcessingStage.not_started,
            stage_error=None,
        )
        db.add(photo)
        await db.flush()
        item = await append_item(
            db,
            batch_id=processing_batch.id,
            photo_id=photo.id,
            filename=f["name"],
            source_ref=f["id"],
        )
        queued_items.append((
            str(photo_id), str(item.id), f["id"], f["name"], f["mimeType"]
        ))

    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="photo.drive_import",
        resource_type="event",
        resource_id=str(event_id),
        payload={
            "folder_id": folder_id,
            "count": len(queued_items),
            "batch_id": str(processing_batch.id),
        },
    ))
    processing_batch = await seal_batch(
        db,
        batch_id=processing_batch.id,
        tenant_id=current_user.tenant_id,
        event_id=event_id,
    )
    await db.commit()

    # Drive download itself is now a durable worker stage. A web restart after
    # this commit is recovered from the batch-item outbox.
    await _dispatch_batch_items(
        items=[(photo_id, item_id) for photo_id, item_id, *_rest in queued_items],
        event=event,
        background_tasks=background_tasks,
    )

    return {
        "queued": len(queued_items),
        "message": f"Importing {len(queued_items)} photos from Google Drive in the background.",
        "files": [f["name"] for f in drive_files[:10]],  # preview of first 10
        "batch_id": str(processing_batch.id),
        "batch_status": processing_batch.status.value,
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
        for photo_id_str, batch_item_id_str, file_id, filename, mime_type in queued_items:
            photo_uuid = uuid.UUID(photo_id_str)
            batch_item_uuid = uuid.UUID(batch_item_id_str)

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
                        await mark_item_terminal(
                            db,
                            item_id=batch_item_uuid,
                            status=BatchItemStatus.skipped,
                            error_message="Duplicate image",
                        )
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
                    photo_obj.status = PhotoStatus.queued
                    await db.commit()

                    # 5. Face detection + clustering
                    # Dispatch to Celery instead of processing locally
                    from ..workers.tasks import process_photo
                    await run_in_threadpool(
                        process_photo.apply_async,
                        args=[str(photo_uuid), str(tenant_id), str(event_id)],
                        kwargs={"batch_item_id": str(batch_item_uuid)},
                    )
                except Exception as e:
                    await db.rollback()
                    try:
                        res = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                        photo_obj = res.scalar_one_or_none()
                        if photo_obj:
                            photo_obj.status = PhotoStatus.failed
                            photo_obj.error_message = str(e)[:500]
                        transition = await mark_item_terminal(
                            db,
                            item_id=batch_item_uuid,
                            status=BatchItemStatus.failed,
                            error_message=str(e),
                        )
                        await db.commit()
                        if transition.applied:
                            record_completion_sync(
                                batch_id=transition.batch_id,
                                tenant_id=transition.tenant_id,
                                faces_detected=0,
                            )
                    except Exception:
                        pass


# ─────────────────────────────────────────────────────────────────────────────
# List photos
# ─────────────────────────────────────────────────────────────────────────────
    await _schedule_recluster_if_idle(event_id)


@router.get("/events/{event_id}", response_model=PhotoListResponse)
async def list_event_photos(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status_filter: Literal["all", "queued", "processing", "done", "failed"] = "all",
    stage_filter: str = Query(default="all", max_length=40),
    q: Optional[str] = Query(default=None, max_length=120),
):
    await _get_event_or_404(event_id, current_user.tenant_id, db)

    filters = [Photo.event_id == event_id]
    if status_filter != "all":
        filters.append(Photo.status == PhotoStatus(status_filter))
    if stage_filter != "all":
        if stage_filter not in PHOTO_STAGE_FILTER_VALUES:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Invalid photo stage filter",
                    "allowed": ["all", *PHOTO_STAGE_FILTER_VALUES],
                },
            )
        if stage_filter in INGESTION_STAGE_VALUES:
            filters.append(
                Photo.ingestion_stage == PhotoIngestionStage(stage_filter)
            )
        else:
            processing_filter_map = {
                "processing_not_started": PhotoProcessingStage.not_started,
                "processing_queued": PhotoProcessingStage.queued,
                "processing": PhotoProcessingStage.processing,
                "processed": PhotoProcessingStage.processed,
                "processing_failed": PhotoProcessingStage.failed,
                "cancelled": PhotoProcessingStage.cancelled,
            }
            filters.append(
                Photo.processing_stage == processing_filter_map[stage_filter]
            )
    if q and q.strip():
        filters.append(Photo.filename.ilike(f"%{q.strip()}%"))

    total = (await db.execute(
        select(func.count(Photo.id)).where(*filters)
    )).scalar()

    face_counts = (
        select(FaceDetection.photo_id, func.count(FaceDetection.id).label("face_count"))
        .group_by(FaceDetection.photo_id)
        .subquery()
    )
    is_drive_import = exists(
        select(ProcessingBatchItem.id)
        .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
        .where(
            ProcessingBatchItem.photo_id == Photo.id,
            ProcessingBatch.source == BatchSource.drive_import,
        )
    ).label("is_drive_import")
    result = await db.execute(
        select(
            Photo,
            func.coalesce(face_counts.c.face_count, 0),
            is_drive_import,
        )
        .outerjoin(face_counts, face_counts.c.photo_id == Photo.id)
        .where(*filters)
        .order_by(Photo.uploaded_at.desc())
        .offset(skip).limit(limit)
    )
    rows = result.all()

    out = []
    for p, face_count, is_drive in rows:
        thumb_url = generate_presigned_url(p.thumbnail_key, expires_in=3600) if p.thumbnail_key else None
        preview_url = generate_presigned_url(p.original_key, expires_in=1800) if p.original_key else thumb_url
        out.append(PhotoResponse(
            id=p.id,
            filename=p.filename,
            status=p.status,
            error_message=p.error_message,
            ingestion_stage=p.ingestion_stage,
            processing_stage=p.processing_stage,
            stage=combined_photo_stage(
                p.ingestion_stage,
                p.processing_stage,
            ),
            drive_stage=drive_stage_for_photo(
                p.ingestion_stage,
                is_drive_import=bool(is_drive),
            ),
            r2_stage=r2_stage_for_photo(p.ingestion_stage),
            stage_error=p.stage_error,
            uploaded_at=p.uploaded_at,
            thumbnail_url=thumb_url,
            preview_url=preview_url,
            original_size_bytes=p.original_size_bytes or 0,
            face_count=int(face_count or 0),
        ))

    return PhotoListResponse(photos=out, total=total)


async def _get_photo_for_organizer(
    photo_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Photo:
    photo = (await db.execute(
        select(Photo).where(
            Photo.id == photo_id,
            Photo.tenant_id == current_user.tenant_id,
        )
    )).scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


@router.post("/{photo_id}/process-now", status_code=202)
async def process_photo_now(
    photo_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    photo = await _get_photo_for_organizer(photo_id, current_user, db)
    if not photo.original_key:
        raise HTTPException(
            status_code=409,
            detail="This photo does not have a stored original yet. Re-import or upload it again.",
        )

    await lock_event_face_mutation(photo.event_id, db)
    active_rows = (await db.execute(
        select(ProcessingBatchItem, ProcessingBatch)
        .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
        .where(
            ProcessingBatchItem.photo_id == photo.id,
            ProcessingBatchItem.status.notin_(TERMINAL_ITEM_STATUSES),
            ProcessingBatch.status.in_([
                BatchStatus.receiving,
                BatchStatus.queued,
                BatchStatus.running,
                BatchStatus.finalizing,
            ]),
        )
        .order_by(ProcessingBatchItem.queued_at.desc())
    )).all()

    dispatch_items: List[tuple[str, str]] = []
    if active_rows:
        for item, _batch in active_rows:
            if item.status == BatchItemStatus.queued:
                dispatch_items.append((str(photo.id), str(item.id)))
        if photo.status != PhotoStatus.processing:
            photo.status = PhotoStatus.queued
            photo.error_message = None
            photo.processing_stage = PhotoProcessingStage.queued
            photo.stage_error = None
        message = (
            "Photo is already processing."
            if not dispatch_items and photo.status == PhotoStatus.processing
            else "Queued photo was dispatched for processing."
        )
    else:
        photo.status = PhotoStatus.queued
        photo.error_message = None
        photo.ingestion_stage = PhotoIngestionStage.r2_uploaded
        photo.processing_stage = PhotoProcessingStage.queued
        photo.stage_error = None
        processing_batch = await create_batch(
            db,
            tenant_id=photo.tenant_id,
            event_id=photo.event_id,
            created_by_user_id=current_user.id,
            source=BatchSource.retry,
            expected_images=1,
        )
        item = await append_item(
            db,
            batch_id=processing_batch.id,
            photo_id=photo.id,
            filename=photo.filename,
        )
        processing_batch = await seal_batch(
            db,
            batch_id=processing_batch.id,
            tenant_id=photo.tenant_id,
            event_id=photo.event_id,
        )
        dispatch_items.append((str(photo.id), str(item.id)))
        message = "Photo was queued for processing."

    await db.commit()
    if dispatch_items:
        await _dispatch_batch_items(
            items=dispatch_items,
            event=None,
            background_tasks=background_tasks,
        )
    return {"message": message, "dispatched": len(dispatch_items)}


@router.post("/{photo_id}/cancel", response_model=MessageResponse)
async def cancel_photo_processing(
    photo_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    photo = await _get_photo_for_organizer(photo_id, current_user, db)
    if photo.status not in (PhotoStatus.queued, PhotoStatus.processing):
        return MessageResponse(message="Photo is not queued or processing.")

    await lock_event_face_mutation(photo.event_id, db)
    active_items = (await db.execute(
        select(ProcessingBatchItem).where(
            ProcessingBatchItem.photo_id == photo.id,
            ProcessingBatchItem.status.notin_(TERMINAL_ITEM_STATUSES),
        )
    )).scalars().all()
    batch_finalizing = False
    for item in active_items:
        transition = await mark_item_terminal(
            db,
            item_id=item.id,
            status=BatchItemStatus.cancelled,
            error_message="Cancelled by organizer",
        )
        batch_finalizing = batch_finalizing or transition.batch_finalizing
    photo.status = PhotoStatus.failed
    photo.error_message = "Cancelled by organizer"
    photo.processing_stage = PhotoProcessingStage.cancelled
    photo.stage_error = "Cancelled by organizer"
    await db.commit()
    if batch_finalizing:
        await _schedule_recluster_if_idle(photo.event_id)
    return MessageResponse(message="Photo processing cancelled.")


@router.delete("/{photo_id}", response_model=MessageResponse)
async def remove_photo(
    photo_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    photo = await _get_photo_for_organizer(photo_id, current_user, db)
    event_id = photo.event_id
    await lock_event_face_mutation(photo.event_id, db)

    from ..services.storage_cleanup import collect_photo_assets

    asset_keys, deleted_bytes = await collect_photo_assets(db, [photo])
    active_items = (await db.execute(
        select(ProcessingBatchItem).where(
            ProcessingBatchItem.photo_id == photo.id,
            ProcessingBatchItem.status.notin_(TERMINAL_ITEM_STATUSES),
        )
    )).scalars().all()
    batch_finalizing = False
    for item in active_items:
        transition = await mark_item_terminal(
            db,
            item_id=item.id,
            status=BatchItemStatus.cancelled,
            error_message="Photo removed by organizer",
        )
        batch_finalizing = batch_finalizing or transition.batch_finalizing

    if deleted_bytes:
        sub_result = await db.execute(
            select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
        )
        sub = sub_result.scalar_one_or_none()
        if sub:
            sub.current_storage_bytes = max(
                0,
                (sub.current_storage_bytes or 0) - deleted_bytes,
            )
    await db.delete(photo)
    await db.commit()
    try:
        await run_in_threadpool(delete_objects, asset_keys)
    except Exception as cleanup_error:
        print(f"Deferred storage cleanup failed: {cleanup_error}")
    if batch_finalizing:
        await _schedule_recluster_if_idle(event_id)
    return MessageResponse(message="Photo removed.")


# ─────────────────────────────────────────────────────────────────────────────
# Delete photos (bulk clear)
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/events/{event_id}/clear")
async def clear_event_photos(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
    status_filter: Literal["all", "failed", "queued"] = "all",
):
    """
    Delete selected event photos and their R2 assets.

    Database state commits first; object cleanup is fail-soft so a storage
    outage cannot leave live photo rows pointing at deleted originals.
    """
    await _get_event_or_404(event_id, current_user.tenant_id, db)
    await lock_event_face_mutation(event_id, db)

    query = select(Photo).where(Photo.event_id == event_id)
    if status_filter != "all":
        query = query.where(Photo.status == status_filter)

    from ..services.storage_cleanup import collect_photo_assets

    result = await db.execute(query)
    photos = result.scalars().all()
    asset_keys, deleted_bytes = await collect_photo_assets(db, photos)

    photo_ids = [photo.id for photo in photos]
    if photo_ids:
        active_items = (await db.execute(
            select(ProcessingBatchItem).where(
                ProcessingBatchItem.photo_id.in_(photo_ids),
                ProcessingBatchItem.status.notin_(TERMINAL_ITEM_STATUSES),
            )
        )).scalars().all()
        for item in active_items:
            await mark_item_terminal(
                db,
                item_id=item.id,
                status=BatchItemStatus.cancelled,
                error_message="Photo removed by organizer",
            )

    for p in photos:
        await db.delete(p)

    if deleted_bytes:
        sub_result = await db.execute(
            select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
        )
        sub = sub_result.scalar_one_or_none()
        if sub:
            sub.current_storage_bytes = max(
                0,
                (sub.current_storage_bytes or 0) - deleted_bytes,
            )
    
    # Also delete face clusters if we are clearing all photos
    if status_filter == "all":
        from ..models import FaceCluster
        clusters_res = await db.execute(select(FaceCluster).where(FaceCluster.event_id == event_id))
        for c in clusters_res.scalars().all():
            await db.delete(c)

    await db.commit()
    # Database deletion is authoritative. Storage cleanup happens only after a
    # successful commit, so a DB failure can never leave live rows with missing
    # originals. Failures here can leak objects but cannot lose referenced data.
    for offset in range(0, len(asset_keys), 1000):
        try:
            await run_in_threadpool(delete_objects, asset_keys[offset:offset + 1000])
        except Exception as cleanup_error:
            print(f"Deferred storage cleanup failed: {cleanup_error}")
    return MessageResponse(message=f"Deleted {len(photos)} photos.")


# ───────────────────────────────────────────────────────────────────────────────
# Retry failed photos
# ───────────────────────────────────────────────────────────────────────────────
@router.post("/events/{event_id}/reprocess-faces", status_code=202)
async def reprocess_event_faces(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Re-embed every original with the current, pinned face pipeline.

    This is intentionally explicit: legacy and current embeddings are never
    compared merely because both happen to contain 512 floats.
    """
    event = await _get_event_or_404(event_id, current_user.tenant_id, db)
    await lock_event_face_mutation(event_id, db)
    photos = (await db.execute(
        select(Photo).where(Photo.event_id == event_id).order_by(Photo.uploaded_at, Photo.id)
    )).scalars().all()
    if not photos:
        return {"reprocessing": 0, "message": "This event has no photos."}

    active_count = (await db.execute(
        select(func.count(Photo.id)).where(
            Photo.event_id == event_id,
            Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
        )
    )).scalar() or 0
    if active_count:
        raise HTTPException(
            status_code=409,
            detail="Wait for current photo processing to finish before rebuilding face groups.",
        )

    face_keys = list((await db.execute(
        select(FaceDetection.face_key)
        .join(Photo, Photo.id == FaceDetection.photo_id)
        .where(Photo.event_id == event_id, FaceDetection.face_key.is_not(None))
    )).scalars().all())

    processing_batch = await create_batch(
        db,
        tenant_id=event.tenant_id,
        event_id=event.id,
        created_by_user_id=current_user.id,
        source=BatchSource.reprocess,
        expected_images=len(photos),
    )
    items = await append_photo_items(db, batch_id=processing_batch.id, photos=photos)

    photo_ids_query = select(Photo.id).where(Photo.event_id == event_id)
    await db.execute(
        delete(FaceDetection).where(FaceDetection.photo_id.in_(photo_ids_query))
    )
    await db.execute(delete(FaceCluster).where(FaceCluster.event_id == event_id))
    await db.execute(
        update(Photo)
        .where(Photo.event_id == event_id)
        .values(
            status=PhotoStatus.queued,
            error_message=None,
            processing_stage=PhotoProcessingStage.queued,
            stage_error=None,
        )
    )
    processing_batch = await seal_batch(
        db,
        batch_id=processing_batch.id,
        tenant_id=event.tenant_id,
        event_id=event.id,
    )
    db.add(AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="faces.reprocess_all",
        resource_type="event",
        resource_id=str(event_id),
        payload={"photo_count": len(photos), "batch_id": str(processing_batch.id)},
    ))
    await db.commit()

    dispatch_items = [(str(item.photo_id), str(item.id)) for item in items if item.photo_id]
    await _dispatch_batch_items(
        items=dispatch_items,
        event=event,
        background_tasks=background_tasks,
    )
    for offset in range(0, len(face_keys), 1000):
        background_tasks.add_task(delete_objects, face_keys[offset:offset + 1000])

    return {
        "reprocessing": len(dispatch_items),
        "message": f"Reprocessing {len(dispatch_items)} photo(s) with the current face model.",
        "batch_id": str(processing_batch.id),
        "batch_status": processing_batch.status.value,
    }


async def _reprocess_failed_background(
    photo_ids: List[str],
    event: Event,
    batch_item_ids: Optional[Dict[str, str]] = None,
):
    """Re-download originals from R2 and re-run face detection for failed photos."""
    batch_item_ids = batch_item_ids or {}
    for pid in photo_ids:
        async with async_session_maker() as db:
            photo_uuid = uuid.UUID(pid)
            item_id = uuid.UUID(batch_item_ids[pid]) if pid in batch_item_ids else None
            started = time.perf_counter()
            try:
                res = await db.execute(select(Photo).where(Photo.id == photo_uuid))
                photo = res.scalar_one_or_none()
                if not photo or not photo.original_key:
                    raise ValueError("Photo or original object is unavailable")

                if item_id is not None:
                    claimed = await mark_item_started(
                        db,
                        item_id=item_id,
                        processor=detect_runtime_processor(),
                    )
                    if not claimed:
                        await db.rollback()
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
                processor = detect_runtime_processor()
                set_local_processor(processor)
                del image_bytes   # Free 50-100 MB immediately
                gc.collect()

                async with async_session_maker() as db2:
                    await lock_event_face_mutation(event.id, db2)
                    # Remove any old (broken) face detections for this photo
                    old_dets = await db2.execute(
                        select(FaceDetection).where(FaceDetection.photo_id == photo_uuid)
                    )
                    for det in old_dets.scalars().all():
                        await db2.delete(det)
                    await db2.flush()

                    pipeline_version = _pipeline_version()
                    for face_index, face in enumerate(detected_faces):
                        detection = FaceDetection(
                            photo_id=photo_uuid,
                            bbox={"x1": face.bbox[0], "y1": face.bbox[1],
                                  "x2": face.bbox[2], "y2": face.bbox[3]},
                            detection_confidence=face.confidence,
                            quality_score=face.quality_score,
                            embedding=embedding_to_bytes(face.embedding),
                            pipeline_version=pipeline_version,
                            face_index=face_index,
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
                    transition = None
                    if item_id is not None:
                        transition = await mark_item_terminal(
                            db2,
                            item_id=item_id,
                            status=BatchItemStatus.succeeded,
                            faces_detected=len(detected_faces),
                            processing_ms=int((time.perf_counter() - started) * 1000),
                            processor=processor,
                        )
                    await db2.commit()
                    if transition and transition.applied:
                        record_completion_sync(
                            batch_id=transition.batch_id,
                            tenant_id=transition.tenant_id,
                            faces_detected=len(detected_faces),
                        )

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
                        transition = None
                        if item_id is not None:
                            transition = await mark_item_terminal(
                                dberr,
                                item_id=item_id,
                                status=BatchItemStatus.failed,
                                processing_ms=int((time.perf_counter() - started) * 1000),
                                processor=detect_runtime_processor(),
                                error_message=str(e),
                            )
                        await dberr.commit()
                        if transition and transition.applied:
                            record_completion_sync(
                                batch_id=transition.batch_id,
                                tenant_id=transition.tenant_id,
                                faces_detected=0,
                            )
                except Exception:
                    pass

    await _schedule_recluster_if_idle(event.id)


@router.post("/events/{event_id}/retry-failed", status_code=202)
async def retry_failed_photos(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-process failed photos for an event.
    Downloads originals from R2 and reruns face detection — no re-upload needed.
    """
    event = await _get_event_or_404(event_id, current_user.tenant_id, db)
    await lock_event_face_mutation(event_id, db)

    result = await db.execute(
        select(Photo).where(
            Photo.event_id == event_id,
            Photo.status == PhotoStatus.failed,
        )
    )
    failed_photos = result.scalars().all()

    if not failed_photos:
        return {"retrying": 0, "message": "No failed photos found."}

    failed_ids = [photo.id for photo in failed_photos]
    drive_ref_rows = (await db.execute(
        select(ProcessingBatchItem.photo_id, ProcessingBatchItem.source_ref)
        .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
        .where(
            ProcessingBatchItem.photo_id.in_(failed_ids),
            ProcessingBatchItem.source_ref.is_not(None),
            ProcessingBatch.source == BatchSource.drive_import,
        )
        .order_by(ProcessingBatchItem.queued_at.desc())
    )).all()
    drive_refs: Dict[uuid.UUID, str] = {}
    for photo_id, source_ref in drive_ref_rows:
        if photo_id is not None and source_ref and photo_id not in drive_refs:
            drive_refs[photo_id] = source_ref

    stored_photos = [(photo, None) for photo in failed_photos if photo.original_key]
    drive_photos = [
        (photo, drive_refs[photo.id])
        for photo in failed_photos
        if not photo.original_key and photo.id in drive_refs
    ]
    unrecoverable = len(failed_photos) - len(stored_photos) - len(drive_photos)

    dispatch_items: List[tuple[str, str]] = []
    processing_batches: List[ProcessingBatch] = []
    for source, photos_with_refs in (
        (BatchSource.retry, stored_photos),
        (BatchSource.drive_import, drive_photos),
    ):
        if not photos_with_refs:
            continue
        processing_batch = await create_batch(
            db,
            tenant_id=event.tenant_id,
            event_id=event.id,
            created_by_user_id=current_user.id,
            source=source,
            expected_images=len(photos_with_refs),
        )
        for photo, source_ref in photos_with_refs:
            photo.status = PhotoStatus.queued
            photo.error_message = None
            photo.stage_error = None
            if source == BatchSource.drive_import:
                photo.ingestion_stage = PhotoIngestionStage.drive_queued
                photo.processing_stage = PhotoProcessingStage.not_started
            else:
                photo.ingestion_stage = PhotoIngestionStage.r2_uploaded
                photo.processing_stage = PhotoProcessingStage.queued
            item = await append_item(
                db,
                batch_id=processing_batch.id,
                photo_id=photo.id,
                filename=photo.filename,
                source_ref=source_ref,
            )
            dispatch_items.append((str(photo.id), str(item.id)))
        processing_batch = await seal_batch(
            db,
            batch_id=processing_batch.id,
            tenant_id=event.tenant_id,
            event_id=event.id,
        )
        processing_batches.append(processing_batch)
    await db.commit()

    if dispatch_items:
        await _dispatch_batch_items(
            items=dispatch_items,
            event=event,
            background_tasks=background_tasks,
        )

    retrying = len(dispatch_items)
    message = f"Retrying {retrying} photo(s) in the background."
    if unrecoverable:
        message += (
            f" {unrecoverable} Drive photo(s) no longer have a source reference; "
            "select them again in Drive to re-import."
        )
    return {
        "retrying": retrying,
        "message": message,
        "batch_id": str(processing_batches[0].id) if processing_batches else None,
        "batch_ids": [str(batch.id) for batch in processing_batches],
        "batch_status": processing_batches[0].status.value if processing_batches else None,
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


@router.get("/{photo_id}/faces")
async def get_photo_faces(
    photo_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    """Detected faces for one photo with person names for preview overlays.

    Bounding boxes are in original-image pixel coordinates, so the client can
    scale them against the preview image's natural dimensions.
    """
    photo = await _get_photo_for_organizer(photo_id, current_user, db)
    rows = (await db.execute(
        select(FaceDetection, FaceCluster.label)
        .outerjoin(FaceCluster, FaceCluster.id == FaceDetection.cluster_id)
        .where(FaceDetection.photo_id == photo.id)
        .order_by(FaceDetection.face_index, FaceDetection.created_at)
    )).all()

    faces = []
    for detection, cluster_label in rows:
        bbox = detection.bbox or {}
        faces.append({
            "id": str(detection.id),
            "bbox": {
                "x1": float(bbox.get("x1", 0)),
                "y1": float(bbox.get("y1", 0)),
                "x2": float(bbox.get("x2", 0)),
                "y2": float(bbox.get("y2", 0)),
            },
            "cluster_id": str(detection.cluster_id) if detection.cluster_id else None,
            "person_label": cluster_label,
            "confidence": float(detection.detection_confidence or 0),
            "is_low_quality": bool(detection.is_low_quality),
        })
    return {"photo_id": str(photo.id), "status": photo.status.value, "faces": faces}


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
