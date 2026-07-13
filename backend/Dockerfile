FROM python:3.11-slim

# System dependencies for OpenCV + InsightFace
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download InsightFace buffalo_l model at build time
# so first request does not trigger a 500MB download
# NOTE: Requires a build instance with enough RAM (at least 4GB for safe compilation)
RUN python -c "\
import os; \
os.environ['INSIGHTFACE_HOME'] = '/tmp/insightface_cache'; \
from insightface.app import FaceAnalysis; \
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
app.prepare(ctx_id=0, det_size=(640,640))"

COPY . .

COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 8000

CMD ["/start.sh"]
