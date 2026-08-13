# QueryMind backend -- FastAPI app (backend.app.api.main:app) + the
# LangGraph agent, guardrail, and eval code it imports.
#
# This image does NOT bundle Postgres/pgvector -- it expects DATABASE_URL /
# READONLY_DATABASE_URL to point at an external instance (docker-compose's
# `postgres` service locally, a managed Postgres add-on in production; see
# DEPLOYMENT.md). Keeping the app and the database as separate containers/
# services matches how Render/Railway actually deploy this: one web service
# talking to one managed Postgres instance, not a single fat container.
#
# Build:  docker build -t querymind-backend .
# Run:    docker run --env-file .env -p 8000:8000 querymind-backend

FROM python:3.11-slim AS base

# psycopg2-binary avoids needing libpq-dev at build time, but pgvector's
# Python client and a couple of Phase 1 deps (scipy/scikit-learn) still
# need a C toolchain for their wheels on some platforms; build-essential
# keeps that from being a surprise on an architecture without prebuilt
# wheels, then gets removed from the final layer to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi==0.115.0 "uvicorn[standard]==0.30.6"

# App code. .dockerignore keeps frontend/, eval/logs, eval/reports,
# __pycache__, and local env files out of the image.
COPY backend/ backend/
COPY data/schema_docs/ data/schema_docs/
COPY run_agent.py .

# Non-root runtime user.
RUN useradd --create-home --uid 1000 querymind \
    && chown -R querymind:querymind /app
USER querymind

ENV PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Shell form so ${PORT} expands -- lets Railway/Render inject their own
# port via the PORT env var without a Dockerfile change.
CMD uvicorn backend.app.api.main:app --host 0.0.0.0 --port ${PORT}
