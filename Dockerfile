# Mediastack v4 — Docker image
# Mount docker.sock and data directories at the SAME absolute path as the host.
# See docker-compose.option-b.yml for the correct volume mount convention.

FROM python:3.12-slim AS builder

# Install Node.js for frontend build
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build Vue frontend
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm ci --quiet
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# ── Runtime image ──────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates rsync sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy application
COPY backend/ ./backend/
COPY catalog/ ./catalog/
COPY --from=builder /app/frontend/dist/ ./backend/static/
COPY docker-entrypoint.sh /entrypoint.sh

# Runtime environment
ENV PYTHONPATH=/app
ENV MS_DATA_DIR=/srv/mediastack/data
ENV MS_CONFIG_ROOT=/srv/mediastack/config
ENV MS_HOST_DATA_DIR=/srv/mediastack/data
ENV MS_HOST_CONFIG_DIR=/srv/mediastack/config
ENV MS_HOST_ENV_FILE=/srv/mediastack/.env

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8080/api/ping || exit 1

ENTRYPOINT ["/entrypoint.sh"]
