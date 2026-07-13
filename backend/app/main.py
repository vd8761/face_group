"""
FastAPI application entry point.
Assembles all routers, middleware, CORS, startup seeding, and health check.
"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .config import get_settings
from .database import init_db, AsyncSessionLocal
from .models import User, UserRole, AuditLog
from .auth import hash_password
from .routers import auth, admin, events, photos, faces, downloads, public

settings = get_settings()


# ─────────────────────────────────────────────────────────────────────────────
# Startup: seed super admin
# ─────────────────────────────────────────────────────────────────────────────
async def seed_super_admin():
    """Create the super admin user on first startup if not exists."""
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.email == settings.SUPER_ADMIN_EMAIL)
        )
        if result.scalar_one_or_none():
            return  # Already exists

        admin = User(
            email=settings.SUPER_ADMIN_EMAIL,
            password_hash=hash_password(settings.SUPER_ADMIN_PASSWORD),
            role=UserRole.super_admin,
            full_name="Super Admin",
            is_active=True,
            tenant_id=None,
        )
        db.add(admin)
        await db.commit()
        print(f"✅ Super admin seeded: {settings.SUPER_ADMIN_EMAIL}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_super_admin()
    yield
    # Shutdown (cleanup if needed)


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="PhotoGroup API",
    description="AI-powered face grouping for event photos",
    version=settings.APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router,      prefix="/api")
app.include_router(admin.router,     prefix="/api")
app.include_router(events.router,    prefix="/api")
app.include_router(photos.router,    prefix="/api")
app.include_router(faces.router,     prefix="/api")
app.include_router(downloads.router, prefix="/api")
app.include_router(public.router,    prefix="/api")


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}
