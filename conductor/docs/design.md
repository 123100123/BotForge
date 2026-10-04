# conductor - Design Rationale

## Purpose

This document explains why conductor v2.0.0 is shaped the way it is. The evidence behind each choice is in [research.md](./research.md). Runtime behavior described here is *expected*: the system has been unit-tested (22 tests covering the policy contract and the hooks) but not yet run live.

The brief: Fable 5.1 plans and orchestrates only; Opus 5.5 and Sonnet 5.5 execute, at effort between `medium` and `max`. Goals are token frugality and execution first.

## Layers

Who orchestrates, who executes, and how delegation behaves change at different rates, so they live in different places.

| Layer | File | Changes when | Mechanism |
|---|---|---|---|
| Machine | `settings.json` | Your plan or access changes | `model: "best"`, `fallbackModel`, `modelSettings` |
| Roles | `agents/*.md` | A tier is re-pointed | `model:` and `effort:` in frontmatter |
| Policy | `CLAUDE.md` block | Your working style changes | Prose written against role names, never model names |
| Guardrails | `conductor/hooks/` | Discipline slips | Three light hooks |

A test enforces that the policy prose contains no model names. Model bindings exist in one place (role frontmatter), so re-pointing a tier is a one-line edit.

## Why triage first

Orchestration loses money on small tasks. Every spawn is a fresh context that re-reads its slice of the codebase, and writing the spec costs main-session tokens on the most expensive model. A community run of 60 tasks measured a median of $0.16 per run for Opus 5.5 at medium and $0.48 for Fable 5.1, concluding that on small tasks solo Opus beats a Fable-led split. fable-baton measured Fable tokens down 38-44% with total API cost roughly unchanged (n=2).

So the first rule of the policy is a classification:

| Class | Why this treatment |
|---|---|
| S | Delegation overhead would exceed the work. Do it inline. |
| M | One coherent unit: one role agent, verifier only if non-trivial. |
| L | Parallelism pays; integration and verification become necessary. |
| XL | Fan-out is large enough that a saved workflow beats hand-orchestration. It is proposed to the user, not run silently. |

Anthropic also recommends an effort sweep before multi-model setups. The S class is the built-in answer to "is orchestration worth it here".

## Why route by risk, not size

