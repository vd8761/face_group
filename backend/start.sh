#!/bin/bash

PORT=${PORT:-8000}
echo "Starting Celery worker (2 concurrent)..."
celery -A app.workers.celery_app:celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=celery \
    --hostname=worker@%h &

echo "Starting FastAPI on port $PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 120 --limit-max-requests 1000
