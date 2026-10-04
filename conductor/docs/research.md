# conductor - Research Report

## Purpose and method

This report collects the facts behind conductor v2.0.0 (see [design.md](./design.md)): model aliases and effort levels, pricing, subscription limits, Anthropic's cost guidance, community measurements, and the Claude Code mechanisms the config relies on. Data is current as of October 2026.

Method note: the findings below were gathered in a research pass before the docs were written and are reproduced here as supplied; this document's author did not re-fetch the sources. Anything not in that verified set is marked **unverified**. Nothing here has been observed in a live conductor install.

## Contents

- [Models, aliases, context](#models-aliases-context)
- [Effort](#effort)
- [Pricing](#pricing)
- [Subscriptions](#subscriptions)
- [Official cost guidance](#official-cost-guidance)
- [Prompting guides](#prompting-guides)
- [Community measurements](#community-measurements)
- [Claude Code mechanics](#claude-code-mechanics)
- [Unverified or unconfirmed](#unverified-or-unconfirmed)
- [Sources](#sources)

## Models, aliases, context

| Alias | Resolves to | Minimum Claude Code |
|---|---|---|
| `best` | Fable 5.1 if the account has Fable access, else Opus | - |
| `fable` | Fable 5.1 | 2.1.257 |
| `opus` | Opus 5.5 | 2.1.280 |
| `sonnet` | Sonnet 5.5 on the Anthropic API; older Sonnets on Bedrock, Vertex, Foundry | 2.1.284 |

All three models have a native 1M context window. The default model for most plans is Opus 5.5. Source: [model-config](https://code.claude.com/docs/en/model-config).

## Effort

| Fact | Value |
|---|---|
| Levels | `low`, `medium`, `high`, `xhigh`, `max`; all supported on Fable 5.1, Opus 5.5, Sonnet 5.5 |
| "ultra" level | Does not exist. `ultracode` is a Claude Code toggle that makes Claude plan a workflow for each substantive task |
| Claude Code defaults | Opus 5.5 and Sonnet 5.5 at `medium`; Fable at `high` |
| Precedence (highest first) | `CLAUDE_CODE_EFFORT_LEVEL` env, `--effort`, `/effort`, `modelSettings.<id>.effortLevel`, top-level `effortLevel` (ignored for Opus 5.5+), model default |
| Subagents | Frontmatter `effort` overrides the session level; `maxEffortLevel` caps it |

Consequence for conductor: per-model defaults go under `modelSettings`, and role effort lives in frontmatter. Source: [model-config](https://code.claude.com/docs/en/model-config), [sub-agents](https://code.claude.com/docs/en/sub-agents).

## Pricing

| Model | Input / MTok | Output / MTok | Relative |
|---|---|---|---|
| Fable 5.1 | $10 | $50 | about 2.5x Opus, 5x Sonnet |
| Opus 5.5 | $4 | $20 | 1x |
| Sonnet 5.5 | $2 | $10 | 0.5x |

Source: [pricing](https://platform.claude.com/docs/en/about-claude/pricing).

## Subscriptions

| Plan | Fable 5.1 access |
|---|---|
| Max, Team/Enterprise Premium | Up to 50% of the weekly limit |
| Pro, Standard seats, API | Billed through usage credits |

Max has one weekly limit. pilotfish v1.1.5 described an additional Sonnet-only bucket; that is **unconfirmed** and conductor does not rely on it. Source: [Claude Fable models on your plan](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan).

## Official cost guidance

From [optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence):

| Setup | Result |
|---|---|
| Fable 5.1 coordinator + 25 Sonnet 5 workers vs solo Fable | 47-55% cheaper, 10-12 points lower score, about 2.3 h vs 15-20 h |
| Advisor: Opus 5.5 at high + Fable 5.1 advisor | 90.1% at $2.92 |
| Opus 5.5 at xhigh alone | 91.1% at $4.11 |

Anthropic recommends an effort sweep before trying multi-model setups. The "96% of all-Fable performance at 46% of the cost" figure quoted by pilotfish v1.1.5 was **not found** in the official docs, so conductor does not repeat it.

## Prompting guides

| Model | Guidance |
|---|---|
| Opus 5.5 | Medium is at least as good as Opus 5 at high |
| Sonnet 5.5 | Medium for agentic work, high for harder tasks. At xhigh/max it spawns reviewer subagents by itself; one prompt line stops this and cut cost by about a third |
| Fable 5.1 | Start at high |

Related community finding: Sonnet 5.5 cannot read Opus thinking blocks, so handoffs between them must be explicit text.

## Community measurements

| Finding | Source |
|---|---|
| pilotfish is now v1.4.2 (Sep 2026): executors on Sonnet, verifier on Opus at medium, a "dispatch brake", CONFIRMED/REFUTED/INCONCLUSIVE verdicts. conductor forks v1.1.5 and is not a port of v1.4.2 | [pilotfish](https://github.com/Nanako0129/pilotfish) |
| Fable token use down 38-44% with total API cost roughly unchanged (n=2) | [fable-baton](https://github.com/realgarit/fable-baton) |
| 60 runs (Sep 2026), median cost per run: Opus 5.5 at medium $0.16, Sonnet 5 $0.18, Fable 5.1 $0.48. On small tasks solo Opus beats a Fable-led split | [wmedia.es](https://wmedia.es/en/tips/claude-code-opus-5-5-vs-fable-5-1-vs-opus-5-benchmark) |
| 12-worker audit: all-Fable $14.50, Fable + Sonnet $6.10, all-Sonnet $4.35 | [Developers Digest](https://developersdigest.tech/blog/fable-5-orchestrator-model-playbook) |
| 40-line report cap and a solo-edit gate | [Rylaa/fable5-orchestrator](https://github.com/Rylaa/fable5-orchestrator) |
| Routing by risk: "file count never selects the model" | [latinovation/fable-orchestrator-claude-code](https://github.com/latinovation/fable-orchestrator-claude-code) |
| Documents routing traps: an unpinned subagent inherits Fable, forks ignore `CLAUDE_CODE_SUBAGENT_MODEL`, and the cache TTL matters; conductor's `agent_guard` hook exists because of the first trap | [y0f/fable-orchestration-5.1](https://github.com/y0f/fable-orchestration-5.1) |

Read these as single-source, small-sample data points, not benchmarks.

## Claude Code mechanics

| Mechanic | Detail | Source |
|---|---|---|
| Subagent model resolution | per-call `model` > frontmatter > `CLAUDE_CODE_SUBAGENT_MODEL` > main model; `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` overrides everything | [sub-agents](https://code.claude.com/docs/en/sub-agents), [model-config](https://code.claude.com/docs/en/model-config) |
| Limits | Nesting depth 3; up to 20 concurrent subagents | [sub-agents](https://code.claude.com/docs/en/sub-agents) |
| Workflow scripts | 16 concurrent agents and 1000 agents per run; pause and resume at usage limits; saved in `~/.claude/workflows/` | [workflows](https://code.claude.com/docs/en/workflows) |
| Hooks on Windows | Run through Git Bash, or PowerShell if Git Bash is absent | [hooks](https://code.claude.com/docs/en/hooks) |
| Hook events used | `PreToolUse` can match `Agent`; `SubagentStop` provides `agent_type` and `agent_transcript_path` | [hooks](https://code.claude.com/docs/en/hooks) |
| Task tools | On 5.x models they need `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` | [model-config](https://code.claude.com/docs/en/model-config) |
| Cost tooling | `/usage` and cost docs | [costs](https://code.claude.com/docs/en/costs) |

How each mechanic is used in conductor:

| Mechanic | Use |
|---|---|
| Resolution order | The guard denies per-call `model` on named roles, because it would win over frontmatter |
| `PreToolUse` on `Agent` | `agent_guard.py` |
| `SubagentStop` | `subagent_ledger.py` reads the transcript for per-model token usage |
| Workflow scripts | `execute-plan.js` omits `model` entirely so roles own routing |
| Nesting and concurrency | Roles are leaves (`disallowedTools: Agent, Workflow`), so depth stays at 1 |

## Unverified or unconfirmed

| Item | Status |
|---|---|
| Extra Sonnet-only weekly bucket on Max | Unconfirmed (claimed by pilotfish v1.1.5) |
| "96% at 46% cost" | Not found in official docs |
| Built-in `Explore` inheriting the main-session model (CC v2.1.198) | Carried over from pilotfish v1.1.5; not re-checked for 5.1-era builds. The shadowing `Explore` role is harmless either way |
| Frontier-model security classifier refusals as a reason to run security work on Opus | Carried over from pilotfish; not re-checked for Fable 5.1 |
| Agent teams, advisor | Experimental per docs ([agent-teams](https://code.claude.com/docs/en/agent-teams), [advisor](https://code.claude.com/docs/en/advisor)); excluded |
| Cache-TTL setting | Undocumented; excluded |
| Haiku effort control | Not available per pilotfish v1.1.5 notes; not re-checked |
| Token or cost savings from conductor itself | Not measured. Use `ledger.jsonl` and `/usage` after install |
| Runtime behavior of hooks, workflow, and install | Unit-tested only (22 tests); not run live |

## Sources

| Category | Links |
|---|---|
| Claude Code docs | [model-config](https://code.claude.com/docs/en/model-config) · [sub-agents](https://code.claude.com/docs/en/sub-agents) · [hooks](https://code.claude.com/docs/en/hooks) · [workflows](https://code.claude.com/docs/en/workflows) · [costs](https://code.claude.com/docs/en/costs) · [agent-teams](https://code.claude.com/docs/en/agent-teams) · [advisor](https://code.claude.com/docs/en/advisor) |
| Anthropic platform | [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) · [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence) |
| Plans | [Claude Fable models on your plan](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan) |
| Community repos | [Nanako0129/pilotfish](https://github.com/Nanako0129/pilotfish) · [Rylaa/fable5-orchestrator](https://github.com/Rylaa/fable5-orchestrator) · [latinovation/fable-orchestrator-claude-code](https://github.com/latinovation/fable-orchestrator-claude-code) · [y0f/fable-orchestration-5.1](https://github.com/y0f/fable-orchestration-5.1) · [realgarit/fable-baton](https://github.com/realgarit/fable-baton) |
| Community measurements | [wmedia.es benchmark](https://wmedia.es/en/tips/claude-code-opus-5-5-vs-fable-5-1-vs-opus-5-benchmark) · [Developers Digest playbook](https://developersdigest.tech/blog/fable-5-orchestrator-model-playbook) |
