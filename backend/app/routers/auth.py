"""
Auth router — login + attendee join.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import User, UserRole, Tenant, ConsentRecord
from ..auth import hash_password, verify_password, create_access_token
from ..schemas import LoginRequest, TokenResponse, AttendeeJoinRequest, MessageResponse
from ..models import Event

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")

    token = create_access_token(user.id, user.tenant_id, user.role)
    return TokenResponse(
        access_token=token,
        role=user.role.value,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


@router.post("/attendee-join", response_model=TokenResponse)
async def attendee_join(body: AttendeeJoinRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Attendee self-registers using an event access code."""
    # Validate access code
    event_result = await db.execute(
        select(Event).where(Event.access_code == body.access_code, Event.is_active == True)
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Invalid or expired event access code")

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == body.email))
    user = existing.scalar_one_or_none()

    if not user:
        user = User(
            email=body.email,
            password_hash=hash_password(body.password),
            role=UserRole.attendee,
            full_name=body.full_name,
            tenant_id=event.tenant_id,
        )
        db.add(user)
        await db.flush()

    token = create_access_token(user.id, event.tenant_id, user.role)
    return TokenResponse(
        access_token=token,
        role=user.role.value,
        tenant_id=event.tenant_id,
        user_id=user.id,
    )
