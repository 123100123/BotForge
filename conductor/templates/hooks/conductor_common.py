"""Shared helpers for conductor hooks. Standard library only; every hook fails open."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROLES = frozenset(
    {
        "scout",
        "Explore",
        "mech-executor",
        "executor",
        "senior-executor",
        "security-executor",
        "integrator",
        "verifier",
    }
)


def conductor_home() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "conductor"


def read_event() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def in_subagent(event: dict) -> bool:
    return bool(event.get("agent_id"))


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def state_file(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    return conductor_home() / "state" / f"{safe}.json"


def load_state(session_id: str) -> dict:
    try:
        return json.loads(state_file(session_id).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(session_id: str, state: dict) -> None:
    try:
        path = state_file(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass
