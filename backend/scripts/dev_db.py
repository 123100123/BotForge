"""Persistent local development Postgres (DEVELOPMENT TOOL; never used in production).

Usage (from backend/):
    uv sync --group dbtest            # once: installs pgserver, a pip-installable Postgres
    uv run python scripts/dev_db.py start     # start (create on first use), migrate, print DATABASE_URL
    uv run python scripts/dev_db.py status    # running or not, and the DATABASE_URL
    uv run python scripts/dev_db.py stop      # stop the server; the data stays in backend/.devdb/

The data directory is backend/.devdb/ (git-ignored). It is separate from the throw-away database that
``pytest`` starts in a temporary directory, so the two never collide. The server listens on 127.0.0.1
on a free port chosen at start, so the port (and DATABASE_URL) can change between starts; ``status``
always prints the current one. There is no password: the server accepts only local connections.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND / ".devdb"

try:
    import pgserver
    from pgserver import _commands
    from pgserver.utils import PostmasterInfo
except ImportError:  # the dbtest group is optional; say how to get it
    pgserver = None  # type: ignore[assignment]


def _require_pgserver() -> None:
    if pgserver is None:
        raise SystemExit("pgserver is not installed. Run: uv sync --group dbtest")


def _info() -> Any:  # a pgserver PostmasterInfo of the running server, or None
    if not (DATA_DIR / "postmaster.pid").exists():
        return None
    info = PostmasterInfo.read_from_pgdata(DATA_DIR)
    return info if info is not None and info.is_running() else None


def running_url() -> str | None:
    """The DATABASE_URL of the running dev database, or None when it is not running."""
    if pgserver is None:
        return None
    info = _info()
    return info.get_uri() if info is not None and info.status == "ready" else None


def _migrate(url: str) -> int:
    env = {**os.environ, "DATABASE_URL": url}
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env)
    return result.returncode


def start() -> int:
    _require_pgserver()
    # cleanup_mode=None: the server keeps running after this script exits; `stop` ends it.
    server = pgserver.get_server(DATA_DIR, cleanup_mode=None)
    url = server.get_uri()
    if _migrate(url) != 0:
        print("alembic upgrade head failed", file=sys.stderr)
        return 1
    print(f"dev database running, data in {DATA_DIR}")
    print(f"DATABASE_URL={url}")
    print(f"PowerShell:  $env:DATABASE_URL = '{url}'")
    return 0


def stop() -> int:
    _require_pgserver()
    if _info() is None:
        print("dev database is not running")
        return 0
    _commands.pg_ctl(["-w", "-m", "fast", "stop"], pgdata=DATA_DIR)
    print("dev database stopped")
    return 0


def status() -> int:
    _require_pgserver()
    url = running_url()
    if url is None:
        print("dev database is not running (start it with: uv run python scripts/dev_db.py start)")
        return 1
    print("dev database is running")
    print(f"DATABASE_URL={url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["start", "stop", "status"])
    args = parser.parse_args()
    return {"start": start, "stop": stop, "status": status}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
