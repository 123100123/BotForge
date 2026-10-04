# BotForge

- `IMPLEMENTATION_ROADMAP.md` is the source of truth. Read it before any work. Keep it updated:
  architectural or scope changes need a Decision Log entry and a Change Log line, then code.
- Contract files (WP0) are frozen: `backend/app/botspec/`, `backend/app/runtime/{contracts,store,callbacks}.py`,
  `backend/app/testing/scenario.py`, `backend/app/agent/requirements.py`, `examples/`.
  Changing them requires a Decision Log entry and a check of every dependent package.
- Stay inside your work package's allowed paths (roadmap: "Agent Ownership / Work Packages").
- `conductor/` is unrelated tooling. Do not modify it.
- Load the `claude-api` skill before writing any LLM code.

## Commands (run from `backend/`)

- Install: `uv sync`
- Tests: `uv run pytest -q` (contracts only: `uv run pytest tests/unit/botspec -q`)
- Lint: `uv run ruff check app tests`
- Without uv: `python -m venv .venv`, install `pydantic pytest pytest-asyncio ruff` and `-e .`,
  then `.venv/Scripts/python -m pytest -q`.

Python 3.12, type hints throughout, async I/O, ruff clean. Automated tests never call the real
LLM or the real Telegram API.
