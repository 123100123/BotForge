"""PreToolUse(Agent) guard: keeps model routing owned by role definitions.

- Named conductor role + explicit `model`  -> deny (the invocation would override the role's tier).
- Ad-hoc agent (no named role) without `model` -> deny (it would inherit the expensive main-session model).
- Anything else -> allow, and reset the main session's inline-edit counter (a delegation happened).

Escape hatches: CONDUCTOR_GUARD=off disables the guard; CONDUCTOR_ALLOW_INHERIT is a comma-separated
list of extra agent types allowed to run without a model (built-ins that pin their own model).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conductor_common import ROLES, emit, in_subagent, load_state, read_event, save_state  # noqa: E402

SELF_PINNED_BUILTINS = {"claude-code-guide", "statusline-setup"}


def deny(reason: str) -> None:
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def main() -> int:
    if os.environ.get("CONDUCTOR_GUARD", "").lower() == "off":
        return 0
    event = read_event()
    if event.get("tool_name") not in ("Agent", "Task") or in_subagent(event):
        return 0

    tool_input = event.get("tool_input") or {}
    agent_type = (tool_input.get("subagent_type") or "").strip()
    model = (tool_input.get("model") or "").strip()
    allowed_inherit = SELF_PINNED_BUILTINS | {
        a.strip() for a in os.environ.get("CONDUCTOR_ALLOW_INHERIT", "").split(",") if a.strip()
    }

    if agent_type in ROLES and model:
        deny(
            f"conductor: '{agent_type}' is a named role that owns its model and effort in its "
            "agent definition. Re-invoke it WITHOUT the `model` argument."
        )
        return 0

    if agent_type not in ROLES and agent_type not in allowed_inherit and not model:
        deny(
            f"conductor: ad-hoc agent '{agent_type or '(default)'}' has no `model`, so it would inherit "
            "the main-session (frontier) model. Use a named role (scout, mech-executor, executor, "
            "senior-executor, security-executor, integrator, verifier) or pass an explicit cheap "
            "`model` such as 'sonnet'."
        )
        return 0

    session_id = str(event.get("session_id") or "")
    if session_id:
        state = load_state(session_id)
        state["inline_edits"] = 0
        state["delegations"] = int(state.get("delegations", 0)) + 1
        save_state(session_id, state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
