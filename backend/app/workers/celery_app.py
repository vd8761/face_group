"""
Celery application configuration — uses Upstash Redis as broker and backend.
"""
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
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
    # The durable dispatcher publishes to this queue explicitly. Making it the
    # default means a bare `celery worker` (no -Q flag) still consumes it and
    # unrouted legacy publishes land where workers are listening.
    task_default_queue="face-v2",
    broker_connection_timeout=3.0,
    broker_connection_retry=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    # The local 4 GB GPU can safely hold one Buffalo-L worker at a time.
    worker_prefetch_multiplier=1,
    worker_concurrency=1,
    # Large originals can need several tiled CPU passes. Keep a hard guard
    # without failing healthy 100 MB photos on slower workers.
    task_time_limit=900,
    task_soft_time_limit=840,
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


@worker_process_init.connect
def _start_worker_resource_sampler(**_kwargs):
    from ..services.telemetry import start_resource_sampler

    start_resource_sampler("worker")


@worker_process_shutdown.connect
def _stop_worker_resource_sampler(**_kwargs):
    from ..services.telemetry import stop_resource_sampler

    stop_resource_sampler()
