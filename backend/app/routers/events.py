"""
Events router — organizer creates/manages events, generates access codes.
"""
import uuid
import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import Event, User, Photo, FaceCluster, Subscription, SubscriptionStatus
from ..auth import require_organizer, get_current_user, get_current_tenant
from ..schemas import EventCreate, EventResponse, EventUpdate, MessageResponse

router = APIRouter(prefix="/events", tags=["Events"])


def generate_access_code(length: int = 8) -> str:
    """Generate a short alphanumeric access code for attendees."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


async def _event_response(event: Event, db: AsyncSession) -> EventResponse:
    photo_count = (await db.execute(
        select(func.count(Photo.id)).where(Photo.event_id == event.id)
    )).scalar()
    processed_count = (await db.execute(
        select(func.count(Photo.id)).where(Photo.event_id == event.id, Photo.status == "done")
    )).scalar()
    cluster_count = (await db.execute(
        select(func.count(FaceCluster.id)).where(FaceCluster.event_id == event.id)
    )).scalar()
    return EventResponse(
        **{k: getattr(event, k) for k in ["id", "name", "description", "access_code", "is_active", "created_at"]},
        photo_count=photo_count,
        processed_count=processed_count,
        cluster_count=cluster_count,
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
    await db.delete(event)
    return MessageResponse(message="Event and all associated data deleted")
