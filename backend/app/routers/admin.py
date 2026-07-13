"""
Super Admin router — organization management, subscription control, system stats, audit logs.
All endpoints require super_admin role.
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from ..database import get_db
from ..models import (
    Tenant, User, UserRole, Subscription, SubscriptionPlan, SubscriptionStatus,
    Event, Photo, AuditLog
)
from ..auth import hash_password, require_super_admin
from ..schemas import (
    TenantCreate, TenantResponse, TenantDetailResponse, TenantUpdate,
    SubscriptionResponse, SubscriptionUpdate,
    SystemStatsResponse, AuditLogResponse, PaginatedAuditLogs, MessageResponse,
)

router = APIRouter(prefix="/admin", tags=["Super Admin"])

PLAN_LIMITS = {
    SubscriptionPlan.starter:    {"max_events": 1,         "max_photos": 1000,  "max_storage_gb": 5.0},
    SubscriptionPlan.pro:        {"max_events": 5,         "max_photos": 5000,  "max_storage_gb": 50.0},
    SubscriptionPlan.enterprise: {"max_events": 999,       "max_photos": 20000, "max_storage_gb": 500.0},
}


# ─────────────────────────────────────────────────────────────────────────────
# System Stats
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/stats", response_model=SystemStatsResponse)
async def system_stats(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    total_tenants = (await db.execute(select(func.count(Tenant.id)))).scalar()
    active_tenants = (await db.execute(select(func.count(Tenant.id)).where(Tenant.is_active == True))).scalar()
    total_events = (await db.execute(select(func.count(Event.id)))).scalar()
    total_photos = (await db.execute(select(func.count(Photo.id)))).scalar()
    storage_sum = (await db.execute(select(func.sum(Subscription.current_storage_bytes)))).scalar() or 0

    return SystemStatsResponse(
        total_tenants=total_tenants,
        active_tenants=active_tenants,
        total_events=total_events,
        total_photos=total_photos,
        total_storage_bytes=storage_sum,
        processing_queue_depth=0,  # TODO: query Celery inspect
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tenant / Organisation Management
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/tenants", response_model=list[TenantDetailResponse])
async def list_tenants(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 50,
):
    result = await db.execute(select(Tenant).offset(skip).limit(limit))
    tenants = result.scalars().all()
    out = []
    for t in tenants:
        sub_result = await db.execute(select(Subscription).where(Subscription.tenant_id == t.id))
        sub = sub_result.scalar_one_or_none()
        event_count = (await db.execute(select(func.count(Event.id)).where(Event.tenant_id == t.id))).scalar()
        photo_count = (await db.execute(select(func.count(Photo.id)).where(Photo.tenant_id == t.id))).scalar()
        storage_gb = round((sub.current_storage_bytes / (1024**3)) if sub else 0, 3)
        out.append(TenantDetailResponse(
            **{k: getattr(t, k) for k in ["id", "name", "slug", "is_active", "created_at"]},
            subscription=SubscriptionResponse.model_validate(sub) if sub else None,
            event_count=event_count,
            photo_count=photo_count,
            storage_used_gb=storage_gb,
        ))
    return out


@router.post("/tenants", response_model=TenantDetailResponse, status_code=201)
async def create_tenant(
    body: TenantCreate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == body.organizer_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Slug from name
    slug = body.name.lower().replace(" ", "-")[:50] + "-" + str(uuid.uuid4())[:8]

    tenant = Tenant(name=body.name, slug=slug)
    db.add(tenant)
    await db.flush()

    limits = PLAN_LIMITS[body.plan]
    sub = Subscription(
        tenant_id=tenant.id,
        plan=body.plan,
        max_events_per_month=limits["max_events"],
        max_photos_per_event=limits["max_photos"],
        max_storage_gb=limits["max_storage_gb"],
    )
    db.add(sub)

    organizer = User(
        tenant_id=tenant.id,
        email=body.organizer_email,
        password_hash=hash_password(body.organizer_password),
        role=UserRole.organizer,
        full_name=body.organizer_name,
    )
    db.add(organizer)
    await db.flush()

    return TenantDetailResponse(
        **{k: getattr(tenant, k) for k in ["id", "name", "slug", "is_active", "created_at"]},
        subscription=SubscriptionResponse.model_validate(sub),
        event_count=0,
        photo_count=0,
        storage_used_gb=0.0,
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if body.name is not None:
        tenant.name = body.name
    if body.is_active is not None:
        tenant.is_active = body.is_active
    return TenantResponse.model_validate(tenant)


@router.delete("/tenants/{tenant_id}", response_model=MessageResponse)
async def delete_tenant(
    tenant_id: uuid.UUID,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.delete(tenant)
    return MessageResponse(message="Tenant and all associated data deleted")


# ─────────────────────────────────────────────────────────────────────────────
# Subscription Management
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/tenants/{tenant_id}/subscription", response_model=SubscriptionResponse)
async def update_subscription(
    tenant_id: uuid.UUID,
    body: SubscriptionUpdate,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if body.plan is not None:
        limits = PLAN_LIMITS[body.plan]
        sub.plan = body.plan
        sub.max_events_per_month = limits["max_events"]
        sub.max_photos_per_event = limits["max_photos"]
        sub.max_storage_gb = limits["max_storage_gb"]
    if body.status is not None:
        sub.status = body.status

    return SubscriptionResponse.model_validate(sub)


# ─────────────────────────────────────────────────────────────────────────────
# Audit Logs
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/audit-logs", response_model=PaginatedAuditLogs)
async def get_audit_logs(
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    tenant_id: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_query = select(func.count(AuditLog.id))

    if tenant_id:
        query = query.where(AuditLog.tenant_id == tenant_id)
        count_query = count_query.where(AuditLog.tenant_id == tenant_id)
    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    logs = result.scalars().all()

    return PaginatedAuditLogs(
        logs=[AuditLogResponse.model_validate(l) for l in logs],
        total=total,
        page=page,
        page_size=page_size,
    )
