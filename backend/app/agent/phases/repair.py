"""repair: a bounded tool loop that reads failures and patches the spec or fixes a new scenario.

MODIFY adds ``supersede_scenario`` (guarded in the tool) and marks each failure as derived, new or
carried, with ``supersedable`` for carried ones, so the model knows which side may be wrong.
"""

from app.agent.checks import compact_json
from app.agent.context import Next, RunContext
from app.agent.modify import releasable_ids
from app.agent.phases import note_loop_end, section, task_message
from app.agent.phases.build_change import compat_issues
from app.agent.prompts import system_prompt
from app.agent.tools import MODIFY_REPAIR_TOOLS, REPAIR_TOOLS, AgentTools


def failure_list(ctx: RunContext) -> list[dict[str, object]]:
    state = ctx.state
    report = state.test_report
    if report is None:
        return []
    by_id = {s.id: s for s in state.all_scenarios()}
    releasable = releasable_ids(state.delta)
    out = []
    for r in report.results:
        if r.passed:
            continue
        sc = by_id.get(r.scenario_id)
        step = next((s for s in r.steps if not s.passed), None)
        item: dict[str, object] = {
            "id": r.scenario_id,
            "title": sc.title if sc else r.scenario_id,
            "source": sc.source if sc else None,
            "requirement_ids": sc.requirement_ids if sc else [],
            "fixable": r.scenario_id in state.new_scenario_ids,
            "failed_step": r.failed_step,
            "message": step.message if step else None,
        }
        if state.kind == "modify" and sc is not None:
            if sc.source == "derived":
                item["kind"] = "derived"
            elif sc.id in state.new_scenario_ids:
                item["kind"] = "new"
            else:
                item["kind"] = "carried"
                item["supersedable"] = bool(set(sc.requirement_ids) & releasable)
        out.append(item)
    return out


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    assert state.draft_spec is not None and state.requirements is not None
    state.repair_rounds += 1
    modify = state.kind == "modify"
    tools = AgentTools(
        state,
        loop="repair",
        emit=ctx.emit,
        names=MODIFY_REPAIR_TOOLS if modify else REPAIR_TOOLS,
        compat=(lambda s: compat_issues(ctx, s)) if modify else None,
    )
    sections = [section("requirements", state.requirements)]
    if modify:
        sections.append(section("requirement_change", state.delta))
    sections += [
        section("current_draft_spec", compact_json(state.draft_spec.model_dump(mode="json"))),
        section("failures", failure_list(ctx)),
        section("repair_round", f"{state.repair_rounds} of {ctx.limits.max_repair_rounds}"),
    ]
    result = await ctx.llm.tool_loop(
        task="repair",
        system=system_prompt(),
        messages=[task_message("repair_change" if modify else "repair", *sections)],
        tools=tools.defs(),
        handler=tools.handle,
        max_tool_calls=ctx.limits.max_tool_calls,
        tier="strong",
        on_usage=ctx.usage_hook,
    )
    state.usage.tool_calls += result.tool_calls
    note_loop_end(state, "repair", result.stop_reason)
    return Next("run")  # the run phase re-tests and decides: review, another round, or blocked
