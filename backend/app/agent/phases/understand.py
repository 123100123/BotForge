"""understand: conversation -> Requirements (one structured call), then the clarification policy.

Policy (roadmap: Requirements Model): blocking questions are asked, at most ``max_questions`` per
round and ``max_clarify_rounds`` rounds per run; important questions are never asked and become
assumed requirements; after the last round every remaining question becomes an assumption.
"""

import re

from app.agent import events as ev
from app.agent.checks import compact_json
from app.agent.context import Next, RunContext
from app.agent.llm import LLMError
from app.agent.phases import BUDGET_MESSAGE, fail, render_conversation, say, section, task_message
from app.agent.prompts import system_prompt
from app.agent.requirements import Question, Requirement, Requirements
from app.agent.state import ChatTurn
from app.botspec.models import StrictModel


class UnderstandOut(StrictModel):
    requirements: Requirements
    message: str


_RID = re.compile(r"^R(\d+)$")


def _next_number(items: list[Requirement]) -> int:
    nums = [int(m.group(1)) for r in items if (m := _RID.match(r.id))]
    return max(nums, default=0) + 1


def normalize_ids(req: Requirements) -> Requirements:
    """Requirement ids are unique "R<n>"; duplicates or malformed ids get the next free number."""
    seen: set[str] = set()
    out: list[Requirement] = []
    n = _next_number(req.items)
    for item in req.items:
        if not _RID.match(item.id) or item.id in seen:
            item = item.model_copy(update={"id": f"R{n}"})
            n += 1
        seen.add(item.id)
        out.append(item)
    return req.model_copy(update={"items": out})


def question_as_assumption(q: Question, rid: str) -> Requirement:
    if q.options:
        statement = f"{q.text} فرض: {q.options[0]}"
    else:
        statement = f"{q.text} (یک پیش‌فرض معقول در نظر گرفته شد)"
    return Requirement(id=rid, kind="rule", statement=statement, status="assumed")


def apply_policy(
    req: Requirements, *, allow_questions: bool, max_questions: int
) -> tuple[Requirements, list[Question]]:
    """Return (requirements, questions to ask now)."""
    items = list(req.items)
    n = _next_number(items)
    blocking: list[Question] = []
    for q in req.open_questions:
        if q.severity == "blocking" and allow_questions:
            blocking.append(q)
        else:
            items.append(question_as_assumption(q, f"R{n}"))
            n += 1
    asked = blocking[:max_questions]
    return req.model_copy(update={"items": items, "open_questions": blocking}), asked


def unsupported_text(req: Requirements) -> str | None:
    if not req.unsupported:
        return None
    lines = ["این موارد را فعلاً نمی‌توانم بسازم:"]
    for u in req.unsupported:
        line = f"• {u.statement}: {u.reason}"
        if u.alternative:
            line += f" (پیشنهاد: {u.alternative})"
        lines.append(line)
    return "\n".join(lines)


def questions_text(asked: list[Question]) -> str:
    lines = ["برای ساخت دقیق ربات این سؤال‌ها را دارم:"]
    for q in asked:
        line = f"• {q.text}"
        if q.options:
            line += " (" + " / ".join(q.options) + ")"
        lines.append(line)
    return "\n".join(lines)


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    if ctx.over_budget():
        return await fail(ctx, BUDGET_MESSAGE, "token budget exhausted before understand")
    allow_questions = state.clarify_rounds < ctx.limits.max_clarify_rounds
    sections = [section("conversation", render_conversation(state.conversation))]
    if state.requirements is not None:
        sections.append(section("previous_requirements", state.requirements))
    if state.draft_spec is not None:
        sections.append(section("current_draft_spec", compact_json(state.draft_spec.model_dump(mode="json"))))
    sections.append(
        section(
            "clarification",
            f"Clarification rounds used: {state.clarify_rounds} of {ctx.limits.max_clarify_rounds}. "
            + (
                f"You may ask at most {ctx.limits.max_questions} blocking questions."
                if allow_questions
                else "No more questions are allowed: record every open point as an assumed requirement "
                "and return an empty open_questions list."
            ),
        )
    )
    try:
        out, usage = await ctx.llm.structured(
            task="understand",
            system=system_prompt(),
            messages=[task_message("understand", *sections)],
            schema=UnderstandOut,
            tier="strong",
        )
    except LLMError as exc:
        ctx.charge(exc.usage)
        return await fail(
            ctx, "نتوانستم درخواست شما را تحلیل کنم. لطفاً دوباره تلاش کنید.", f"understand: {exc}"
        )
    ctx.charge(usage)
    assert isinstance(out, UnderstandOut)

    req, asked = apply_policy(
        normalize_ids(out.requirements),
        allow_questions=allow_questions,
        max_questions=ctx.limits.max_questions,
    )
    state.requirements = req
    await ctx.emit(ev.requirements(req))
    message = out.message.strip()
    unsupported = unsupported_text(req)
    text = "\n\n".join(t for t in (message, unsupported) if t)
    if text:
        await say(ctx, text)

    if asked:
        state.clarify_rounds += 1
        state.pending_questions = asked
        await ctx.emit(ev.questions(asked))
        state.conversation.append(ChatTurn(role="agent", text=questions_text(asked)))
        return Next("clarify", "waiting_user")
    state.pending_questions = []
    if not any(r.kind == "capability" for r in req.items):
        # Nothing buildable: ask the owner to describe a supported workflow (counts as a round).
        state.clarify_rounds += 1
        if state.clarify_rounds > ctx.limits.max_clarify_rounds + 1:
            return await fail(ctx, "با توضیحات فعلی نمی‌توانم رباتی بسازم.", "no buildable capability")
        if not text:
            await say(ctx, "لطفاً بگویید مشتری‌ها در ربات چه کاری انجام دهند تا آن را بسازم.")
        return Next("clarify", "waiting_user")
    return Next("build")
