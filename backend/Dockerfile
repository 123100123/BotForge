# BotForge backend: one always-on container, one uvicorn worker.
# Build context is backend/ (Render: rootDir backend). Not built locally (no Docker on the dev machine).
FROM python:3.12-slim

# uv is installed from its official image; nothing else is added to the system.
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first (cached layer): runtime group only, exactly as locked. No dev, no dbtest.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-group dbtest --no-install-project

# Application code, migrations and operator scripts (tests are excluded by .dockerignore).
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN useradd --system --uid 10001 --no-create-home botforge && chown -R botforge /app
USER botforge

# Render injects PORT; 8000 is the fallback for a plain `docker run`.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

# Migrate, then serve. --workers 1 is required: agent runs and rate limits live in this process.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
