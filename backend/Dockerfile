# syntax=docker/dockerfile:1.6
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgomp1 \
        curl \
        ca-certificates \
        tini \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY cara ./cara
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

# Default to 1 worker; overridable via UVICORN_WORKERS env (compose sets 2).
ENV UVICORN_WORKERS=1

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=90s \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn cara.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]
