"""Tenant-scoped processing snapshots and realtime WebSocket updates."""
from __future__ import annotations

import asyncio
import fnmatch
import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, resolve_user_from_token
from ..config import get_settings
from ..database import AsyncSessionLocal, get_db
from ..models import (
    BatchItemStatus,
    BatchStatus,
    Event,
    ProcessingBatch,
    ProcessingBatchItem,
    Subscription,
    SubscriptionStatus,
    Tenant,
    User,
    UserRole,
)
from ..schemas import (
    ProcessingBatchMetrics,
    ProcessingResources,
    ProcessingSnapshot,
    ProcessingSummary,
)
from ..services.batch_tracking import RUNNING_BATCH_STATUSES, phase_for_status
from ..services.telemetry import read_rate, read_resources

settings = get_settings()
router = APIRouter(prefix="/processing", tags=["Processing"])


def _authorize(user: User) -> None:
    if user.role not in (UserRole.organizer, UserRole.super_admin):
        raise HTTPException(status_code=403, detail="Processing metrics require organizer access")
    if user.role == UserRole.organizer and user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Organizer has no organization scope")


async def _authorize_scope(user: User, db: AsyncSession) -> None:
    _authorize(user)
    if user.role != UserRole.organizer:
        return
    result = await db.execute(
        select(Tenant.is_active, Subscription.status)
        .outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
        .where(Tenant.id == user.tenant_id)
    )
    row = result.one_or_none()
    if not row or not row.is_active or row.status != SubscriptionStatus.active:
        raise HTTPException(status_code=403, detail="Organization or subscription is inactive")


def _processor(value: str | None) -> str:
    normalized = (value or "").lower()
    return normalized if normalized in ("cpu", "gpu", "mixed") else "unknown"


