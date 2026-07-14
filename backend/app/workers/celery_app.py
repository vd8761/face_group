"""
Celery application configuration — uses Upstash Redis as broker and backend.
"""
from celery import Celery
import ssl
from ..config import get_settings

settings = get_settings()

celery_app = Celery(
    "photogroup",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

# Configure SSL for Upstash rediss://
ssl_conf = {"ssl_cert_reqs": ssl.CERT_NONE} if settings.REDIS_URL and settings.REDIS_URL.startswith("rediss://") else None

celery_app.conf.update(
    broker_use_ssl=ssl_conf,
    redis_backend_use_ssl=ssl_conf,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    # On 4 GB / 2 CPU Pro instance: prefetch 2 so both CPU cores stay busy
    worker_prefetch_multiplier=2,
    # How many tasks a single worker process executes in parallel
    worker_concurrency=2,
    # Kill a single task that runs longer than 5 minutes (stuck / hung)
    task_time_limit=300,
    task_soft_time_limit=240,
    task_max_retries=3,
    task_default_retry_delay=15,     # Faster retry (was 30s)
    task_reject_on_worker_lost=True,
    # Rate limit raised for Pro instance (was 30/m = glacially slow for 4K photos)
    task_annotations={
        "app.workers.tasks.process_photo": {"rate_limit": "120/m"},
    },
    # Result expiry
    result_expires=3600,
)
