"""Transaction-scoped serialization for face-identity mutations per event."""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_event_face_mutation(event_id: uuid.UUID, db: AsyncSession) -> None:
    """Serialize ingestion, organizer corrections, and final regrouping.

    PostgreSQL advisory transaction locks are re-entrant within the same
    transaction and let different events continue processing in parallel.
    Other databases used by unit tests simply retain their normal semantics.
    """
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    lock_key = event_id.int & ((1 << 63) - 1)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": lock_key},
    )
