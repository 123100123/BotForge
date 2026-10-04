# conductor — Agent Install Runbook

You are a Claude Code agent installing **conductor** into the user's global Claude Code configuration from this local checkout. Follow the steps in order.

**Nothing gets written before the user approves the plan in Step 2.**

Use your own file tools (Read/Write/Edit) for every file change; shell snippets are illustrative only. The target is Windows, macOS, or Linux.

## What you are installing

| Target (under the config dir, default `~/.claude/`) | Source in this checkout |
|---|---|
| `agents/` — 8 role agents | `templates/agents/*.md` |
| `CLAUDE.md` — one marker-delimited policy block | `templates/claude-md.orchestration.md` |
| `settings.json` — merged keys | `templates/settings.snippet.json` |
| `conductor/hooks/*.py`, `conductor/statusline.py` | `templates/hooks/`, `templates/statusline.py` |
| `workflows/execute-plan.js` | `templates/workflows/execute-plan.js` |

The config dir is `$CLAUDE_CONFIG_DIR` if set, otherwise `~/.claude` (on Windows, `%USERPROFILE%\.claude`). Call it `CFG` below.

## Updating an existing install

Look for `<!-- conductor vX.Y.Z -->` in `CFG/CLAUDE.md`.
- If it's present, this is an upgrade. Show the user the `CHANGELOG.md` entries newer than the installed version, then run the steps below.
- Unchanged files are skipped. The policy block is replaced in place.
- Settings keys are re-merged by the rules in 3.3.

If a `<!-- pilotfish:begin -->` block exists, conductor supersedes it. Offer to remove that block and pilotfish's agents. Its 6 role names overlap with conductor's, so both sets cannot coexist.

## Step 1 — Preflight (read-only)

Collect these facts and report them:

1. **Python interpreter.** Run `python --version`, then `python3 --version`. Pick the first one that reports Python ≥ 3.9 and resolve its absolute path (`where python` / `command -v python3`). Call it `PY`.
   - Use forward slashes in the path, e.g. `C:/Users/me/AppData/Local/Programs/Python/Python312/python.exe`.
   - If neither command works: the hooks and status line can't be installed. Offer a policy-only install (agents + CLAUDE.md + model settings) and stop if the user declines.
