"""Durable database-backed dispatch and stale-work recovery."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import and_, exists, or_, select, update

from ..database import AsyncSessionLocal
from ..models import (
    BatchItemStatus,
    BatchSource,
    BatchStatus,
    Photo,
    PhotoStatus,
    ProcessingBatch,
    ProcessingBatchItem,
)
from .batch_tracking import (
    append_photo_items,
    create_batch,
    mark_item_terminal,
    seal_batch,
)
from .event_lock import lock_event_face_mutation


logger = logging.getLogger(__name__)
DISPATCH_QUEUE = "face-v2"
DISPATCH_CLAIM_TIMEOUT_SECONDS = 60
PUBLISHED_TASK_RECHECK_SECONDS = 24 * 60 * 60
PROCESSING_LEASE_SECONDS = 17 * 60
LEGACY_PHOTO_ADOPTION_SECONDS = 30 * 60
LEGACY_ADOPTION_STARTUP_GRACE_SECONDS = 30 * 60
# A browser may vanish before it can call /seal. Pages are dispatched as they
# arrive, so after this deliberately long grace we close the declared upload
# at the number of files the server actually received.
RECEIVING_BATCH_STALE_SECONDS = 6 * 60 * 60
RECOVERY_INTERVAL_SECONDS = 15
RUNNABLE_BATCH_STATUSES = (
    BatchStatus.receiving,
    BatchStatus.queued,
    BatchStatus.running,
)
_dispatcher_started_monotonic = time.monotonic()


@dataclass(frozen=True)
class DispatchRecord:
    item_id: uuid.UUID
    photo_id: uuid.UUID
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    source: BatchSource
    source_ref: Optional[str]
    original_key: str
    claim_token: str


async def _claim_items(
    *,
    item_ids: Optional[Iterable[uuid.UUID]] = None,
    limit: int = 100,
) -> list[DispatchRecord]:
    now = datetime.now(timezone.utc)
    stale_claim_before = now - timedelta(seconds=DISPATCH_CLAIM_TIMEOUT_SECONDS)
    stale_publish_before = now - timedelta(seconds=PUBLISHED_TASK_RECHECK_SECONDS)
    async with AsyncSessionLocal() as db:
        query = (
            select(ProcessingBatchItem, ProcessingBatch, Photo)
            .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
            .join(Photo, Photo.id == ProcessingBatchItem.photo_id)
            .where(
                ProcessingBatchItem.status == BatchItemStatus.queued,
                ProcessingBatch.status.in_(RUNNABLE_BATCH_STATUSES),
                or_(
                    ProcessingBatchItem.celery_task_id.is_(None),
                    and_(
                        ProcessingBatchItem.celery_task_id.like("dispatching:%"),
                        ProcessingBatchItem.dispatch_attempted_at < stale_claim_before,
                    ),
                    and_(
                        ProcessingBatchItem.celery_task_id.is_not(None),
                        ~ProcessingBatchItem.celery_task_id.like("dispatching:%"),
                        ProcessingBatchItem.dispatch_attempted_at < stale_publish_before,
                    ),
                ),
            )
            .order_by(ProcessingBatchItem.queued_at, ProcessingBatchItem.id)
            .limit(max(1, min(int(limit), 500)))
            .with_for_update(of=ProcessingBatchItem, skip_locked=True)
        )
        if item_ids is not None:
            normalized_ids = [uuid.UUID(str(item_id)) for item_id in item_ids]
            if not normalized_ids:
                return []
            query = query.where(ProcessingBatchItem.id.in_(normalized_ids))

        rows = (await db.execute(query)).all()
        records: list[DispatchRecord] = []
        for item, batch, photo in rows:
            claim_token = f"dispatching:{uuid.uuid4()}"
            item.celery_task_id = claim_token
            item.dispatch_attempted_at = now
            records.append(DispatchRecord(
                item_id=item.id,
                photo_id=photo.id,
                tenant_id=batch.tenant_id,
                event_id=batch.event_id,
                source=batch.source,
                source_ref=item.source_ref,
                original_key=photo.original_key or "",
                claim_token=claim_token,
            ))
        await db.commit()
        return records


async def _finish_dispatch_claim(
    record: DispatchRecord,
    *,
    task_id: Optional[str],
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ProcessingBatchItem)
            .where(
                ProcessingBatchItem.id == record.item_id,
                ProcessingBatchItem.status == BatchItemStatus.queued,
                ProcessingBatchItem.celery_task_id == record.claim_token,
            )
            .values(
                celery_task_id=task_id,
                dispatch_attempted_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _publish(record: DispatchRecord) -> bool:
    try:
        from ..workers.tasks import import_drive_item, process_photo

        if record.source == BatchSource.drive_import and not record.original_key:
            if not record.source_ref:
                raise ValueError("Drive batch item has no source file identifier")
            result = await asyncio.to_thread(
                import_drive_item.apply_async,
                args=[str(record.item_id)],
                queue=DISPATCH_QUEUE,
            )
        else:
            result = await asyncio.to_thread(
                process_photo.apply_async,
                args=[
                    str(record.photo_id),
                    str(record.tenant_id),
                    str(record.event_id),
                ],
                kwargs={"batch_item_id": str(record.item_id)},
                queue=DISPATCH_QUEUE,
            )
        await _finish_dispatch_claim(record, task_id=str(result.id))
        return True
    except Exception as exc:
        logger.warning("Could not publish batch item %s: %s", record.item_id, exc)
        # Clear only our own claim. A later recovery pass will retry once the
        # broker or database is healthy again.
        try:
            await _finish_dispatch_claim(record, task_id=None)
        except Exception:
            pass
        return False


async def dispatch_item_ids(item_ids: Iterable[uuid.UUID | str]) -> int:
    records = await _claim_items(item_ids=item_ids, limit=500)
    dispatched = 0
    for record in records:
        dispatched += int(await _publish(record))
    return dispatched


async def _seal_stale_receiving_batches() -> int:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=RECEIVING_BATCH_STALE_SECONDS)
    async with AsyncSessionLocal() as db:
        batches = (await db.execute(
            select(ProcessingBatch)
            .where(
                ProcessingBatch.status == BatchStatus.receiving,
                ProcessingBatch.last_activity_at < stale_before,
            )
            .order_by(ProcessingBatch.last_activity_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        for batch in batches:
            # Once sealed, progress is measured against what reached the
            # server rather than a client-side selection that never arrived.
            batch.expected_images = batch.total_images
            batch.last_activity_at = now
            batch.updated_at = now
            if batch.total_images == 0:
                batch.status = BatchStatus.cancelled
                batch.completed_at = now
            elif batch.completed_images >= batch.total_images:
                batch.status = BatchStatus.finalizing
            else:
                batch.status = BatchStatus.running
        await db.commit()
        if batches:
            logger.info("Server-sealed %s abandoned receiving batch(es)", len(batches))
        return len(batches)


async def _adopt_stale_untracked_photos() -> int:
    """Move pre-batch queued photos into the durable dispatch pipeline.

    Older releases could publish Celery before the Photo transaction committed.
    A fast worker then acknowledged a missing row, leaving the later commit
    queued forever. Adopt one event per recovery tick after a long grace so an
    in-flight legacy task is not mistaken for abandoned work.
    """
    if (
        time.monotonic() - _dispatcher_started_monotonic
        < LEGACY_ADOPTION_STARTUP_GRACE_SECONDS
    ):
        return 0

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=LEGACY_PHOTO_ADOPTION_SECONDS)
    active_item = exists(
        select(ProcessingBatchItem.id)
        .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
        .where(
            ProcessingBatchItem.photo_id == Photo.id,
            ProcessingBatchItem.status.in_([
                BatchItemStatus.queued,
                BatchItemStatus.processing,
            ]),
            ProcessingBatch.status.in_(RUNNABLE_BATCH_STATUSES),
        )
    )
    candidate_filter = (
        Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
        Photo.uploaded_at < stale_before,
        ~active_item,
    )

    async with AsyncSessionLocal() as db:
        event_id = (await db.execute(
            select(Photo.event_id)
            .where(*candidate_filter)
            .order_by(Photo.uploaded_at, Photo.id)
            .limit(1)
        )).scalar_one_or_none()
        if event_id is None:
            return 0

        # Event-level lock order matches reprocess, clear, and regroup paths.
        # A second web instance rechecks the filter after the first commits.
        await lock_event_face_mutation(event_id, db)
        photos = (await db.execute(
            select(Photo)
            .where(Photo.event_id == event_id, *candidate_filter)
            .order_by(Photo.uploaded_at, Photo.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        if not photos:
            await db.rollback()
            return 0

        recoverable = []
        for photo in photos:
            if photo.original_key:
                recoverable.append(photo)
                photo.status = PhotoStatus.queued
                photo.error_message = None
            else:
                photo.status = PhotoStatus.failed
                photo.error_message = (
                    "The original Drive file was never stored. Select it again "
                    "in Google Drive to re-import it."
                )

        if recoverable:
            exemplar = recoverable[0]
            batch = await create_batch(
                db,
                tenant_id=exemplar.tenant_id,
                event_id=event_id,
                created_by_user_id=None,
                source=BatchSource.retry,
                expected_images=len(recoverable),
            )
            await append_photo_items(db, batch_id=batch.id, photos=recoverable)
            await seal_batch(
                db,
                batch_id=batch.id,
                tenant_id=exemplar.tenant_id,
                event_id=event_id,
            )
        await db.commit()
        logger.info(
            "Adopted %s stale pre-batch photo(s) for event %s (%s recoverable)",
            len(photos),
            event_id,
            len(recoverable),
        )
        return len(photos)


async def _recover_stale_items() -> set[uuid.UUID]:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=PROCESSING_LEASE_SECONDS)
    affected_events: set[uuid.UUID] = set()
    async with AsyncSessionLocal() as db:
        stale_rows = (await db.execute(
            select(ProcessingBatchItem, ProcessingBatch)
            .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
            .where(
                ProcessingBatchItem.status == BatchItemStatus.processing,
                ProcessingBatchItem.started_at < stale_before,
            )
            .order_by(ProcessingBatchItem.started_at)
            .limit(200)
            .with_for_update(of=ProcessingBatchItem, skip_locked=True)
        )).all()
        photo_ids = [
            item.photo_id for item, _batch in stale_rows if item.photo_id is not None
        ]
        photos_by_id = {}
        if photo_ids:
            photos = (await db.execute(
                select(Photo).where(Photo.id.in_(photo_ids))
            )).scalars().all()
            photos_by_id = {photo.id: photo for photo in photos}

        for item, batch in stale_rows:
            item.status = BatchItemStatus.queued
            item.celery_task_id = None
            item.dispatch_attempted_at = None
            item.started_at = None
            item.finished_at = None
            item.error_message = "Recovered after an interrupted worker lease"
            photo = photos_by_id.get(item.photo_id) if item.photo_id else None
            if photo is not None and photo.status != PhotoStatus.done:
                photo.status = PhotoStatus.queued
                photo.error_message = None
            affected_events.add(batch.event_id)

        orphan_rows = (await db.execute(
            select(ProcessingBatchItem, ProcessingBatch)
            .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
            .where(
                ProcessingBatchItem.status.in_([
                    BatchItemStatus.queued,
                    BatchItemStatus.processing,
                ]),
                ProcessingBatchItem.photo_id.is_(None),
            )
            .limit(200)
            .with_for_update(of=ProcessingBatchItem, skip_locked=True)
        )).all()
        for item, batch in orphan_rows:
            transition = await mark_item_terminal(
                db,
                item_id=item.id,
                status=BatchItemStatus.cancelled,
                error_message="Photo was removed before processing completed",
            )
            if transition.applied:
                affected_events.add(batch.event_id)
        await db.commit()
    return affected_events


async def dispatch_ready_finalizers() -> None:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=75)
    async with AsyncSessionLocal() as db:
        pending_photo = exists(
            select(Photo.id).where(
                Photo.event_id == ProcessingBatch.event_id,
                Photo.status.in_([PhotoStatus.queued, PhotoStatus.processing]),
            )
        )
        batches = (await db.execute(
            select(ProcessingBatch)
            .where(
                ProcessingBatch.status == BatchStatus.finalizing,
                or_(
                    ProcessingBatch.finalize_dispatched_at.is_(None),
                    ProcessingBatch.finalize_dispatched_at < stale_before,
                ),
                ~pending_photo,
            )
            .order_by(ProcessingBatch.last_activity_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        event_ids = sorted({batch.event_id for batch in batches}, key=str)
        if event_ids:
            await db.execute(
                update(ProcessingBatch)
                .where(
                    ProcessingBatch.event_id.in_(event_ids),
                    ProcessingBatch.status == BatchStatus.finalizing,
                )
                .values(finalize_dispatched_at=now)
            )
        await db.commit()
    if not event_ids:
        return
    from ..workers.tasks import recluster_event_task

    for event_id in event_ids:
        try:
            await asyncio.to_thread(
                recluster_event_task.apply_async,
                kwargs={
                    "event_id": str(event_id),
                    "require_finalizing": True,
                },
                queue=DISPATCH_QUEUE,
            )
        except Exception as exc:
            logger.warning("Could not publish finalizer for event %s: %s", event_id, exc)
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ProcessingBatch)
                    .where(
                        ProcessingBatch.event_id == event_id,
                        ProcessingBatch.status == BatchStatus.finalizing,
                        ProcessingBatch.finalize_dispatched_at == now,
                    )
                    .values(finalize_dispatched_at=None)
                )
                await db.commit()
            return


async def recover_and_dispatch_once() -> int:
    await _seal_stale_receiving_batches()
    await _adopt_stale_untracked_photos()
    await _recover_stale_items()
    records = await _claim_items(limit=100)
    dispatched = 0
    for record in records:
        dispatched += int(await _publish(record))
    await dispatch_ready_finalizers()
    return dispatched


async def recovery_dispatch_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await recover_and_dispatch_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Durable processing recovery pass failed")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=RECOVERY_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            continue
