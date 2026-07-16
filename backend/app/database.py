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
        # Web and worker containers may start together during a Blueprint
        # rollout. Serialize the idempotent migration transaction across both.
        await conn.execute(text("SELECT pg_advisory_xact_lock(5784688345334636884)"))
        await conn.run_sync(Base.metadata.create_all)

        # ── Safe column migrations ──────────────────────────────────────────
        # These use ADD COLUMN IF NOT EXISTS so they are idempotent — safe to
        # run on every startup even if the column already exists.

        migrations = [
            # SQLAlchemy create_all() does not extend existing PostgreSQL enums.
            "ALTER TYPE processing_batch_source ADD VALUE IF NOT EXISTS 'reprocess'",

            # photos table
            "ALTER TABLE photos ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",

            # Durable batch recovery metadata.
            "ALTER TABLE processing_batches ADD COLUMN IF NOT EXISTS expected_images INTEGER",
            "ALTER TABLE processing_batches ADD COLUMN IF NOT EXISTS finalize_dispatched_at TIMESTAMPTZ",
            "ALTER TABLE processing_batches ADD COLUMN IF NOT EXISTS finalization_error TEXT",
            "ALTER TABLE processing_batch_items ADD COLUMN IF NOT EXISTS dispatch_attempted_at TIMESTAMPTZ",

            # Face task idempotency, exact pipeline identity, and durable
            # organizer grouping corrections.
            "ALTER TABLE face_detections ADD COLUMN IF NOT EXISTS face_key VARCHAR(500)",
            "ALTER TABLE face_detections ADD COLUMN IF NOT EXISTS pipeline_version VARCHAR(100)",
            "ALTER TABLE face_detections ADD COLUMN IF NOT EXISTS face_index INTEGER",
            "ALTER TABLE face_detections ADD COLUMN IF NOT EXISTS manual_group_id UUID",
            "UPDATE face_detections SET pipeline_version = 'legacy-unversioned' "
            "WHERE pipeline_version IS NULL",
            "ALTER TABLE face_detections ALTER COLUMN pipeline_version "
            "SET DEFAULT 'legacy-unversioned'",
            "ALTER TABLE face_detections ALTER COLUMN pipeline_version SET NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_face_detections_photo_pipeline_face "
            "ON face_detections (photo_id, pipeline_version, face_index)",
            "CREATE INDEX IF NOT EXISTS ix_face_detections_manual_group_id "
            "ON face_detections (manual_group_id)",

            # A matching byte length does not prove embeddings came from the
            # same recognition model and detector configuration.
            "ALTER TABLE face_clusters ADD COLUMN IF NOT EXISTS pipeline_version VARCHAR(100)",
            "UPDATE face_clusters SET pipeline_version = 'legacy-unversioned' "
            "WHERE pipeline_version IS NULL",
            "ALTER TABLE face_clusters ALTER COLUMN pipeline_version "
            "SET DEFAULT 'legacy-unversioned'",
            "ALTER TABLE face_clusters ALTER COLUMN pipeline_version SET NOT NULL",
            "CREATE INDEX IF NOT EXISTS ix_face_clusters_event_pipeline "
            "ON face_clusters (event_id, pipeline_version)",
            "ALTER TABLE selfie_scans ADD COLUMN IF NOT EXISTS pipeline_version VARCHAR(100)",
            "UPDATE selfie_scans SET pipeline_version = 'legacy-unversioned' "
            "WHERE pipeline_version IS NULL",
            "ALTER TABLE selfie_scans ALTER COLUMN pipeline_version "
            "SET DEFAULT 'legacy-unversioned'",
            "ALTER TABLE selfie_scans ALTER COLUMN pipeline_version SET NOT NULL",
        ]

        for sql in migrations:
            await conn.execute(text(sql))

        print("DB schema migrations applied")
