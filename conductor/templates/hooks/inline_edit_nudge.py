"""PostToolUse(Edit|Write|MultiEdit|NotebookEdit) nudge for the main session.

Counts consecutive inline edits made by the main session since its last delegation. At the threshold
(CONDUCTOR_NUDGE_AFTER, default 4) and every threshold-multiple after, it injects a non-blocking
reminder to route execution to a role agent. It never blocks a tool call.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conductor_common import emit, in_subagent, load_state, read_event, save_state  # noqa: E402


def threshold() -> int:
    try:
        return max(1, int(os.environ.get("CONDUCTOR_NUDGE_AFTER", "4")))
    except ValueError:
        return 4


def main() -> int:
    event = read_event()
    if in_subagent(event):
        return 0
    session_id = str(event.get("session_id") or "")
    if not session_id:
        return 0

    state = load_state(session_id)
    count = int(state.get("inline_edits", 0)) + 1
    state["inline_edits"] = count
    save_state(session_id, state)

    limit = threshold()
    if count % limit == 0:
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"conductor: the main session has made {count} inline edits since its last "
                        "delegation. Unless this is S-class finishing work, hand the remaining execution "
                        "to a role agent (mech-executor / executor) with a one-shot spec."
                    ),
                }
            }
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
