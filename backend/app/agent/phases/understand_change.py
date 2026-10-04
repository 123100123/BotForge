"""understand_change: change request + base requirements + spec outline -> RequirementsDelta.

One structured call (strong tier). The delta is normalized against the base requirements (new ids
continue the base numbering) and the run's requirements become base + delta. Clarification follows
the CREATE policy: blocking questions are asked (at most ``max_questions`` per round,
``max_clarify_rounds`` rounds), everything else becomes an assumed added requirement.
"""

from app.agent import events as ev
from app.agent.context import Next, RunContext
from app.agent.llm import LLMError
from app.agent.modify import (
    apply_delta,
    delta_is_empty,
    empty_requirements,
    next_requirement_number,
    normalize_delta,
    requirement_lines,
)
from app.agent.phases import BUDGET_MESSAGE, fail, render_conversation, say, section, task_message
from app.agent.phases.understand import question_as_assumption, questions_text, unsupported_text
from app.agent.prompts import system_prompt
from app.agent.requirements import Question, RequirementsDelta
from app.agent.state import ChatTurn
from app.botspec.models import StrictModel
from app.botspec.outline import spec_outline

NOTHING_TO_CHANGE = "متوجه نشدم چه چیزی در ربات باید تغییر کند. لطفاً تغییر موردنظر را در یک جمله بگویید."
NOTHING_DONE = "تغییری در ربات لازم نبود؛ ربات فعلی همان‌طور که هست کار می‌کند."


class UnderstandChangeOut(StrictModel):
    delta: RequirementsDelta
    message: str


def apply_question_policy(
    delta: RequirementsDelta, base_numbers_from: int, *, allow_questions: bool, max_questions: int
) -> tuple[RequirementsDelta, list[Question]]:
    """Blocking questions are asked (when allowed); the rest become assumed added requirements."""
    added = list(delta.added)
    n = max(base_numbers_from, next_requirement_number(added))
    blocking: list[Question] = []
    for q in delta.open_questions:
        if q.severity == "blocking" and allow_questions:
            blocking.append(q)
        else:
            added.append(question_as_assumption(q, f"R{n}"))
            n += 1
    asked = blocking[:max_questions]
    return delta.model_copy(update={"added": added, "open_questions": blocking}), asked


async def end_without_change(ctx: RunContext, text: str) -> Next:
    """Finish the run ``done`` without a revision (a previous draft of this run is rejected)."""
    if ctx.state.revision_id is not None:
        await ctx.repo.reject_revision(ctx.state.revision_id)
        ctx.state.revision_id = None
    await say(ctx, text)
    return Next("understand", "done")


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    if ctx.over_budget():
        return await fail(ctx, BUDGET_MESSAGE, "token budget exhausted before understand_change")
    assert state.base_spec is not None and state.draft_spec is not None
    base = state.base_requirements or empty_requirements()
    allow_questions = state.clarify_rounds < ctx.limits.max_clarify_rounds
    sections = [
        section("conversation", render_conversation(state.conversation)),
        section("base_requirements", base),
        section("bot_outline", spec_outline(state.draft_spec)),
    ]
    if state.delta is not None:
        sections.append(section("previous_delta", state.delta))
    sections.append(
        section(
            "clarification",
            f"Clarification rounds used: {state.clarify_rounds} of {ctx.limits.max_clarify_rounds}. "
            + (
                f"You may ask at most {ctx.limits.max_questions} blocking questions."
                if allow_questions
                else "No more questions are allowed: record every open point as an assumed added "
                "requirement and return an empty open_questions list."
            ),
        )
    )
    try:
        out, usage = await ctx.llm.structured(
            task="understand",
            system=system_prompt(),
            messages=[task_message("understand_change", *sections)],
            schema=UnderstandChangeOut,
            tier="strong",
        )
    except LLMError as exc:
        ctx.charge(exc.usage)
        return await fail(
            ctx, "نتوانستم درخواست تغییر را تحلیل کنم. لطفاً دوباره تلاش کنید.", f"understand_change: {exc}"
        )
    ctx.charge(usage)
    assert isinstance(out, UnderstandChangeOut)

    delta, asked = apply_question_policy(
        normalize_delta(out.delta, base),
        next_requirement_number(base.items),
        allow_questions=allow_questions,
        max_questions=ctx.limits.max_questions,
    )
    state.delta = delta
    state.requirements = apply_delta(base, delta)
    await ctx.emit(ev.requirements(state.requirements))

    unsupported = unsupported_text(state.requirements)
    lines = requirement_lines(delta, base)
    text = "\n\n".join(t for t in (out.message.strip(), "\n".join(lines), unsupported) if t)

    if asked:
        if text:
            await say(ctx, text)
        state.clarify_rounds += 1
        state.pending_questions = asked
        await ctx.emit(ev.questions(asked))
        state.conversation.append(ChatTurn(role="agent", text=questions_text(asked)))
        return Next("clarify", "waiting_user")
    state.pending_questions = []

    if delta_is_empty(delta):
        if delta.unsupported:
            return await end_without_change(ctx, text or NOTHING_DONE)
        state.clarify_rounds += 1
        if state.clarify_rounds > ctx.limits.max_clarify_rounds:
            return await end_without_change(ctx, NOTHING_DONE)
        await say(
            ctx,
            NOTHING_TO_CHANGE if not out.message.strip() else f"{out.message.strip()}\n\n{NOTHING_TO_CHANGE}",
        )
        return Next("clarify", "waiting_user")

    if text:
        await say(ctx, text)
    return Next("build")
