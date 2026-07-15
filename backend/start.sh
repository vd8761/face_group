#!/bin/bash

PORT=${PORT:-8000}

echo "Starting FastAPI on port $PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 120 --limit-max-requests 1000