async def build_processing_snapshot(
    user: User,
    db: AsyncSession,
    *,
    seq: int = 0,
) -> ProcessingSnapshot:
    await _authorize_scope(user, db)

    query = (
        select(ProcessingBatch, Event.name)
        .join(Event, Event.id == ProcessingBatch.event_id)
        .where(ProcessingBatch.status.in_(RUNNING_BATCH_STATUSES))
        .order_by(ProcessingBatch.created_at.desc())
    )
    if user.role == UserRole.organizer:
        query = query.where(ProcessingBatch.tenant_id == user.tenant_id)
    rows = (await db.execute(query)).all()
    batch_ids = [batch.id for batch, _ in rows]

    item_stats: dict[uuid.UUID, tuple[int, float | None]] = {}
    if batch_ids:
        stats_result = await db.execute(
            select(
                ProcessingBatchItem.batch_id,
                func.sum(
                    case(
                        (ProcessingBatchItem.status == BatchItemStatus.processing, 1),
                        else_=0,
                    )
                ),
                func.avg(ProcessingBatchItem.processing_ms),
            )
            .where(ProcessingBatchItem.batch_id.in_(batch_ids))
            .group_by(ProcessingBatchItem.batch_id)
        )
        item_stats = {
            batch_id: (int(active or 0), float(avg_ms) if avg_ms is not None else None)
            for batch_id, active, avg_ms in stats_result.all()
        }

    scope_rate_task = asyncio.create_task(
        read_rate(tenant_id=user.tenant_id if user.role == UserRole.organizer else None)
    )
    resources_task = asyncio.create_task(read_resources())
    batch_rates = await asyncio.gather(
        *(read_rate(batch_id=batch_id) for batch_id in batch_ids)
    ) if batch_ids else []
    scope_images_rate, scope_faces_rate = await scope_rate_task
    resources = ProcessingResources.model_validate(await resources_task)

    batch_payload = []
    displayed_totals: dict[uuid.UUID, int] = {}
    fallback_eta_total = 0.0
    fallback_eta_complete = True
    for index, (batch, event_name) in enumerate(rows):
        active_images, avg_ms = item_stats.get(batch.id, (0, None))
        images_rate, faces_rate = batch_rates[index]
        displayed_total = batch.total_images
        if batch.status == BatchStatus.receiving and batch.expected_images is not None:
            displayed_total = max(displayed_total, batch.expected_images)
        displayed_totals[batch.id] = displayed_total
        remaining = max(0, displayed_total - batch.completed_images)
        eta = None
        if batch.status.value == "finalizing":
            eta = None
        elif remaining == 0:
            eta = 0
        elif images_rate > 0:
            eta = max(1, math.ceil(remaining / images_rate))
        elif avg_ms and avg_ms > 0:
            eta = max(1, math.ceil((remaining * avg_ms) / 1000.0))

        if remaining and avg_ms and avg_ms > 0:
            fallback_eta_total += (remaining * avg_ms) / 1000.0
        elif remaining:
            fallback_eta_complete = False

        progress = (
            round(min(100.0, batch.completed_images * 100.0 / displayed_total), 1)
            if displayed_total
            else 0.0
        )
        batch_payload.append(ProcessingBatchMetrics(
            id=batch.id,
            event_id=batch.event_id,
            event_name=event_name,
            source=batch.source,
            status=batch.status,
            phase=(
                "finalization_retrying"
                if batch.status == BatchStatus.finalizing and batch.finalization_error
                else phase_for_status(batch.status)
            ),
            processor=_processor(batch.processor),
            total_images=displayed_total,
            completed_images=batch.completed_images,
            succeeded_images=batch.succeeded_images,
            failed_images=batch.failed_images,
            skipped_images=batch.skipped_images,
            active_images=active_images,
            remaining_images=remaining,
            faces_detected=batch.faces_detected,
            images_per_second=images_rate,
            faces_per_second=faces_rate,
            eta_seconds=eta,
            progress_percent=progress,
            finalization_error=batch.finalization_error,
            created_at=batch.created_at,
            started_at=batch.started_at,
            last_activity_at=batch.last_activity_at,
            completed_at=batch.completed_at,
            updated_at=batch.updated_at,
        ))

    total_images = sum(displayed_totals.get(batch.id, batch.total_images) for batch, _ in rows)
    completed_images = sum(batch.completed_images for batch, _ in rows)
    remaining_images = max(0, total_images - completed_images)
    has_finalizing = any(batch.status.value == "finalizing" for batch, _ in rows)
    if has_finalizing:
        summary_eta = None
    elif remaining_images == 0:
        summary_eta = 0
    elif scope_images_rate > 0:
        summary_eta = max(1, math.ceil(remaining_images / scope_images_rate))
    elif fallback_eta_complete and fallback_eta_total > 0:
        summary_eta = max(1, math.ceil(fallback_eta_total))
    else:
        summary_eta = None

    summary = ProcessingSummary(
        running_batches=len(rows),
        total_images=total_images,
        completed_images=completed_images,
        succeeded_images=sum(batch.succeeded_images for batch, _ in rows),
        failed_images=sum(batch.failed_images for batch, _ in rows),
        skipped_images=sum(batch.skipped_images for batch, _ in rows),
        active_images=sum(item_stats.get(batch.id, (0, None))[0] for batch, _ in rows),
        remaining_images=remaining_images,
        faces_detected=sum(batch.faces_detected for batch, _ in rows),
        images_per_second=scope_images_rate,
        faces_per_second=scope_faces_rate,
        eta_seconds=summary_eta,
    )
    scope = (
        {"type": "global"}
        if user.role == UserRole.super_admin
        else {"type": "organization", "tenant_id": str(user.tenant_id)}
    )
    return ProcessingSnapshot(
        seq=seq,
        emitted_at=datetime.now(timezone.utc),
        scope=scope,
        summary=summary,
        resources=resources,
        # Super admins receive the requested global total, not cross-tenant
        # batch details. Organizer connections get their own running batches.
        batches=[] if user.role == UserRole.super_admin else batch_payload,
    )


@router.get("/snapshot", response_model=ProcessingSnapshot)
async def processing_snapshot(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await build_processing_snapshot(current_user, db)


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True  # Non-browser clients and backend health probes.
    return any(fnmatch.fnmatch(origin, pattern) for pattern in settings.CORS_ORIGINS)


@router.websocket("/ws")
async def processing_websocket(websocket: WebSocket):
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    await websocket.accept()
    try:
        auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        if auth_message.get("type") != "auth" or not auth_message.get("token"):
            await websocket.close(code=4401, reason="Authentication required")
            return
        token = str(auth_message["token"])

        # Authenticate before starting the stream. Re-resolving in every loop
        # also notices expiry, suspension, role changes, and tenant changes.
        async with AsyncSessionLocal() as db:
            try:
                user = await resolve_user_from_token(token, db)
                await _authorize_scope(user, db)
            except HTTPException as exc:
                await websocket.close(
                    code=4403 if exc.status_code == 403 else 4401,
                    reason=exc.detail,
                )
                return

        seq = 0
        while True:
            async with AsyncSessionLocal() as db:
                try:
                    user = await resolve_user_from_token(token, db)
                    snapshot = await build_processing_snapshot(user, db, seq=seq)
                except HTTPException as exc:
                    await websocket.close(
                        code=4403 if exc.status_code == 403 else 4401,
                        reason=exc.detail,
                    )
                    return
            await websocket.send_json(snapshot.model_dump(mode="json"))
            seq += 1
            await asyncio.sleep(1.0)
    except asyncio.TimeoutError:
        await websocket.close(code=4401, reason="Authentication timed out")
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011, reason="Metrics stream unavailable")
        except Exception:
            pass
