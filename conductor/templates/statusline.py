"""conductor status line: model · session cost · context use · subagents delegated this session.

Reads Claude Code's status-line JSON on stdin. Every field is optional, so the line degrades
gracefully when a field is missing or renamed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def dig(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def delegations(session_id: str) -> int | None:
    if not session_id:
        return None
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    try:
        state = json.loads((Path(base) / "conductor" / "state" / f"{safe}.json").read_text(encoding="utf-8"))
        return int(state.get("delegations", 0))
    except Exception:
        return 0


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    parts = [str(dig(data, "model", "display_name") or dig(data, "model", "id") or "claude")]

    cost = dig(data, "cost", "total_cost_usd")
    if isinstance(cost, (int, float)):
        parts.append(f"${cost:.2f}")

    ctx = dig(data, "context_window", "used_percentage")
    if isinstance(ctx, (int, float)):
        parts.append(f"ctx {ctx:.0f}%")

    count = delegations(str(data.get("session_id") or ""))
    if count is not None:
        parts.append(f"delegated {count}")

    sys.stdout.write(" · ".join(parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stdout.write("claude")
