"""review: summary, sample data (fast tier), draft revision, sandbox load, approval request."""

import logging

from app.agent import events as ev
from app.agent.checks import check_sample_record, fa
from app.agent.context import Next, RunContext
from app.agent.llm import LLMError
from app.agent.phases import render_conversation, say, section, task_message
from app.agent.prompts import system_prompt
from app.agent.repository import RepositoryError
from app.botspec.models import StrictModel
from app.botspec.outline import OutlineResource, spec_outline
from app.testing.scenario import SeedRecord

log = logging.getLogger(__name__)

MAX_SAMPLE_RECORDS = 12


class SampleDataOut(StrictModel):
    records: list[SeedRecord]


async def generate_sample_data(ctx: RunContext, resources: list[OutlineResource]) -> list[SeedRecord]:
    state = ctx.state
    assert state.draft_spec is not None and state.requirements is not None
    if not resources or ctx.over_budget():
        return []
    try:
        out, usage = await ctx.llm.structured(
            task="sample_data",
            system=system_prompt(),
            messages=[
                task_message(
                    "sample_data",
                    section("business", state.requirements.business_summary),
                    section("resources", [r.model_dump(mode="json") for r in resources]),
                )
            ],
            schema=SampleDataOut,
            tier="fast",
        )
    except LLMError as exc:
        ctx.charge(exc.usage)
        log.warning("sample data generation failed: %s", exc)
        return []
    ctx.charge(usage)
    assert isinstance(out, SampleDataOut)
    records: list[SeedRecord] = []
    for raw in out.records[:MAX_SAMPLE_RECORDS]:
        seed, problem = check_sample_record(raw.model_dump(mode="json"), state.draft_spec)
        if seed is None:
            log.info("sample record dropped: %s", problem)
            continue
        records.append(seed)
    return records


def summary_text(ctx: RunContext, loaded: int) -> str:
    state = ctx.state
    assert state.draft_spec is not None
    spec = state.draft_spec
    report = state.test_report
    titles = "، ".join(c.title for c in spec.capabilities)
    parts = [f"ربات «{spec.bot.name}» آماده شد: {titles}."]
    if report is not None:
        parts.append(f"{fa(report.passed)} از {fa(report.total)} آزمون موفق بود.")
    assumed = [r for r in (state.requirements.items if state.requirements else []) if r.status == "assumed"]
    if assumed:
        parts.append(f"{fa(len(assumed))} مورد را خودم فرض کردم؛ اگر درست نیست بگویید.")
    if loaded:
        parts.append("چند نمونه برای امتحان در شبیه‌ساز گذاشتم.")
    if state.approval_blocked_reason:
        parts.append(f"فعلاً امکان تأیید نیست: {state.approval_blocked_reason}")
    else:
        parts.append("اگر راضی هستید، آن را تأیید کنید.")
    return " ".join(parts)


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    assert state.draft_spec is not None
    report = state.test_report
    if report is None:
        state.approval_blocked_reason = state.approval_blocked_reason or "آزمون‌ها اجرا نشده‌اند."
    elif report.failed > 0 and not state.approval_blocked_reason:
        state.approval_blocked_reason = f"{fa(report.failed)} آزمون ناموفق است."

    outline = spec_outline(state.draft_spec)
    state.sample_data = await generate_sample_data(ctx, outline.resources)

    if state.revision_id is not None:  # re-entry after the owner asked for changes
        await ctx.repo.reject_revision(state.revision_id)
    first_owner = next((t.text for t in state.conversation if t.role == "owner"), None)
    draft = await ctx.repo.create_draft_revision(
        ctx.bot_id,
        spec=state.draft_spec,
        requirements=state.requirements,
        scenarios=state.all_scenarios(),
        test_report=report,
        sample_data=state.sample_data,
        change_request=first_owner
        if state.kind == "create"
        else render_conversation(state.conversation, owner_only=True),
        parent_id=ctx.active_revision_id,
    )
    state.revision_id = draft.id
    loaded = 0
    if state.sample_data:
        try:
            loaded = await ctx.repo.load_sample_data(draft.id)
        except RepositoryError as exc:
            log.warning("sample data not loaded: %s", exc.message)

    can_approve = state.approval_blocked_reason is None
    await say(ctx, summary_text(ctx, loaded))
    await ctx.emit(ev.approval_requested(draft.id, can_approve, state.approval_blocked_reason))
    return Next("await_approval", "waiting_approval")
