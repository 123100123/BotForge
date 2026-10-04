# BotForge

- **Start here:** the "Current Status" section at the top of `IMPLEMENTATION_ROADMAP.md` says what is
  done, what is unproven, and what to do next, in order. Update it at the end of every working session.
- `IMPLEMENTATION_ROADMAP.md` is the source of truth. Read it before any work. Keep it updated:
  architectural or scope changes need a Decision Log entry and a Change Log line, then code.
- Contract files (WP0) are frozen: `backend/app/botspec/`, `backend/app/runtime/{contracts,store,callbacks}.py`,
  `backend/app/testing/scenario.py`, `backend/app/agent/requirements.py`, `examples/`.
  Changing them requires a Decision Log entry and a check of every dependent package.
- Stay inside your work package's allowed paths (roadmap: "Agent Ownership / Work Packages").
- `conductor/` is the Claude Code orchestration config (role agents, hooks, workflow), not product
  code. Do not modify it as part of product work. On a new machine, install it globally by following
  `conductor/install/AGENT-INSTALL.md`.
- Load the `claude-api` skill before writing any LLM code.

## Commands (run from `backend/`)

- Install: `uv sync`
- Tests: `uv run pytest -q` (contracts only: `uv run pytest tests/unit/botspec -q`)
- Database tests: `uv sync --group dbtest` once; then `uv run pytest -q` starts a temporary Postgres itself (or set `TEST_DATABASE_URL`); with neither, database tests skip.
- Lint: `uv run ruff check app tests scripts alembic`
- Without uv: `python -m venv .venv`, install `pydantic pytest pytest-asyncio ruff` and `-e .`,
  then `.venv/bin/python -m pytest -q` (Windows: `.venv/Scripts/python`).

Local run, dev database, smoke test and deployment steps: see `README.md`.

Python 3.12, type hints throughout, async I/O, ruff clean. Automated tests never call the real
LLM or the real Telegram API.