File count says little about the cost of being wrong. A one-line change to billing logic needs design judgment; a 40-file rename needs none. The policy states "file count never picks the role" (a rule borrowed from latinovation's orchestrator), and the role descriptions are written around risk: invariants, migrations, concurrency, money, security.

## Why Sonnet is the default executor, and Opus covers three roles

| Role | Model | Argument |
|---|---|---|
| `scout`, `Explore`, `mech-executor`, `executor`, `integrator` | Sonnet 5.5 | Cheapest tier ($2/$10 vs $4/$20 for Opus) and the volume sink. Anthropic's guidance puts Sonnet 5.5 at medium for agentic work and high for harder tasks, which is where these roles sit. |
| `senior-executor` | Opus 5.5 | Work where a wrong design decision is expensive, and the escalation target for `executor`. |
| `security-executor` | Opus 5.5 | Security work deserves maximum effort over cost. Running it directly on Opus (never Fable) also avoids frontier-model classifier fallbacks carried over from pilotfish (that rationale is unverified for 5.1). |
| `verifier` | Opus 5.5 | A stronger tier than the usual Sonnet executor, so a fresh-context check is not the same model grading its own work. At medium, since Opus 5.5 at medium is reported to match Opus 5 at high. |

pilotfish v1.1.5 made Opus the default `executor`. Moving it to Sonnet follows both the price gap and pilotfish's own later direction (v1.4.2 runs executors on Sonnet and the verifier on Opus at medium). `senior-executor` takes over the cases that justified Opus.

A Sonnet-specific hazard: at `xhigh` or `max`, Sonnet 5.5 spawns reviewer subagents on its own, and one prompt line stops this and cut cost by about a third. conductor handles it twice: Sonnet roles top out at `high`, and every role forbids delegation (`disallowedTools: Agent, Workflow`, plus a leaf-agent line in each prompt). Sonnet 5.5 also cannot read Opus thinking blocks, so `senior-executor`'s prompt requires a plain, explicit-text final report.

## Why no role binds to Fable

Fable 5.1 costs about 2.5x Opus and 5x Sonnet. The point of conductor is that Fable's tokens go to triage, specs, and judgment in the main session. A role bound to Fable would spend them on execution. A test checks that no role uses `fable`, `best`, or `inherit`, and the fallback chain `["opus","sonnet"]` also excludes Fable. Roles are not affected if Fable leaves the account.

## Why light hooks rather than hard gates

Pilotfish v1.1.5 was policy-only. Policy text alone drifts, and the costliest drift is mechanical: a model argument on a role call silently overrides the role's tier, and an ad-hoc agent inherits the frontier model. Those two have exact signatures, so `agent_guard.py` denies them.

Everything else is a nudge or a record: `inline_edit_nudge.py` injects a reminder after 4 consecutive main-session edits, and `subagent_ledger.py` records per-subagent usage so routing can be audited instead of assumed. All hooks fail open, ignore subagent events, and have an off switch or threshold. Hard edit gates (blocking the main session from editing) were rejected: they would break the S class, they punish legitimate finishing work, and a misfire costs more than a nudge.

## Why the integrator exists

Parallel writers in separate worktrees produce slices that someone must merge. Without a role for it, the orchestrator either merges inline (expensive tokens on mechanical work) or forgets worktrees (lost work). The `integrator` merges in a given order, resolves only mechanical conflicts, stops and reports semantic ones with both sides, runs the full suite, and removes only what it fully merged. It is the single place where uncollected worktrees are harvested.

## Why INCONCLUSIVE was added

pilotfish v1.1.5 verdicts were CONFIRMED or REFUTED, which forces a verifier without decisive evidence (no credentials, service, or environment) to guess. INCONCLUSIVE lets it say exactly what is missing and what it did check. The policy then tells the orchestrator to report the gap to the user rather than loop. pilotfish v1.4.2 also uses three verdicts.

## Effort tiers

| Role class | Effort | Reason |
|---|---|---|
| Recon (`scout`, `Explore`) | `medium` | The user's range starts at medium; Sonnet is the cheapest tier with effort control. |
| `mech-executor` | `medium` | Judgment is in the spec; Sonnet 5.5 guidance is medium for agentic work. |
| `executor`, `integrator` | `high` | Real implementation and merge debugging; the harder-task setting for Sonnet 5.5. |
| `senior-executor` | `high` | Opus 5.5 at high; `xhigh` adds cost for diminishing return in most cases. |
| `verifier` | `medium` | Reads and runs rather than writes; depth scales with risk through its prompt. |
| `security-executor` | `max` | Correctness over cost, taken to the ceiling. Capped if `maxEffortLevel` is lower. |
| Main session | `high` (Fable 5.1 and Opus 5.5), `medium` (Sonnet 5.5) | Via `modelSettings`. Anthropic suggests starting Fable at high. |

The official `effortLevel` top-level setting is ignored for Opus 5.5 and later, which is why defaults are written under `modelSettings.<id>.effortLevel`.

## Deliberately left out

| Not included | Why |
|---|---|
| Agent teams | Experimental and tmux-based; roles plus worktrees cover the need with stable features. |
| The advisor feature | Experimental. Anthropic's own numbers: Opus 5.5 at high with a Fable 5.1 advisor scored 90.1% at $2.92, while Opus 5.5 at xhigh alone scored 91.1% at $4.11. Cheaper, but a one-point gap that an effort setting can also close, and the feature is experimental. |
| Haiku | No effort control, and the user's range starts at medium. |
| A cache-TTL setting | Undocumented; not worth tuning blind. |
| Hard edit gates | See the hooks section above. |
| `CLAUDE_CODE_SUBAGENT_MODEL` | It overrides every role's frontmatter. The installer warns if it is set. |
| Per-project configuration | One global source of truth; project files stay technical notes. |
| A Chinese README | Not carried over from pilotfish. |

## Changes from pilotfish v1.1.5

| Area | pilotfish v1.1.5 | conductor v2.0.0 |
|---|---|---|
| Roles | 6 | 8 (adds `senior-executor`, `integrator`) |
| Default `executor` | Opus, high | Sonnet, high |
| `mech-executor` effort | high | medium |
| `verifier` | Opus, high; CONFIRMED/REFUTED | Opus, medium; adds INCONCLUSIVE |
| `security-executor` | Opus, max | unchanged |
| Leaf roles, read-only verifier | Already present | Kept (tests now enforce both) |
| Triage | Start cheap, escalate | Explicit S/M/L/XL classes before any work |
| Routing basis | Task type | Risk, never file count |
| Hooks | None | Guard, nudge, ledger; fail open |
| Status line | None | Model, cost, context, delegation count |
| Workflow | None | `execute-plan` (execute, integrate, verify) |
| Settings | `model`, `fallbackModel` | Adds `modelSettings` effort, `CLAUDE_CODE_ENABLE_TODO_TOOLS`, hooks, status line |
| Subscription claim | Extra Sonnet-only weekly bucket | Removed: unconfirmed |
| "96% at 46% cost" claim | Quoted in README | Removed: not found in official docs |
| Marker block | `pilotfish:begin/end` | `conductor:begin/end`; installer offers to supersede pilotfish |
| Languages | English + zh-TW | English only |
| Tests | Policy contract | 22 tests: policy contract plus hook behavior |
