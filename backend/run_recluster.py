import asyncio
import uuid
import os
import sys

from app.database import async_session_maker
from app.services.clustering import recluster_event
from app.config import get_settings

async def main():
    settings = get_settings()
    print("AGGLOMERATIVE_DISTANCE_THRESHOLD:", settings.AGGLOMERATIVE_DISTANCE_THRESHOLD)
    
    event_id_str = "65d693c1-bc2f-4e63-b38f-596fca81b631"
    event_id = uuid.UUID(event_id_str)
    
    async with async_session_maker() as db:
        try:
            n_clusters = await recluster_event(event_id, db)
            await db.commit()
            print(f"Success! Found {n_clusters} clusters.")
        except Exception as e:
            print(f"Error: {e}")
            await db.rollback()

if __name__ == "__main__":
    asyncio.run(main())
