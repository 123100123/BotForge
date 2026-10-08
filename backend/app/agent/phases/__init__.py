"""Phase implementations. Each phase is ``async def run(ctx: RunContext) -> Next``.

Shared helpers build the per-call user message: task instructions first, then tagged data
sections. Everything per-call goes after the cached system prefix.
"""

from typing import Any

from pydantic import BaseModel

from app.agent import events as ev
from app.agent import prompts
from app.agent.checks import compact_json
from app.agent.context import Next, RunContext
from app.agent.llm import LLMError
from app.agent.state import ChatTurn, RunState

BUDGET_MESSAGE = "بودجهٔ این گفتگو برای ساخت ربات تمام شد."
CORRECTIVE_RETRY_REASON = "بعضی آزمون‌ها ایراد داشتند؛ دوباره می‌نویسم."
STEP_LIMIT_TEXT = (
    "ایجنت پیش از تأیید نهایی کارش به سقف تعداد اقدام‌ها رسید. اگر می‌خواهید ادامه دهد، یک پیام بفرستید."
)


def add_block_reason(state: RunState, reason: str) -> None:
    """Record a reason that blocks approval (reasons accumulate, each once)."""
    current = state.approval_blocked_reason
    if not current:
        state.approval_blocked_reason = reason
    elif reason not in current:
        state.approval_blocked_reason = f"{current} {reason}"


def note_loop_end(state: RunState, loop: str, stop_reason: str) -> None:
    """Roadmap Limits: a loop that hit the tool-call cap without ``finish`` blocks approval.

    The run still goes on to tests and review so the owner sees the state; a later loop of this
    run that ends with ``finish`` clears the mark.
    """
    if stop_reason == "tool_limit":
        state.step_limit_hit = loop
    elif stop_reason == "finished":
        state.step_limit_hit = None


async def say(ctx: RunContext, text: str) -> None:
    """An agent message to the owner: emitted and kept in the conversation."""
    ctx.state.conversation.append(ChatTurn(role="agent", text=text))
    await ctx.emit(ev.agent_message(text))


async def fail(
    ctx: RunContext, message: str, detail: str | None = None, code: str = ev.VALIDATION_FAILED
) -> Next:
    """End the run as failed with a Persian explanation (error event + agent message).

    ``code`` is the stable ``error.code``: VALIDATION_FAILED (the default: the agent could not reach
    a valid result), BUDGET_EXCEEDED, or LLM_UNAVAILABLE. Nothing has reached the live bot, so
    ``applied`` is always false."""
    ctx.state.error = detail or message
    if ctx.state.kind == "modify" and ctx.state.revision_id is not None:
        # A draft from an earlier round of this run must not outlive the failed run.
        await ctx.repo.reject_revision(ctx.state.revision_id)
    await ctx.emit(ev.error(message, code))
    await say(ctx, message)
    return Next("failed", "failed")


def llm_failure_code(exc: LLMError) -> str:
    """``error.code`` for a model call that failed: the API was unreachable, or its output was unusable."""
    return ev.LLM_UNAVAILABLE if exc.code == "api_error" else ev.VALIDATION_FAILED


def section(tag: str, content: str | BaseModel | Any) -> str:
    if isinstance(content, BaseModel):
        content = compact_json(content.model_dump(mode="json", exclude_none=False))
    elif not isinstance(content, str):
        content = compact_json(content)
    return f"<{tag}>\n{content}\n</{tag}>"


def task_message(task: str, *sections: str) -> dict[str, Any]:
    body = "\n\n".join([prompts.load(task), *[s for s in sections if s]])
    return {"role": "user", "content": body}


def render_conversation(turns: list[ChatTurn], *, owner_only: bool = False) -> str:
    lines = []
    for t in turns:
        if owner_only and t.role != "owner":
            continue
        who = "Owner" if t.role == "owner" else "Agent"
        lines.append(f"{who}: {t.text}")
    return "\n".join(lines)
