"""Celery tasks for idempotent, tenant-scoped photo processing."""
from __future__ import annotations

import asyncio
import time
import uuid

from celery import shared_task
from celery.utils.log import get_task_logger

# Ensure this process installs the configured app as Celery's default app.
from .celery_app import celery_app

logger = get_task_logger(__name__)
_worker_loop = None


class ProcessingLeaseBusy(RuntimeError):
    """A prior delivery still owns a non-expired durable item lease."""


def run_async(coro):
    """Run worker coroutines on one loop so pooled DB connections stay valid."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop.run_until_complete(coro)


def _pipeline_version() -> str:
    try:
        from ..services.ml_pipeline import get_pipeline_version

        return str(get_pipeline_version())[:100]
    except (ImportError, AttributeError):
        from ..config import get_settings

        return f"insightface:{get_settings().INSIGHTFACE_MODEL}:v1"[:100]


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    time_limit=900,
    soft_time_limit=840,
    name="app.workers.tasks.process_photo",
)
def process_photo(
    self,
    photo_id: str,
    tenant_id: str | None = None,
    event_id: str | None = None,
    batch_item_id: str | None = None,
):
    """Detect, embed, persist, and group one photo.

    The three original positional arguments remain supported for already queued
    jobs. New jobs also carry ``batch_item_id``; its guarded state transition is
    the idempotency key for retries and broker redelivery. Tenant/event scope is
    always derived from the database and legacy arguments are only validated.
    """
    from sqlalchemy import func as sa_func, select

    from ..database import AsyncSessionLocal
    from ..models import (
        BatchItemStatus,
        BatchSource,
        FaceDetection,
        Photo,
        PhotoStatus,
        ProcessingBatchItem,
    )
    from ..services.batch_tracking import (
        get_item_context,
        mark_item_retrying,
        mark_item_started,
        mark_item_terminal,
    )
    from ..services.clustering import assign_to_cluster, create_new_cluster
    from ..services.event_lock import lock_event_face_mutation
    from ..services.ml_pipeline import detect_and_embed, embedding_to_bytes
    from ..services.storage import stream_object, upload_face_crop
    from ..services.telemetry import (
        detect_runtime_processor,
        record_completion_sync,
        set_local_processor,
        start_resource_sampler,
    )

    # Covers solo/eventlet pools where prefork lifecycle signals are absent.
    start_resource_sampler("worker")

    photo_uuid = uuid.UUID(str(photo_id))
    item_uuid = uuid.UUID(str(batch_item_id)) if batch_item_id else None
    context: dict[str, object] = {
        "item_validated": False,
        "safe_to_mutate": False,
        "tenant_id": None,
        "event_id": None,
    }
    started_clock = time.perf_counter()

    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Photo).where(Photo.id == photo_uuid))
            photo = result.scalar_one_or_none()
            if not photo:
                logger.error("Photo %s not found", photo_id)
                if item_uuid is not None:
                    row = await get_item_context(db, item_id=item_uuid)
                    if row is not None:
                        item, batch, _missing_photo = row
                        context["item_validated"] = True
                        context["tenant_id"] = batch.tenant_id
                        context["event_id"] = batch.event_id
                        transition = await mark_item_terminal(
                            db,
                            item_id=item.id,
                            status=BatchItemStatus.cancelled,
                            error_message="Photo was removed before processing started",
                        )
                        await db.commit()
                        if transition.applied:
                            record_completion_sync(
                                batch_id=transition.batch_id,
                                tenant_id=transition.tenant_id,
                                faces_detected=0,
                                images=0,
                            )
                return

            # Old task arguments are not trusted as scope, but mismatches are a
            # hard failure rather than silently writing into another event.
            if tenant_id and photo.tenant_id != uuid.UUID(str(tenant_id)):
                raise ValueError("Photo tenant does not match queued task")
            if event_id and photo.event_id != uuid.UUID(str(event_id)):
                raise ValueError("Photo event does not match queued task")

            context["tenant_id"] = photo.tenant_id
            context["event_id"] = photo.event_id
            context["safe_to_mutate"] = item_uuid is None
            batch = None
            item = None
            explicit_rebuild = False
            legacy_lock_held = False
            if item_uuid is None:
                # Stale pre-batch photos may be adopted during a rolling
                # upgrade. Both paths take this event lock and recheck, so
                # exactly one owns the photo. Holding the transaction through
                # inference is deliberate and limited to queued v1 messages.
                await lock_event_face_mutation(photo.event_id, db)
                legacy_lock_held = True
                await db.refresh(photo)
                durable_item_id = (await db.execute(
                    select(ProcessingBatchItem.id)
                    .where(ProcessingBatchItem.photo_id == photo.id)
                    .limit(1)
                )).scalar_one_or_none()
                if durable_item_id is not None:
                    logger.info(
                        "Legacy delivery for photo %s yielded to durable item %s",
                        photo.id,
                        durable_item_id,
                    )
                    return
            if item_uuid is not None:
                row = await get_item_context(db, item_id=item_uuid)
                if row is None:
                    raise ValueError("Processing batch item not found")
                item, batch, item_photo = row
                if (
                    item.photo_id != photo.id
                    or item_photo is None
                    or batch.tenant_id != photo.tenant_id
                    or batch.event_id != photo.event_id
                ):
                    raise ValueError("Processing batch item scope mismatch")
                context["item_validated"] = True
                context["safe_to_mutate"] = True
                explicit_rebuild = batch.source in (
                    BatchSource.retry,
                    BatchSource.reprocess,
                )

                if item.status in (
                    BatchItemStatus.succeeded,
                    BatchItemStatus.failed,
                    BatchItemStatus.skipped,
                    BatchItemStatus.cancelled,
                ):
                    return

            # Legacy redeliveries have no item id, so Photo.done remains their
            # durable idempotency guard. A retry batch deliberately rebuilds.
            if photo.status == PhotoStatus.failed and item_uuid is None:
                return
            if photo.status == PhotoStatus.done and not explicit_rebuild:
                if item_uuid is not None:
                    face_count = (await db.execute(
                        select(sa_func.count(FaceDetection.id)).where(
                            FaceDetection.photo_id == photo.id
                        )
                    )).scalar() or 0
                    transition = await mark_item_terminal(
                        db,
                        item_id=item_uuid,
                        status=BatchItemStatus.succeeded,
                        faces_detected=face_count,
                        processing_ms=0,
                        processor=detect_runtime_processor(),
                    )
                    await db.commit()
                    if transition.applied:
                        record_completion_sync(
                            batch_id=transition.batch_id,
                            tenant_id=transition.tenant_id,
                            faces_detected=face_count,
                        )
                return

            if item_uuid is not None:
                claimed = await mark_item_started(
                    db,
                    item_id=item_uuid,
                    processor=detect_runtime_processor(),
                    task_id=str(self.request.id or "") or None,
                )
                if not claimed:
                    await db.rollback()
                    status_row = await get_item_context(db, item_id=item_uuid)
                    if status_row is not None and status_row[0].status == BatchItemStatus.processing:
                        raise ProcessingLeaseBusy(
                            f"Batch item {item_uuid} is still owned by another delivery"
                        )
                    return

            photo.status = PhotoStatus.processing
            photo.error_message = None
            if item_uuid is not None:
                await db.commit()
            else:
                await db.flush()

            body = stream_object(photo.original_key)
            try:
                image_bytes = body.read()
            finally:
                try:
                    body.close()
                except Exception:
                    pass

            detected_faces = detect_and_embed(image_bytes, photo.filename or "")
            del image_bytes
            processor = detect_runtime_processor()
            set_local_processor(processor)
            pipeline_version = _pipeline_version()
            logger.info("Photo %s: %s faces detected on %s", photo_id, len(detected_faces), processor)

            # Final regrouping and organizer corrections participate in this
            # same event lock, preventing snapshot/delete/assignment races.
            if not legacy_lock_held:
                await lock_event_face_mutation(photo.event_id, db)

            # Explicit retry batches rebuild this photo's detections. Normal
            # task redelivery never reaches this branch after Photo.done.
            if explicit_rebuild:
                old_result = await db.execute(
                    select(FaceDetection).where(FaceDetection.photo_id == photo.id)
                )
                for old_detection in old_result.scalars().all():
                    await db.delete(old_detection)
                await db.flush()

            detections = []
            for face_index, face in enumerate(detected_faces):
                detection = FaceDetection(
                    photo_id=photo.id,
                    bbox={
                        "x1": face.bbox[0], "y1": face.bbox[1],
                        "x2": face.bbox[2], "y2": face.bbox[3],
                    },
                    detection_confidence=face.confidence,
                    quality_score=face.quality_score,
                    embedding=embedding_to_bytes(face.embedding),
                    pipeline_version=pipeline_version,
                    face_index=face_index,
                    is_low_quality=face.is_low_quality,
                )
                db.add(detection)
                await db.flush()
                detections.append(detection)

            upload_tasks = []
            for index, face in enumerate(detected_faces):
                if not face.is_low_quality:
                    upload_tasks.append(upload_face_crop(
                        face.face_crop_bytes,
                        photo.tenant_id,
                        photo.event_id,
                        detections[index].id,
                    ))
                else:
                    upload_tasks.append(asyncio.sleep(0, result=None))
            face_keys = await asyncio.gather(*upload_tasks)

            for index, face in enumerate(detected_faces):
                if face.is_low_quality:
                    continue
                detections[index].face_key = face_keys[index]
                await db.flush()
                cluster_id = await assign_to_cluster(
                    detections[index].id,
                    face.embedding,
                    photo.event_id,
                    db,
                )
                if cluster_id is None:
                    await create_new_cluster(
                        detections[index].id,
                        face.embedding,
                        photo.event_id,
                        db,
                    )

            photo.status = PhotoStatus.done
            transition = None
            if item_uuid is not None:
                transition = await mark_item_terminal(
                    db,
                    item_id=item_uuid,
                    status=BatchItemStatus.succeeded,
                    faces_detected=len(detected_faces),
                    processing_ms=int((time.perf_counter() - started_clock) * 1000),
                    processor=processor,
                )
            await db.commit()

            # Redis is emitted strictly after the exact DB transition commits.
            if transition and transition.applied:
                record_completion_sync(
                    batch_id=transition.batch_id,
                    tenant_id=transition.tenant_id,
                    faces_detected=len(detected_faces),
                )
            logger.info("Photo %s processed successfully", photo_id)

            # Everything below is post-commit notification. A broker outage
            # must never semantically undo an already successful DB result;
            # the durable dispatcher will also recover ready finalizers.
            try:
                pending = (await db.execute(
                    select(sa_func.count(Photo.id)).where(
                        Photo.event_id == photo.event_id,
                        Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
                    )
                )).scalar() or 0
                if pending == 0 and item_uuid is None:
                    logger.info("Event %s ready for final grouping", photo.event_id)
                    recluster_event_task.apply_async(
                        kwargs={"event_id": str(photo.event_id)},
                        countdown=1,
                        queue="face-v2",
                    )
            except Exception as scheduling_exc:
                logger.warning(
                    "Final grouping notification deferred for %s: %s",
                    photo.event_id,
                    scheduling_exc,
                )

    try:
        run_async(_run())
    except ProcessingLeaseBusy as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=20)
    except Exception as exc:
        exc_str = str(exc)
        is_deadlock = "DeadlockDetected" in exc_str or "deadlock" in exc_str.lower()
        is_retriable = is_deadlock or "connection" in exc_str.lower()

        if is_retriable and self.request.retries < self.max_retries:
            if item_uuid is not None and context["item_validated"]:
                async def _release_for_retry():
                    async with AsyncSessionLocal() as retry_db:
                        released = await mark_item_retrying(
                            retry_db,
                            item_id=item_uuid,
                            error_message=exc_str,
                        )
                        retry_photo = (await retry_db.execute(
                            select(Photo).where(Photo.id == photo_uuid)
                        )).scalar_one_or_none()
                        if retry_photo and released:
                            retry_photo.status = PhotoStatus.queued
                        await retry_db.commit()
                try:
                    run_async(_release_for_retry())
                except Exception:
                    pass
            countdown = 1 if is_deadlock else 15
            logger.warning("Photo %s retriable error: %s", photo_id, exc_str[:120])
            raise self.retry(exc=exc, countdown=countdown)

        logger.error("Photo %s permanently failed: %s", photo_id, exc_str[:200])
        transition_holder = {"value": None}
        legacy_ready_holder = {"value": False}
        legacy_failure_holder = {"value": False}

        async def _mark_failed():
            async with AsyncSessionLocal() as failed_db:
                if context.get("event_id"):
                    await lock_event_face_mutation(context["event_id"], failed_db)
                failed_photo = (await failed_db.execute(
                    select(Photo).where(Photo.id == photo_uuid)
                )).scalar_one_or_none()
                transition = None
                if item_uuid is not None and context["item_validated"]:
                    transition = await mark_item_terminal(
                        failed_db,
                        item_id=item_uuid,
                        status=BatchItemStatus.failed,
                        processing_ms=int((time.perf_counter() - started_clock) * 1000),
                        processor=detect_runtime_processor(),
                        error_message=exc_str,
                    )
                    transition_holder["value"] = transition
                may_mark_photo = item_uuid is None or (
                    transition is not None and transition.applied
                )
                if (
                    failed_photo
                    and failed_photo.status != PhotoStatus.done
                    and context["safe_to_mutate"]
                    and may_mark_photo
                ):
                    failed_photo.status = PhotoStatus.failed
                    failed_photo.error_message = exc_str[:500]
                    if item_uuid is None:
                        legacy_failure_holder["value"] = True
                if item_uuid is None and context["safe_to_mutate"] and context.get("event_id"):
                    pending = (await failed_db.execute(
                        select(sa_func.count(Photo.id)).where(
                            Photo.event_id == context["event_id"],
                            Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
                        )
                    )).scalar() or 0
                    legacy_ready_holder["value"] = pending == 0
                await failed_db.commit()

        try:
            run_async(_mark_failed())
            transition = transition_holder["value"]
            if transition and transition.applied:
                record_completion_sync(
                    batch_id=transition.batch_id,
                    tenant_id=transition.tenant_id,
                    faces_detected=0,
                )
            resolved_event_id = context.get("event_id")
            if (
                resolved_event_id
                and context["safe_to_mutate"]
                and item_uuid is None
                and legacy_failure_holder["value"]
                and legacy_ready_holder["value"]
            ):
                recluster_event_task.apply_async(
                    kwargs={"event_id": str(resolved_event_id)},
                    countdown=1,
                    queue="face-v2",
                )
        except Exception:
            pass
        raise


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    time_limit=900,
    soft_time_limit=840,
    name="app.workers.tasks.import_drive_item",
)
def import_drive_item(self, batch_item_id: str):
    """Durably download one Drive placeholder, then enqueue face processing."""
    import hashlib

    import httpx
    from sqlalchemy import select

    from ..config import get_settings
    from ..database import AsyncSessionLocal
    from ..models import (
        BatchItemStatus,
        BatchSource,
        Photo,
        PhotoStatus,
        Subscription,
    )
    from ..services.batch_tracking import (
        get_item_context,
        mark_item_retrying,
        mark_item_started,
        mark_item_terminal,
    )
    from ..services.dispatcher import dispatch_item_ids
    from ..services.storage import upload_original, upload_thumbnail
    from ..services.telemetry import record_completion_sync

    settings = get_settings()
    item_uuid = uuid.UUID(str(batch_item_id))

    async def _run():
        async with AsyncSessionLocal() as db:
            row = await get_item_context(db, item_id=item_uuid)
            if row is None:
                return "missing"
            item, batch, photo = row
            if item.status in (
                BatchItemStatus.succeeded,
                BatchItemStatus.failed,
                BatchItemStatus.skipped,
                BatchItemStatus.cancelled,
            ):
                return "terminal"
            if batch.source != BatchSource.drive_import or photo is None:
                transition = await mark_item_terminal(
                    db,
                    item_id=item.id,
                    status=BatchItemStatus.failed,
                    error_message="Invalid Drive import batch item",
                )
                await db.commit()
                if transition.applied:
                    record_completion_sync(
                        batch_id=transition.batch_id,
                        tenant_id=transition.tenant_id,
                        faces_detected=0,
                        images=0,
                    )
                return "invalid"

            claimed = await mark_item_started(
                db,
                item_id=item.id,
                task_id=str(self.request.id or "") or None,
            )
            if not claimed:
                await db.rollback()
                current = await get_item_context(db, item_id=item_uuid)
                if current is not None and current[0].status == BatchItemStatus.processing:
                    raise ProcessingLeaseBusy(
                        f"Drive item {item_uuid} is still owned by another delivery"
                    )
                return "not-claimable"

            photo.status = PhotoStatus.processing
            photo.error_message = None
            await db.commit()

            # A prior delivery may have committed the storage stage and died
            # before publishing face work. Re-open the item without downloading.
            if photo.original_key:
                released = await mark_item_retrying(
                    db, item_id=item.id, error_message=None
                )
                if released:
                    photo.status = PhotoStatus.queued
                await db.commit()
                if released:
                    try:
                        await dispatch_item_ids([item.id])
                    except Exception as dispatch_exc:
                        logger.warning("Drive face dispatch deferred: %s", dispatch_exc)
                return "already-downloaded"

            if not settings.GOOGLE_DRIVE_API_KEY or not item.source_ref:
                raise ValueError("Google Drive import is not configured")

            download_url = (
                f"https://www.googleapis.com/drive/v3/files/{item.source_ref}"
                f"?alt=media&key={settings.GOOGLE_DRIVE_API_KEY}"
            )
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.get(
                    download_url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; PhotoGroup/2.0)"},
                    follow_redirects=True,
                )
            if response.status_code != 200:
                raise ValueError(f"Drive download failed: HTTP {response.status_code}")
            data = response.content
            if len(data) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
                raise ValueError("Drive image exceeds the upload size limit")
            content_hash = hashlib.sha256(data).hexdigest()
            duplicate = (await db.execute(
                select(Photo.id).where(
                    Photo.event_id == batch.event_id,
                    Photo.content_hash == content_hash,
                    Photo.id != photo.id,
                ).limit(1)
            )).scalar_one_or_none()
            if duplicate is not None:
                transition = await mark_item_terminal(
                    db,
                    item_id=item.id,
                    status=BatchItemStatus.skipped,
                    error_message="Duplicate photo",
                )
                await db.delete(photo)
                await db.commit()
                if transition.applied:
                    record_completion_sync(
                        batch_id=transition.batch_id,
                        tenant_id=transition.tenant_id,
                        faces_detected=0,
                        images=0,
                    )
                return "duplicate"

            original_key = await upload_original(
                data,
                batch.tenant_id,
                batch.event_id,
                photo.id,
                photo.filename,
                photo.mime_type,
            )
            thumbnail_key = await upload_thumbnail(
                data,
                batch.tenant_id,
                batch.event_id,
                photo.id,
                filename=photo.filename,
            )
            file_size = len(data)
            del data

            photo.original_key = original_key
            photo.thumbnail_key = thumbnail_key
            photo.original_size_bytes = file_size
            photo.content_hash = content_hash
            released = await mark_item_retrying(db, item_id=item.id, error_message=None)
            if released:
                photo.status = PhotoStatus.queued
                subscription = (await db.execute(
                    select(Subscription).where(Subscription.tenant_id == batch.tenant_id)
                )).scalar_one_or_none()
                if subscription:
                    subscription.current_storage_bytes = (
                        subscription.current_storage_bytes or 0
                    ) + file_size
            await db.commit()
            if released:
                try:
                    await dispatch_item_ids([item.id])
                except Exception as dispatch_exc:
                    logger.warning("Drive face dispatch deferred: %s", dispatch_exc)
            return "downloaded"

    try:
        return run_async(_run())
    except ProcessingLeaseBusy as exc:
        raise self.retry(exc=exc, countdown=60, max_retries=20)
    except Exception as exc:
        exc_text = str(exc)
        if self.request.retries < self.max_retries:
            async def _release():
                async with AsyncSessionLocal() as db:
                    released = await mark_item_retrying(
                        db, item_id=item_uuid, error_message=exc_text
                    )
                    row = await get_item_context(db, item_id=item_uuid)
                    if released and row is not None and row[2] is not None:
                        row[2].status = PhotoStatus.queued
                    await db.commit()

            try:
                run_async(_release())
            except Exception:
                pass
            raise self.retry(exc=exc, countdown=min(300, 30 * (2 ** self.request.retries)))

        async def _fail():
            async with AsyncSessionLocal() as db:
                row = await get_item_context(db, item_id=item_uuid)
                if row is None:
                    return None
                item, batch, photo = row
                transition = await mark_item_terminal(
                    db,
                    item_id=item.id,
                    status=BatchItemStatus.failed,
                    error_message=exc_text,
                )
                if transition.applied and photo is not None:
                    photo.status = PhotoStatus.failed
                    photo.error_message = exc_text[:500]
                await db.commit()
                return transition

        transition = run_async(_fail())
        if transition and transition.applied:
            record_completion_sync(
                batch_id=transition.batch_id,
                tenant_id=transition.tenant_id,
                faces_detected=0,
                images=0,
            )
        raise


@shared_task(
    bind=True,
    max_retries=2,
    time_limit=3600,
    soft_time_limit=3540,
    name="app.workers.tasks.recluster_event",
)
def recluster_event_task(self, event_id: str, require_finalizing: bool = False):
    """Finalize event grouping and only then publish batch completion."""
    from datetime import datetime, timezone
    from sqlalchemy import func as sa_func, select, update

    from ..database import AsyncSessionLocal
    from ..models import BatchStatus, Photo, PhotoStatus, ProcessingBatch
    from ..services.batch_tracking import finalize_event_batches
    from ..services.clustering import recluster_event
    from ..services.event_lock import lock_event_face_mutation

    event_uuid = uuid.UUID(str(event_id))

    async def _run():
        async with AsyncSessionLocal() as db:
            await lock_event_face_mutation(event_uuid, db)
            pending = (await db.execute(
                select(sa_func.count(Photo.id)).where(
                    Photo.event_id == event_uuid,
                    Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
                )
            )).scalar() or 0
            if pending > 0:
                logger.info("Event %s grouping deferred; %s photos pending", event_id, pending)
                await db.execute(
                    update(ProcessingBatch)
                    .where(
                        ProcessingBatch.event_id == event_uuid,
                        ProcessingBatch.status == BatchStatus.finalizing,
                    )
                    .values(finalize_dispatched_at=None)
                )
                await db.commit()
                return 0

            if require_finalizing:
                finalizing = (await db.execute(
                    select(sa_func.count(ProcessingBatch.id)).where(
                        ProcessingBatch.event_id == event_uuid,
                        ProcessingBatch.status == BatchStatus.finalizing,
                    )
                )).scalar() or 0
                if finalizing == 0:
                    logger.info(
                        "Ignoring stale finalizer for event %s; no batch is finalizing",
                        event_id,
                    )
                    return 0

            n_clusters = await recluster_event(event_uuid, db)
            finalized = await finalize_event_batches(db, event_id=event_uuid)
            await db.commit()
            logger.info(
                "Event %s grouped into %s clusters; %s batches finalized",
                event_id,
                n_clusters,
                finalized,
            )
            return n_clusters

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("Recluster failed for event %s: %s", event_id, exc)
        async def _record_finalization_error():
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ProcessingBatch)
                    .where(
                        ProcessingBatch.event_id == event_uuid,
                        ProcessingBatch.status == BatchStatus.finalizing,
                    )
                    .values(
                        finalization_error=str(exc)[:500],
                        finalize_dispatched_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()

        try:
            run_async(_record_finalization_error())
        except Exception:
            pass
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(exc=exc)
