"""run: every scenario on MemoryStore (derived scenarios re-derived from the current draft)."""

from app.agent import events as ev
from app.agent.checks import fa
from app.agent.context import Next, RunContext
from app.agent.phases import BUDGET_MESSAGE
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    assert state.draft_spec is not None
    state.derived = derive_scenarios(state.draft_spec)
    scenarios = state.all_scenarios()
    report = await run_scenarios(state.draft_spec, scenarios)
    state.test_report = report
    await ctx.emit(ev.test_report(report, scenarios))
    if report.failed == 0:
        return Next("review")
    if ctx.over_budget():
        state.approval_blocked_reason = f"{BUDGET_MESSAGE} {fa(report.failed)} آزمون هنوز ناموفق است."
        return Next("review")
    if state.repair_rounds < ctx.limits.max_repair_rounds:
        return Next("repair")
    state.approval_blocked_reason = (
        f"پس از {fa(state.repair_rounds)} دور اصلاح، {fa(report.failed)} آزمون هنوز ناموفق است."
    )
    return Next("review")
