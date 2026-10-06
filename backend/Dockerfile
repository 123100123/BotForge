# BotForge backend: one always-on container, one uvicorn worker.
# Build context is backend/ (Render: rootDir backend, or deploy/docker-compose.yml).
FROM python:3.12-slim

# Optional build args, empty by default (plain behaviour):
#   PIP_INDEX_URL   a PyPI mirror for pip and uv (networks where pypi.org is slow or blocked)
#   UV_EXTRA_GROUPS one extra dependency group, e.g. "headless" for a local build that can run
#                   LLM_PROVIDER=claude_cli. Never set it for production.
ARG PIP_INDEX_URL=
ARG UV_EXTRA_GROUPS=

# uv comes from PyPI (ghcr.io is blocked in some regions). Pinned: the 0.8 series wrote uv.lock.
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} uv==0.12.23

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first (cached layer): runtime group only, exactly as locked. No dev, no dbtest.
COPY pyproject.toml uv.lock ./
RUN if [ -n "$PIP_INDEX_URL" ]; then export UV_DEFAULT_INDEX="$PIP_INDEX_URL"; fi; \
    uv sync --frozen --no-dev --no-group dbtest ${UV_EXTRA_GROUPS:+--group "$UV_EXTRA_GROUPS"} --no-install-project

# Application code, migrations and operator scripts (tests are excluded by .dockerignore).
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# /data/uploads is the UPLOAD_DIR of deploy/docker-compose.yml. Created here, owned by the app user,
# so a fresh named volume mounted on it starts out writable (Docker copies the ownership in).
RUN useradd --system --uid 10001 --no-create-home botforge \
    && mkdir -p /data/uploads \
    && chown -R botforge /app /data/uploads
USER botforge

# Render injects PORT; 8000 is the fallback for a plain `docker run`.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)" || exit 1

# Migrate, then serve. --workers 1 is required: agent runs and rate limits live in this process.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
