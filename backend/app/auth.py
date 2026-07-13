"""
JWT authentication, password hashing, and tenant/role enforcement.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .config import get_settings
from .database import get_db
from .models import User, UserRole, Tenant, Subscription, SubscriptionStatus

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


# ─────────────────────────────────────────────────────────────────────────────
# Password helpers
# ─────────────────────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─────────────────────────────────────────────────────────────────────────────
# JWT creation
# ─────────────────────────────────────────────────────────────────────────────
def create_access_token(
    user_id: uuid.UUID,
    tenant_id: Optional[uuid.UUID],
    role: UserRole,
    expires_delta: Optional[timedelta] = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id) if tenant_id else None,
        "role": role.value,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ─────────────────────────────────────────────────────────────────────────────
# JWT decoding + current user dependency
# ─────────────────────────────────────────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Role-based access control dependencies
# ─────────────────────────────────────────────────────────────────────────────
def require_role(*roles: UserRole):
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in roles]}",
            )
        return current_user
    return dependency


require_super_admin = require_role(UserRole.super_admin)
require_organizer   = require_role(UserRole.organizer, UserRole.super_admin)
require_attendee    = require_role(UserRole.attendee, UserRole.organizer, UserRole.super_admin)


# ─────────────────────────────────────────────────────────────────────────────
# Tenant-scoped user resolution
# ─────────────────────────────────────────────────────────────────────────────
async def get_current_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Returns the tenant for the current organizer user."""
    if current_user.role == UserRole.super_admin:
        raise HTTPException(status_code=400, detail="Super admin has no tenant scope.")
    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id, Tenant.is_active == True)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found or inactive.")
    return tenant


async def check_subscription_active(tenant: Tenant, db: AsyncSession) -> Subscription:
    """Raises 403 if tenant subscription is suspended or cancelled."""
    result = await db.execute(select(Subscription).where(Subscription.tenant_id == tenant.id))
    sub = result.scalar_one_or_none()
    if not sub or sub.status != SubscriptionStatus.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Subscription inactive. Please contact the platform admin.",
        )
    return sub
