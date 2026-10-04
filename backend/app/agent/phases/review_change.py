"""review (modify): the review card (``diff`` event), the draft revision, the approval request.

Deterministic except sample data for newly added resources (fast tier). The base revision's sample
data is carried forward (records that no longer validate against the draft are dropped).
"""

import logging
from typing import Any

from app.agent import events as ev
from app.agent.checks import check_sample_record, fa
from app.agent.context import Next, RunContext
from app.agent.modify import (
    Risk,
    empty_requirements,
    requirements_card,
    risk_level,
    uncovered_requirements,
    uncovered_text,
)
from app.agent.phases import STEP_LIMIT_TEXT, add_block_reason, fail, render_conversation, say
from app.agent.phases.build_change import compat_issues
from app.agent.phases.review import generate_sample_data
from app.agent.repository import RepositoryError
from app.botspec.diff import SpecChange, affected_capabilities, diff_specs
from app.botspec.outline import spec_outline
from app.revisions.service import StaleBase
from app.testing.scenario import SeedRecord

log = logging.getLogger(__name__)

RISK_FA: dict[str, str] = {"low": "کم", "medium": "متوسط", "high": "زیاد"}
NO_SPEC_CHANGE = "این درخواست هیچ تغییری در رفتار ربات ایجاد نکرد."


def diff_payload(
    changes: list[SpecChange], risk: Risk, warnings: list[str], ctx: RunContext
) -> dict[str, Any]:
    """The ``diff`` event payload, exactly per the roadmap's payload table."""
    state = ctx.state
    _, payload = ev.diff(
        changes=[{"label_fa": c.label_fa, "kind": c.kind} for c in changes],
        affected_capabilities=affected_capabilities(changes),
        tests={
            "carried": len(state.carried_ids),
            "new": len(state.new_scenario_ids),
            "superseded": [{"title": s.scenario.title, "reason": s.reason} for s in state.superseded],
        },
        risk=risk,
        warnings=warnings,
        requirements=requirements_card(state.delta, state.base_requirements or empty_requirements()),
    )
    return payload


async def sample_data(ctx: RunContext, changes: list[SpecChange]) -> list[SeedRecord]:
    state = ctx.state
    assert state.draft_spec is not None
    kept: list[SeedRecord] = []
    for seed in state.base_sample_data:
        ok, problem = check_sample_record(seed.model_dump(mode="json"), state.draft_spec)
        if ok is None:
            log.info("carried sample record dropped: %s", problem)
            continue
        kept.append(ok)
    added = {
        c.path[1] for c in changes if c.kind == "added" and len(c.path) == 2 and c.path[0] == "resources"
    }
    if added:
        resources = [r for r in spec_outline(state.draft_spec).resources if r.key in added]
        kept += await generate_sample_data(ctx, resources)
    return kept


def summary_text(ctx: RunContext, payload: dict[str, Any], loaded: int) -> str:
    state = ctx.state
    report = state.test_report
    lines = ["تغییرات پیشنهادی:"]
    lines += [f"• {c['label_fa']}" for c in payload["changes"]] or [f"• {NO_SPEC_CHANGE}"]
    tests = payload["tests"]
    test_line = (
        f"آزمون‌ها: {fa(tests['carried'])} آزمون قبلی و {fa(tests['new'])} آزمون جدید"
        + (f"؛ {fa(len(tests['superseded']))} آزمون قبلی کنار گذاشته شد" if tests["superseded"] else "")
        + "."
    )
    if report is not None:
        test_line += f" {fa(report.passed)} از {fa(report.total)} آزمون موفق بود."
    lines.append(test_line)
    lines.append(f"ریسک: {RISK_FA[payload['risk']]}.")
    if loaded:
        lines.append("نمونه‌ها برای امتحان در شبیه‌ساز آماده است.")
    if state.approval_blocked_reason:
        lines.append(f"فعلاً امکان تأیید نیست: {state.approval_blocked_reason}")
    else:
        lines.append("ربات فعلی تا تأیید شما تغییری نمی‌کند. اگر راضی هستید، تغییر را تأیید کنید.")
    return "\n".join(lines)


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    assert state.draft_spec is not None and state.base_spec is not None
    if ctx.active_revision_id != state.base_revision_id:
        return await fail(ctx, StaleBase.message, "stale base at review")

    report = state.test_report
    if report is None:
        state.approval_blocked_reason = state.approval_blocked_reason or "آزمون‌ها اجرا نشده‌اند."
    elif report.failed > 0 and not state.approval_blocked_reason:
        state.approval_blocked_reason = f"{fa(report.failed)} آزمون ناموفق است."
    # Every added or changed requirement of the cumulative delta needs a passing new scenario.
    passed = {r.scenario_id for r in report.results if r.passed} if report else set()
    uncovered = uncovered_requirements(state.delta, state.scenarios, state.new_scenario_ids, passed)
    if uncovered:
        add_block_reason(state, uncovered_text(uncovered))
    if state.step_limit_hit:
        add_block_reason(state, STEP_LIMIT_TEXT)

    changes = diff_specs(state.base_spec, state.draft_spec)
    compat = compat_issues(ctx, state.draft_spec)
    errors = [i for i in compat if i.severity == "error"]
    warnings = [i.message for i in compat if i.severity == "warning"]
    if errors:
        warnings = [i.message for i in errors] + warnings
        state.approval_blocked_reason = (
            state.approval_blocked_reason or "این تغییر با داده‌های فعلی سازگار نیست."
        )
    if not changes:
        warnings.append(NO_SPEC_CHANGE)
    risk = risk_level(changes, compat)
    payload = diff_payload(changes, risk, warnings, ctx)
    state.diff = payload
    await ctx.emit((ev.DIFF, payload))

    state.sample_data = await sample_data(ctx, changes)
    if state.revision_id is not None:  # re-entry after the owner asked for more changes
        await ctx.repo.reject_revision(state.revision_id)
    draft = await ctx.repo.create_draft_revision(
        ctx.bot_id,
        spec=state.draft_spec,
        requirements=state.requirements,
        scenarios=state.all_scenarios(),
        test_report=report,
        sample_data=state.sample_data,
        change_request=render_conversation(state.conversation, owner_only=True),
        parent_id=state.base_revision_id,
        patch=list(state.patch_ops),
        superseded=list(state.superseded),
    )
    state.revision_id = draft.id
    loaded = 0
    if state.sample_data:
        try:
            loaded = await ctx.repo.load_sample_data(draft.id)
        except RepositoryError as exc:
            log.warning("sample data not loaded: %s", exc.message)

    can_approve = state.approval_blocked_reason is None
    await say(ctx, summary_text(ctx, payload, loaded))
    await ctx.emit(ev.approval_requested(draft.id, can_approve, state.approval_blocked_reason))
    return Next("await_approval", "waiting_approval")
