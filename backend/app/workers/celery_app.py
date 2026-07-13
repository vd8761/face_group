"""
Celery application configuration — uses Upstash Redis as broker and backend.
"""
from celery import Celery
from ..config import get_settings

settings = get_settings()

celery_app = Celery(
    "photogroup",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Retry failed tasks up to 3 times with exponential backoff
    task_max_retries=3,
    task_default_retry_delay=30,
    # Dead-letter: tasks that exceed max retries go to failed state
    task_reject_on_worker_lost=True,
    # Rate limits
    task_annotations={
        "app.workers.tasks.process_photo": {"rate_limit": "30/m"},
    },
    # Result expiry
    result_expires=3600,
)
