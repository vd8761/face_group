#!/bin/bash

# Start FastAPI server in the foreground
# Render expects the web service to listen on port 10000 by default (or respects the PORT env var)
PORT=${PORT:-8000}
echo "Starting FastAPI on port $PORT..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 120 --limit-max-requests 1000