2. **Claude Code version** (`claude --version`, if the command is on PATH). conductor expects ≥ 2.1.284 so that the aliases resolve: `opus` → Opus 5.5, `sonnet` → Sonnet 5.5, `best` → Fable 5.1. If the version is older or unknown, warn the user but continue.
3. **Existing `CFG/settings.json`.** Read it in full. Note these keys if present:
   - `model`, `fallbackModel`, `modelSettings`
   - `effortLevel`, `maxEffortLevel`
   - `availableModels`
   - `env.CLAUDE_CODE_SUBAGENT_MODEL`, `env.CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, `env.CLAUDE_CODE_EFFORT_LEVEL`
   - `statusLine`
   - existing `hooks`
4. **Existing agents.** List `CFG/agents/`. Detect name collisions by each file's frontmatter `name:` field, not by filename. conductor's role names are:
   - `scout`, `Explore`, `mech-executor`, `executor`
   - `senior-executor`, `security-executor`, `integrator`, `verifier`
5. **Plugin agents.** Also check enabled plugins for agents with these names. A plugin agent with the same name shadows ours.
6. **Managed settings.** Check whether managed settings exist. A managed `model`, `availableModels`, or `maxEffortLevel` overrides the user's settings.
7. **The user's plan.** Ask which plan they're on if it isn't already known: Max / Team Premium (Fable is included up to 50% of the weekly limit) or Pro / API (Fable is billed as credits).
   - On Pro/API, recommend `model: "opus"` instead of `"best"`. That makes the main session Opus 5.5 at high effort, with `/model best` as a manual opt-in for hard planning sessions.

## Step 2 — Present the plan and get approval

Show the user a concrete diff-style plan covering:
- every file to be created or replaced
- every settings key to be added or changed (old value → new value)
- every collision found in Step 1 and how you propose to resolve it
- the warnings below

Wait for explicit approval. Apply only what was approved.

Warnings to surface when they apply:
- **`CLAUDE_CODE_SUBAGENT_MODEL` (or `..._FORCE`) is set.** It overrides every role's model, so routing is defeated. Recommend removing it.
- **`CLAUDE_CODE_EFFORT_LEVEL` is set.** It overrides every role's effort. Recommend removing it.
- **`availableModels` is set.** It must include `opus` and `sonnet` (and `best`/`fable` if used for the main session). Otherwise roles silently fall back to inheriting the main model.
- **`maxEffortLevel` is below `max`.** It caps `security-executor`. That's acceptable, but tell the user.
- **An existing `statusLine` is present.** Keep theirs by default; replacing it with conductor's is an opt-in.

## Step 3 — Apply

### 3.1 Backups
- Create `CFG/conductor/backup/`.
- On a **first** install only, copy `settings.json` there as `settings.pre-conductor.json`. Never overwrite that file: it preserves the pristine state.
- On every run, copy `CLAUDE.md` and `settings.json` there with a timestamp suffix.

### 3.2 Files
- Copy `templates/agents/*.md` → `CFG/agents/` (skip byte-identical files).
- Copy `templates/hooks/*.py` → `CFG/conductor/hooks/`.
- Copy `templates/statusline.py` → `CFG/conductor/statusline.py`.
- Copy `templates/workflows/execute-plan.js` → `CFG/workflows/execute-plan.js`.

### 3.3 settings.json — merge key by key, never wholesale overwrite
Take `templates/settings.snippet.json` and substitute the placeholders:
- `{{PYTHON}}` → the quoted `PY` path, e.g. `"C:/…/python.exe"`
- `{{CONDUCTOR_DIR}}` → the absolute `CFG/conductor` path, with forward slashes

Then merge:
- `model`: set to `"best"`, or `"opus"` if the user is on Pro/API or chose it. Record the old value in the plan.
- `fallbackModel`: set to `["opus","sonnet"]` unless the user has a deliberate custom chain.
- `modelSettings`: for each model ID in the snippet, set `effortLevel`. Keep every other key the user has under that model (e.g. `maxEffortLevel`, `autoCompactWindow`). Keep other model IDs untouched.
  - If the user's existing value differs from the snippet (e.g. Sonnet `high` vs conductor's `medium`), show it in the plan and let them choose.
  - This only sets the *main-session* default for that model. Role agents carry their own effort in frontmatter.
- `env`: add `CLAUDE_CODE_ENABLE_TODO_TOOLS: "1"`. Keep all other env keys.
- `statusLine`: add it only if absent, or if the user opted in.
- `hooks`: append conductor's three hook entries to the matching event arrays. Don't remove or reorder the user's hooks. An entry is "conductor's" if its command contains `/conductor/hooks/`. Replace those entries on upgrade instead of duplicating them.

Write valid JSON, then re-read the file and parse it to confirm.

### 3.4 CLAUDE.md policy block
Insert the full contents of `templates/claude-md.orchestration.md` into `CFG/CLAUDE.md`:
- If a `<!-- conductor:begin --> … <!-- conductor:end -->` block exists, replace it in place.
- Otherwise append the block, preceded by one blank line.
- If the file doesn't exist, create it.

Never touch content outside the markers.

## Step 4 — Verify and hand off

1. Run the tests from this checkout: `PY -m unittest discover -s tests`. All of them must pass.
2. Smoke-test the installed guard with real paths:
   - Pipe `{"session_id":"t","tool_name":"Agent","tool_input":{"subagent_type":"general-purpose","prompt":"x"}}` into `PY CFG/conductor/hooks/agent_guard.py`.
   - Expect a `deny` JSON.
   - Then delete `CFG/conductor/state/t.json` if it was created.
3. Tell the user to **restart Claude Code**. Agents, settings, and hooks are loaded at session start. After restart:
   - `/model` should show `best` (or `opus`).
   - Asking "which subagent types are available?" should list the 8 roles.
   - `/hooks` should list the three conductor hooks.
4. Point them to:
   - `CFG/conductor/ledger.jsonl`, which grows one line per finished subagent, for auditing routing
   - `/usage`, which attributes cost per subagent

## Uninstall

1. Delete the 8 role files from `CFG/agents/` (match by frontmatter `name:`).
2. Delete `CFG/workflows/execute-plan.js`.
3. Delete `CFG/conductor/`, but first offer to keep `ledger.jsonl` and `backup/`.
4. Remove the `<!-- conductor:begin --> … <!-- conductor:end -->` block from `CFG/CLAUDE.md`.
5. In `CFG/settings.json`:
   - Remove the hook entries whose command contains `/conductor/hooks/`.
   - Remove conductor's `statusLine` if it was installed.
   - Remove `env.CLAUDE_CODE_ENABLE_TODO_TOOLS`.
   - Offer to restore `model`, `fallbackModel`, and `modelSettings` from `backup/settings.pre-conductor.json`.
