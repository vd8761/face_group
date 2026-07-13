"""
SQLAlchemy async engine and session factory for Neon DB (PostgreSQL).
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Alias used by background tasks that need their own independent session
async_session_maker = AsyncSessionLocal


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables and run safe schema migrations."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # ── Safe column migrations ──────────────────────────────────────────
        # These use ADD COLUMN IF NOT EXISTS so they are idempotent — safe to
        # run on every startup even if the column already exists.

        migrations = [
            # photos table
            "ALTER TABLE photos ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",

            # face_detections table — face_key was added after initial deploy
            "ALTER TABLE face_detections ADD COLUMN IF NOT EXISTS face_key VARCHAR(500)",
        ]

        for sql in migrations:
            await conn.execute(text(sql))

        print("✅ DB schema migrations applied")
