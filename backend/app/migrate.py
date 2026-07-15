"""Idempotent schema expansion entrypoint shared by web and worker deploys."""
import asyncio

# Register every ORM table before Base.metadata.create_all().
from . import models  # noqa: F401
from .database import init_db


if __name__ == "__main__":
    asyncio.run(init_db())
