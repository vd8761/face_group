FROM python:3.11-slim

# System dependencies for OpenCV + InsightFace (pre-built wheels — no C++ compilation)
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (all have pre-built wheels — no compilation needed)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# NOTE: Do NOT pre-download InsightFace models here.
# buffalo_l (500MB) causes OOM at runtime on the 512MB free tier.
# We use buffalo_sc (~85MB) which lazy-downloads on first request.

COPY . .

COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 8000

CMD ["/start.sh"]
