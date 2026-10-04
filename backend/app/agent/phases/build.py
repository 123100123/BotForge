"""build: a bounded tool loop that writes the draft spec (CREATE: set_spec + patches).

Ends when the model calls ``finish`` on a draft without validation errors. A loop that stops for
another reason (tool limit, no more tool calls) still proceeds when the draft is valid; otherwise
the run fails with a Persian explanation.
"""

from app.agent.checks import compact_json
from app.agent.context import Next, RunContext
from app.agent.phases import BUDGET_MESSAGE, fail, render_conversation, section, task_message
from app.agent.prompts import system_prompt
from app.agent.tools import BUILD_PATCH_TOOLS, BUILD_TOOLS, AgentTools
from app.botspec.validate import has_errors, validate_spec

_STOP_MESSAGES = {
    "tool_limit": "به سقف تعداد اقدام‌ها رسیدم و مشخصات ربات هنوز خطا دارد.",
    "budget": BUDGET_MESSAGE,
    "refusal": "مدل زبانی این درخواست را نپذیرفت.",
    "max_tokens": "پاسخ مدل زبانی ناقص ماند.",
    "end_turn": "ساخت مشخصات ربات بدون نتیجهٔ معتبر متوقف شد.",
    "finished": "ساخت مشخصات ربات بدون نتیجهٔ معتبر متوقف شد.",
}


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    if ctx.over_budget():
        return await fail(ctx, BUDGET_MESSAGE, "token budget exhausted before build")
    assert state.requirements is not None
    names = BUILD_TOOLS if state.kind == "create" else BUILD_PATCH_TOOLS
    tools = AgentTools(state, loop="build", emit=ctx.emit, names=names)
    sections = [
        section("requirements", state.requirements),
        section("owner_messages", render_conversation(state.conversation, owner_only=True)),
    ]
    if state.draft_spec is not None:
        sections.append(section("current_draft_spec", compact_json(state.draft_spec.model_dump(mode="json"))))
    result = await ctx.llm.tool_loop(
        task="build",
        system=system_prompt(),
        messages=[task_message("build", *sections)],
        tools=tools.defs(),
        handler=tools.handle,
        max_tool_calls=ctx.limits.max_tool_calls,
        tier="strong",
        on_usage=ctx.usage_hook,
    )
    state.usage.tool_calls += result.tool_calls
    valid = state.draft_spec is not None and not has_errors(validate_spec(state.draft_spec))
    if valid and (result.stop_reason == "finished" or result.stop_reason in ("tool_limit", "end_turn")):
        return Next("testgen")
    if valid and result.stop_reason == "budget":
        return Next("testgen")  # testgen and review will block approval for the spent budget
    reason = _STOP_MESSAGES.get(result.stop_reason, _STOP_MESSAGES["end_turn"])
    return await fail(
        ctx,
        f"{reason} لطفاً درخواست را ساده‌تر یا دقیق‌تر بیان کنید و دوباره تلاش کنید.",
        f"build stopped: {result.stop_reason}, tool_calls={result.tool_calls}",
    )
