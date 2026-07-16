"""Durable, tenant-scoped processing batch state transitions.

The database is the source of truth.  All terminal item transitions are
conditional and update their parent counters in the same transaction, making
Celery redelivery and retries idempotent.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, case, cast, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    BatchItemStatus,
    BatchSource,
    BatchStatus,
    Photo,
    ProcessingBatch,
    ProcessingBatchItem,
)


RUNNING_BATCH_STATUSES = (
    BatchStatus.receiving,
    BatchStatus.queued,
    BatchStatus.running,
    BatchStatus.finalizing,
)
TERMINAL_ITEM_STATUSES = (
    BatchItemStatus.succeeded,
    BatchItemStatus.failed,
    BatchItemStatus.skipped,
    BatchItemStatus.cancelled,
)


def _batch_status_value(status: BatchStatus):
    return cast(literal(status.value), ProcessingBatch.status.type)


class BatchStateError(ValueError):
    """Raised when a caller attempts an invalid batch transition."""


@dataclass(frozen=True)
class TerminalTransition:
    applied: bool
    batch_id: Optional[uuid.UUID] = None
    tenant_id: Optional[uuid.UUID] = None
    event_id: Optional[uuid.UUID] = None
    batch_finalizing: bool = False


async def create_batch(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    created_by_user_id: Optional[uuid.UUID],
    source: BatchSource,
    expected_images: Optional[int] = None,
) -> ProcessingBatch:
    batch = ProcessingBatch(
        tenant_id=tenant_id,
        event_id=event_id,
        created_by_user_id=created_by_user_id,
        source=source,
        status=BatchStatus.receiving,
        expected_images=max(0, int(expected_images)) if expected_images is not None else None,
    )
    db.add(batch)
    await db.flush()
    return batch


async def get_scoped_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    event_id: Optional[uuid.UUID] = None,
    for_update: bool = False,
) -> Optional[ProcessingBatch]:
    query = select(ProcessingBatch).where(
        ProcessingBatch.id == batch_id,
        ProcessingBatch.tenant_id == tenant_id,
    )
    if event_id is not None:
        query = query.where(ProcessingBatch.event_id == event_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def append_item(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID,
    photo_id: Optional[uuid.UUID],
    filename: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> ProcessingBatchItem:
    """Append one item only while a batch is receiving.

    The guarded counter update prevents a concurrent seal from silently
    accepting an item after the batch stopped receiving.
    """
    item = ProcessingBatchItem(
        batch_id=batch_id,
        photo_id=photo_id,
        filename=filename,
        source_ref=source_ref,
        status=BatchItemStatus.queued,
    )
    db.add(item)
    await db.flush()

    result = await db.execute(
        update(ProcessingBatch)
        .where(
            ProcessingBatch.id == batch_id,
            ProcessingBatch.status == BatchStatus.receiving,
        )
        .values(
            total_images=ProcessingBatch.total_images + 1,
            last_activity_at=func.now(),
            updated_at=func.now(),
        )
        .returning(ProcessingBatch.id)
    )
    if result.scalar_one_or_none() is None:
        raise BatchStateError("Batch is no longer receiving images")
    return item


async def append_photo_items(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID,
    photos: list[Photo],
) -> list[ProcessingBatchItem]:
    """Bulk append an already-known photo set to one receiving batch."""
    if not photos:
        return []
    items = [
        ProcessingBatchItem(
            batch_id=batch_id,
            photo_id=photo.id,
            filename=photo.filename,
            status=BatchItemStatus.queued,
        )
        for photo in photos
    ]
    db.add_all(items)
    await db.flush()
    result = await db.execute(
        update(ProcessingBatch)
        .where(
            ProcessingBatch.id == batch_id,
            ProcessingBatch.status == BatchStatus.receiving,
        )
        .values(
            total_images=ProcessingBatch.total_images + len(items),
            last_activity_at=func.now(),
            updated_at=func.now(),
        )
        .returning(ProcessingBatch.id)
    )
    if result.scalar_one_or_none() is None:
        raise BatchStateError("Batch is no longer receiving images")
    return items


async def seal_batch(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID,
    tenant_id: uuid.UUID,
    event_id: Optional[uuid.UUID] = None,
) -> ProcessingBatch:
    batch = await get_scoped_batch(
        db,
        batch_id,
        tenant_id=tenant_id,
        event_id=event_id,
        for_update=True,
    )
    if batch is None:
        raise BatchStateError("Batch not found")

    if batch.status == BatchStatus.receiving:
        if batch.total_images == 0:
            batch.status = BatchStatus.completed
            batch.completed_at = func.now()
        elif batch.completed_images >= batch.total_images:
            # Explicit upload batches begin processing as pages are uploaded.
            # Keep them open for more items until seal, then enter final
            # grouping once every item already reached a terminal state.
            batch.status = BatchStatus.finalizing
        else:
            batch.status = BatchStatus.running
        batch.last_activity_at = func.now()
    elif batch.status not in (
        BatchStatus.queued,
        BatchStatus.running,
        BatchStatus.finalizing,
        BatchStatus.completed,
        BatchStatus.partial_failed,
        BatchStatus.failed,
    ):
        raise BatchStateError(f"Cannot seal a {batch.status.value} batch")

    await db.flush()
    return batch


async def set_item_task_id(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    task_id: Optional[str],
) -> None:
    if not task_id:
        return
    await db.execute(
        update(ProcessingBatchItem)
        .where(
            ProcessingBatchItem.id == item_id,
            ProcessingBatchItem.status == BatchItemStatus.queued,
        )
        .values(celery_task_id=task_id)
    )


async def mark_item_started(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    processor: Optional[str] = None,
    task_id: Optional[str] = None,
    lease_seconds: int = 17 * 60,
) -> bool:
    """Atomically claim queued work or reclaim an expired processing lease."""
    stale_before = datetime.now(timezone.utc) - timedelta(
        seconds=max(60, int(lease_seconds))
    )
    result = await db.execute(
        update(ProcessingBatchItem)
        .where(
            ProcessingBatchItem.id == item_id,
            or_(
                ProcessingBatchItem.status == BatchItemStatus.queued,
                and_(
                    ProcessingBatchItem.status == BatchItemStatus.processing,
                    ProcessingBatchItem.started_at < stale_before,
                ),
            ),
        )
        .values(
            status=BatchItemStatus.processing,
            attempt_count=ProcessingBatchItem.attempt_count + 1,
            started_at=func.now(),
            finished_at=None,
            error_message=None,
            processor=processor,
            celery_task_id=task_id,
            dispatch_attempted_at=func.now(),
        )
        .returning(ProcessingBatchItem.batch_id)
    )
    batch_id = result.scalar_one_or_none()
    if batch_id is None:
        return False

    processor_value = (processor or "").lower()
    values = {
        # An explicit upload batch may process items while it is still open
        # for more uploads.  Starting an item must not implicitly seal it.
        "status": case(
            (
                ProcessingBatch.status == BatchStatus.receiving,
                _batch_status_value(BatchStatus.receiving),
            ),
            else_=_batch_status_value(BatchStatus.running),
        ),
        "started_at": func.coalesce(ProcessingBatch.started_at, func.now()),
        "last_activity_at": func.now(),
        "updated_at": func.now(),
    }
    if processor_value in ("cpu", "gpu"):
        values["processor"] = case(
            (ProcessingBatch.processor.is_(None), processor_value),
            (ProcessingBatch.processor == processor_value, processor_value),
            else_="mixed",
        )
    await db.execute(
        update(ProcessingBatch)
        .where(
            ProcessingBatch.id == batch_id,
            ProcessingBatch.status.in_(RUNNING_BATCH_STATUSES),
        )
        .values(**values)
    )
    return True


async def mark_item_retrying(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    error_message: Optional[str],
) -> bool:
    result = await db.execute(
        update(ProcessingBatchItem)
        .where(
            ProcessingBatchItem.id == item_id,
            ProcessingBatchItem.status == BatchItemStatus.processing,
        )
        .values(
            status=BatchItemStatus.queued,
            error_message=(error_message or "")[:500] or None,
            celery_task_id=None,
            dispatch_attempted_at=None,
            started_at=None,
            finished_at=None,
        )
    )
    return bool(result.rowcount)


async def mark_item_terminal(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
    status: BatchItemStatus,
    faces_detected: int = 0,
    processing_ms: Optional[int] = None,
    processor: Optional[str] = None,
    error_message: Optional[str] = None,
) -> TerminalTransition:
    """Finish an item and increment its batch exactly once.

    Callers must commit the surrounding transaction.  A duplicate task sees
    ``applied=False`` and must not emit another Redis throughput event.
    """
    if status not in TERMINAL_ITEM_STATUSES:
        raise BatchStateError(f"{status.value} is not a terminal item status")

    safe_faces = max(0, int(faces_detected or 0))
    safe_ms = max(0, int(processing_ms)) if processing_ms is not None else None
    processor_value = (processor or "").lower()
    if processor_value not in ("cpu", "gpu"):
        processor_value = None

    result = await db.execute(
        update(ProcessingBatchItem)
        .where(
            ProcessingBatchItem.id == item_id,
            ProcessingBatchItem.status.notin_(TERMINAL_ITEM_STATUSES),
        )
        .values(
            status=status,
            faces_detected=safe_faces,
            processing_ms=safe_ms,
            processor=processor_value,
            error_message=(error_message or "")[:500] or None,
            finished_at=func.now(),
        )
        .returning(ProcessingBatchItem.batch_id)
    )
    batch_id = result.scalar_one_or_none()
    if batch_id is None:
        return TerminalTransition(applied=False)

    succeeded_inc = 1 if status == BatchItemStatus.succeeded else 0
    failed_inc = 1 if status == BatchItemStatus.failed else 0
    skipped_inc = 1 if status in (BatchItemStatus.skipped, BatchItemStatus.cancelled) else 0
    new_completed = ProcessingBatch.completed_images + 1
    new_failed = ProcessingBatch.failed_images + failed_inc
    next_status = case(
        # Keep an explicitly-sized upload open only until all declared files
        # have been accounted for. This closes the page-close/seal-loss gap.
        (
            (ProcessingBatch.status == BatchStatus.receiving)
            & (
            ProcessingBatch.expected_images.is_(None)
                | (ProcessingBatch.total_images < ProcessingBatch.expected_images)
            ),
            _batch_status_value(BatchStatus.receiving),
        ),
        (
            new_completed >= ProcessingBatch.total_images,
            _batch_status_value(BatchStatus.finalizing),
        ),
        else_=_batch_status_value(BatchStatus.running),
    )

    values = {
        "completed_images": new_completed,
        "succeeded_images": ProcessingBatch.succeeded_images + succeeded_inc,
        "failed_images": new_failed,
        "skipped_images": ProcessingBatch.skipped_images + skipped_inc,
        "faces_detected": ProcessingBatch.faces_detected + safe_faces,
        "status": next_status,
        "last_activity_at": func.now(),
        "updated_at": func.now(),
    }
    if processor_value:
        values["processor"] = case(
            (ProcessingBatch.processor.is_(None), processor_value),
            (ProcessingBatch.processor == processor_value, processor_value),
            else_="mixed",
        )

    batch_result = await db.execute(
        update(ProcessingBatch)
        .where(ProcessingBatch.id == batch_id)
        .values(**values)
        .returning(
            ProcessingBatch.tenant_id,
            ProcessingBatch.event_id,
            ProcessingBatch.status,
        )
    )
    tenant_id, event_id, batch_status = batch_result.one()
    return TerminalTransition(
        applied=True,
        batch_id=batch_id,
        tenant_id=tenant_id,
        event_id=event_id,
        batch_finalizing=batch_status == BatchStatus.finalizing,
    )


async def finalize_event_batches(db: AsyncSession, *, event_id: uuid.UUID) -> int:
    """Publish final batch outcomes only after event face grouping succeeds."""
    final_status = case(
        (
            ProcessingBatch.failed_images >= ProcessingBatch.total_images,
            _batch_status_value(BatchStatus.failed),
        ),
        (
            ProcessingBatch.failed_images > 0,
            _batch_status_value(BatchStatus.partial_failed),
        ),
        else_=_batch_status_value(BatchStatus.completed),
    )
    result = await db.execute(
        update(ProcessingBatch)
        .where(
            ProcessingBatch.event_id == event_id,
            ProcessingBatch.status == BatchStatus.finalizing,
        )
        .values(
            status=final_status,
            completed_at=func.now(),
            finalization_error=None,
            last_activity_at=func.now(),
            updated_at=func.now(),
        )
    )
    return int(result.rowcount or 0)


async def get_item_context(
    db: AsyncSession,
    *,
    item_id: uuid.UUID,
):
    result = await db.execute(
        select(ProcessingBatchItem, ProcessingBatch, Photo)
        .join(ProcessingBatch, ProcessingBatch.id == ProcessingBatchItem.batch_id)
        .outerjoin(Photo, Photo.id == ProcessingBatchItem.photo_id)
        .where(ProcessingBatchItem.id == item_id)
    )
    return result.one_or_none()


def phase_for_status(status: BatchStatus) -> str:
    if status == BatchStatus.receiving:
        return "receiving"
    if status == BatchStatus.queued:
        return "queued"
    if status == BatchStatus.running:
        return "processing"
    if status == BatchStatus.finalizing:
        return "finalizing"
    if status == BatchStatus.cancelled:
        return "cancelled"
    return "complete"
