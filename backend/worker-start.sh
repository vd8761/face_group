#!/bin/sh
set -eu

# A worker can become healthy before the web container during a rolling
# deploy. Run the same advisory-locked idempotent expansion first.
python -m app.migrate

# Consume the v2 queue for new schema-aware work and the default queue to drain
# tasks published by the previous release.
exec celery -A app.workers.celery_app worker \
  --loglevel=info \
  --concurrency=1 \
  --queues=face-v2,celery
