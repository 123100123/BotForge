"""repair: a bounded tool loop that reads failures and patches the spec or fixes a new scenario."""

from app.agent.checks import compact_json
from app.agent.context import Next, RunContext
from app.agent.phases import section, task_message
from app.agent.prompts import system_prompt
from app.agent.tools import REPAIR_TOOLS, AgentTools


def failure_list(ctx: RunContext) -> list[dict[str, object]]:
    state = ctx.state
    report = state.test_report
    if report is None:
        return []
    by_id = {s.id: s for s in state.all_scenarios()}
    out = []
    for r in report.results:
        if r.passed:
            continue
        sc = by_id.get(r.scenario_id)
        step = next((s for s in r.steps if not s.passed), None)
        out.append(
            {
                "id": r.scenario_id,
                "title": sc.title if sc else r.scenario_id,
                "source": sc.source if sc else None,
                "requirement_ids": sc.requirement_ids if sc else [],
                "fixable": r.scenario_id in state.new_scenario_ids,
                "failed_step": r.failed_step,
                "message": step.message if step else None,
            }
        )
    return out


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    assert state.draft_spec is not None and state.requirements is not None
    state.repair_rounds += 1
    tools = AgentTools(state, loop="repair", emit=ctx.emit, names=REPAIR_TOOLS)
    result = await ctx.llm.tool_loop(
        task="repair",
        system=system_prompt(),
        messages=[
            task_message(
                "repair",
                section("requirements", state.requirements),
                section("current_draft_spec", compact_json(state.draft_spec.model_dump(mode="json"))),
                section("failures", failure_list(ctx)),
                section("repair_round", f"{state.repair_rounds} of {ctx.limits.max_repair_rounds}"),
            )
        ],
        tools=tools.defs(),
        handler=tools.handle,
        max_tool_calls=ctx.limits.max_tool_calls,
        tier="strong",
        on_usage=ctx.usage_hook,
    )
    state.usage.tool_calls += result.tool_calls
    return Next("run")  # the run phase re-tests and decides: review, another round, or blocked
