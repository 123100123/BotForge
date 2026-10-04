"""SubagentStop ledger: appends one JSON line per finished subagent to ~/.claude/conductor/ledger.jsonl.

Each line records the role, the model(s) it actually ran on, and token usage summed from the subagent's
transcript when the event provides one. Use it to audit routing (is the frontier model's share small?)
and to tune role tiers. Never blocks; fails open.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conductor_common import conductor_home, read_event  # noqa: E402

USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def summarize_transcript(path: str) -> dict:
    usage_by_model: dict[str, dict[str, int]] = {}
    seen_ids: set[str] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                msg_id = message.get("id")
                if msg_id:
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)
                model = str(message.get("model") or "unknown")
                bucket = usage_by_model.setdefault(model, {k: 0 for k in USAGE_KEYS})
                for key in USAGE_KEYS:
                    value = usage.get(key)
                    if isinstance(value, int):
                        bucket[key] += value
    except Exception:
        return {}
    return usage_by_model


def main() -> int:
    event = read_event()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": event.get("session_id"),
        "agent_type": event.get("agent_type"),
        "agent_id": event.get("agent_id"),
        "cwd": event.get("cwd"),
    }
    transcript = event.get("agent_transcript_path")
    if transcript:
        entry["usage_by_model"] = summarize_transcript(str(transcript))

    ledger = conductor_home() / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
