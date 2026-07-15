"""
Events router — organizer creates/manages events, generates access codes.
"""
import uuid
import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, func

from ..database import get_db
from ..models import (
    Event, User, Photo, PhotoStatus, FaceCluster, FaceDetection,
    Subscription, SubscriptionStatus,
)
from ..auth import require_organizer, get_current_user, get_current_tenant
from ..schemas import EventCreate, EventResponse, EventUpdate, MessageResponse
from ..services.storage_cleanup import collect_photo_assets, delete_asset_keys

router = APIRouter(prefix="/events", tags=["Events"])


def generate_access_code(length: int = 8) -> str:
    """Generate a short alphanumeric access code for attendees."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


async def _event_response(event: Event, db: AsyncSession) -> EventResponse:
    photo_counts = (await db.execute(
        select(
            func.count(Photo.id),
            func.count(Photo.id).filter(Photo.status == PhotoStatus.done),
            func.count(Photo.id).filter(Photo.status == PhotoStatus.failed),
            func.count(Photo.id).filter(Photo.status == PhotoStatus.queued),
            func.count(Photo.id).filter(Photo.status == PhotoStatus.processing),
        ).where(Photo.event_id == event.id)
    )).one()
    photo_count, processed_count, failed_count, queued_count, processing_count = (
        int(value or 0) for value in photo_counts
    )
    from ..services.ml_pipeline import get_pipeline_version

    current_pipeline = get_pipeline_version()
    cluster_count = (await db.execute(
        select(func.count(FaceCluster.id)).where(
            FaceCluster.event_id == event.id,
            FaceCluster.pipeline_version == current_pipeline,
        )
    )).scalar() or 0
    legacy_face_count = (await db.execute(
        select(func.count(FaceDetection.id))
        .join(Photo, Photo.id == FaceDetection.photo_id)
        .where(
            Photo.event_id == event.id,
            FaceDetection.pipeline_version != current_pipeline,
        )
    )).scalar() or 0
    return EventResponse(
        **{k: getattr(event, k) for k in ["id", "name", "description", "access_code", "is_active", "created_at"]},
        photo_count=photo_count,
        processed_count=processed_count,
        failed_count=failed_count,
        queued_count=queued_count,
        processing_count=processing_count,
        cluster_count=cluster_count,
        face_pipeline_version=current_pipeline,
        legacy_face_count=legacy_face_count,
        needs_face_rebuild=legacy_face_count > 0,
    )


@router.get("/", response_model=list[EventResponse])
async def list_events(
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.tenant_id == current_user.tenant_id).order_by(Event.created_at.desc())
    )
    events = result.scalars().all()
    return [await _event_response(e, db) for e in events]


@router.post("/", response_model=EventResponse, status_code=201)
async def create_event(
    body: EventCreate,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    # Check subscription event quota
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
    )
    sub = sub_result.scalar_one_or_none()
    if not sub or sub.status != SubscriptionStatus.active:
        raise HTTPException(status_code=403, detail="Subscription inactive")

    # Count events this month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    events_this_month = (await db.execute(
        select(func.count(Event.id)).where(
            Event.tenant_id == current_user.tenant_id,
            Event.created_at >= month_start,
        )
    )).scalar()

    if events_this_month >= sub.max_events_per_month:
        raise HTTPException(
            status_code=403,
            detail=f"Event limit reached for your plan ({sub.max_events_per_month}/month). Please upgrade.",
        )

    # Generate unique access code
    for _ in range(10):
        code = generate_access_code()
        exists = (await db.execute(select(Event).where(Event.access_code == code))).scalar_one_or_none()
        if not exists:
            break
    else:
        raise HTTPException(status_code=500, detail="Could not generate unique access code")

    event = Event(
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
        access_code=code,
    )
    db.add(event)
    await db.flush()
    return await _event_response(event, db)


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == current_user.tenant_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return await _event_response(event, db)


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: uuid.UUID,
    body: EventUpdate,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == current_user.tenant_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if body.name is not None:
        event.name = body.name
    if body.description is not None:
        event.description = body.description
    if body.is_active is not None:
        event.is_active = body.is_active
    return await _event_response(event, db)


@router.delete("/{event_id}", response_model=MessageResponse)
async def delete_event(
    event_id: uuid.UUID,
    current_user: User = Depends(require_organizer),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == current_user.tenant_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    photos_result = await db.execute(select(Photo).where(Photo.event_id == event_id))
    photos = photos_result.scalars().all()
    asset_keys, deleted_bytes = await collect_photo_assets(db, photos)

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

    # Let the database's ON DELETE CASCADE constraints remove child rows.
    await db.execute(
        delete(Event)
        .where(Event.id == event_id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    try:
        await delete_asset_keys(asset_keys)
    except Exception as exc:
        print(f"Deferred event storage cleanup failed: {exc}")
    return MessageResponse(message="Event and all associated data deleted")
