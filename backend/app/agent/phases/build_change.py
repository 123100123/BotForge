"""build (modify): patch a draft copy of the live spec with apply_spec_patch only.

After each tool loop the draft goes through ``check_compat(base, draft, live record counts)``.
Compatibility errors are fed back to a new loop as issues to fix; every loop draws on the same
``max_tool_calls`` budget for the phase. ``finish`` and ``apply_spec_patch`` also report them, so
the model normally fixes them inside the first loop. Warnings are left for the review card.
"""

from app.agent.checks import compact_json
from app.agent.context import Next, RunContext
from app.agent.phases import BUDGET_MESSAGE, fail, render_conversation, section, task_message
from app.agent.phases.build import _STOP_MESSAGES
from app.agent.prompts import system_prompt
from app.agent.tools import BUILD_PATCH_TOOLS, AgentTools, compact_issues
from app.botspec.compat import check_compat
from app.botspec.models import BotSpec
from app.botspec.validate import SpecIssue, has_errors, validate_spec

MAX_COMPAT_ROUNDS = 3
COMPAT_FAILED = "این تغییر با داده‌های فعلی ربات سازگار نیست"


def compat_issues(ctx: RunContext, spec: BotSpec) -> list[SpecIssue]:
    state = ctx.state
    assert state.base_spec is not None
    return check_compat(
        state.base_spec,
        spec,
        state.record_counts,
        max_confirmed_per_item=state.max_confirmed_per_item or None,
    )


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    if ctx.over_budget():
        return await fail(ctx, BUDGET_MESSAGE, "token budget exhausted before build")
    assert state.requirements is not None and state.draft_spec is not None and state.base_spec is not None
    stats = await ctx.repo.live_stats(ctx.bot_id)
    state.record_counts = stats.record_counts
    state.max_confirmed_per_item = stats.max_confirmed_per_item

    tools = AgentTools(
        state, loop="build", emit=ctx.emit, names=BUILD_PATCH_TOOLS, compat=lambda s: compat_issues(ctx, s)
    )
    base_sections = [
        section("requirement_change", state.delta),
        section("requirements", state.requirements),
        section("owner_messages", render_conversation(state.conversation, owner_only=True)),
        section("live_record_counts", state.record_counts or {}),
    ]
    feedback: list[SpecIssue] = []
    used = 0
    for _ in range(MAX_COMPAT_ROUNDS):
        remaining = ctx.limits.max_tool_calls - used
        if remaining <= 0:
            break
        sections = [
            *base_sections,
            section("current_draft_spec", compact_json(state.draft_spec.model_dump(mode="json"))),
        ]
        if feedback:
            sections.append(
                section(
                    "compat_errors",
                    "The draft cannot go live: it is incompatible with the existing records. Fix every "
                    "error below with apply_spec_patch, then call finish.\n"
                    + compact_json(compact_issues(feedback)),
                )
            )
        result = await ctx.llm.tool_loop(
            task="build",
            system=system_prompt(),
            messages=[task_message("build_change", *sections)],
            tools=tools.defs(),
            handler=tools.handle,
            max_tool_calls=remaining,
            tier="strong",
            on_usage=ctx.usage_hook,
        )
        used += result.tool_calls
        state.usage.tool_calls += result.tool_calls
        valid = not has_errors(validate_spec(state.draft_spec))
        errors = [i for i in compat_issues(ctx, state.draft_spec) if i.severity == "error"]
        if valid and not errors and result.stop_reason in ("finished", "tool_limit", "end_turn", "budget"):
            return Next("testgen")
        if not valid or result.stop_reason in ("budget", "refusal", "max_tokens") or not errors:
            reason = _STOP_MESSAGES.get(result.stop_reason, _STOP_MESSAGES["end_turn"])
            return await fail(
                ctx,
                f"{reason} لطفاً تغییر را ساده‌تر یا دقیق‌تر بیان کنید و دوباره تلاش کنید.",
                f"modify build stopped: {result.stop_reason}, tool_calls={used}",
            )
        feedback = errors
    errors = [i for i in compat_issues(ctx, state.draft_spec) if i.severity == "error"]
    detail = " ".join(i.message for i in errors[:3])
    return await fail(
        ctx,
        f"{COMPAT_FAILED}: {detail} ربات فعلی تغییری نکرد.",
        f"compat errors after {used} tool calls: {[i.code for i in errors]}",
    )
