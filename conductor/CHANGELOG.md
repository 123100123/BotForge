# Changelog

## v2.0.0 — 2026-10-04

conductor is a modernized fork of pilotfish v1.1.5 (MIT, Nanako0129) for the Fable 5.1 / Opus 5.5 / Sonnet 5.5 generation. Fable 5.1 plans and orchestrates only; Opus and Sonnet execute at `medium` to `max` effort. Not yet run live; covered by 22 unit tests.

### Added
- Triage policy: every task is classed S / M / L / XL before any work. S is done inline; XL proposes the `execute-plan` workflow to the user.
- Routing by risk, not size, with a bounded escalation ladder (`mech-executor` -> `executor` -> `senior-executor`; security starts on `security-executor`).
- Two roles: `senior-executor` (Opus, high) and `integrator` (Sonnet, high). Roles go from 6 to 8.
- `INCONCLUSIVE` verifier verdict alongside CONFIRMED and REFUTED.
- Three fail-open hooks: `agent_guard.py` (PreToolUse on `Agent`), `inline_edit_nudge.py` (PostToolUse on edits), `subagent_ledger.py` (SubagentStop, writes `ledger.jsonl`). Env vars: `CONDUCTOR_GUARD=off`, `CONDUCTOR_ALLOW_INHERIT`, `CONDUCTOR_NUDGE_AFTER`.
- Status line: model, session cost, context use, delegations this session.
- `execute-plan` workflow: parallel worktree execution, one escalation per failed unit, integrate, verify.
- `modelSettings` per-model effort defaults and `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` in the settings merge.
- Installer: Python preflight, Pro/API guidance (`model: "opus"`), warnings for `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_EFFORT_LEVEL`, `availableModels`, and `maxEffortLevel`, backups, and an offer to supersede a pilotfish block.
- Test suite: 22 unit tests for the policy contract and hook behavior.

### Changed
- `executor` moves from Opus to Sonnet (high). `mech-executor` goes from high to medium. `verifier` goes from high to medium (still Opus).
- Policy marker is now `conductor:begin/end`; policy prose stays free of model names.

### Removed
- The claimed extra Sonnet-only weekly bucket (unconfirmed).
- The "96% of all-Fable performance at 46% of the cost" figure (not found in official docs).
- The Chinese README and research translation.

### Unchanged
- `scout` and `Explore` (Sonnet, medium, read-only allowlist), `security-executor` (Opus, max), `best` as the main model with `fallbackModel: ["opus","sonnet"]`, no role bound to Fable.
