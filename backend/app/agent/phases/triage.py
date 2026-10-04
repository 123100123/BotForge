"""triage: the first phase of every run on a bot with an active revision (fast tier, one call).

``change`` continues with understand_change; ``question``, ``data_request`` and ``unsupported`` are
answered in Persian and the run ends ``done`` without a revision. The model sees the owner's
message, the requirement statements, and the spec outline only.
"""

from typing import Literal

from app.agent.context import Next, RunContext
from app.agent.llm import LLMError
from app.agent.phases import BUDGET_MESSAGE, fail, say, section, task_message
from app.agent.prompts import system_prompt
from app.botspec.models import StrictModel
from app.botspec.outline import spec_outline

Intent = Literal["change", "question", "data_request", "unsupported"]

DATA_TAB_TEXT = (
    "افزودن، ویرایش یا حذف موارد را خودتان در بخش «داده‌ها» انجام دهید؛ تغییرات بلافاصله در ربات دیده می‌شود."
)
QUESTION_FALLBACK = "پاسخ این سؤال را در مشخصات فعلی ربات پیدا نکردم."
UNSUPPORTED_FALLBACK = "این تغییر با قابلیت‌های فعلی قابل ساخت نیست."
TRIAGE_FAILED = "نتوانستم پیام شما را بررسی کنم. لطفاً دوباره تلاش کنید."


class TriageOut(StrictModel):
    intent: Intent
    reply: str


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    if ctx.over_budget():
        return await fail(ctx, BUDGET_MESSAGE, "token budget exhausted before triage")
    assert state.base_spec is not None
    message = next((t.text for t in reversed(state.conversation) if t.role == "owner"), "")
    statements = [r.statement for r in (state.base_requirements.items if state.base_requirements else [])]
    try:
        out, usage = await ctx.llm.structured(
            task="triage",
            system=system_prompt(),
            messages=[
                task_message(
                    "triage",
                    section("owner_message", message),
                    section("requirements", statements),
                    section("bot_outline", spec_outline(state.base_spec)),
                )
            ],
            schema=TriageOut,
            tier="fast",
        )
    except LLMError as exc:
        ctx.charge(exc.usage)
        return await fail(ctx, TRIAGE_FAILED, f"triage: {exc}")
    ctx.charge(usage)
    assert isinstance(out, TriageOut)
    state.triage = out.intent
    reply = out.reply.strip()
    if out.intent == "change":
        if reply:
            await say(ctx, reply)
        return Next("understand")
    if out.intent == "data_request":
        text = reply if "داده" in reply else " ".join(t for t in (reply, DATA_TAB_TEXT) if t)
    elif out.intent == "question":
        text = reply or QUESTION_FALLBACK
    else:
        text = reply or UNSUPPORTED_FALLBACK
    await say(ctx, text)
    return Next("triage", "done")
