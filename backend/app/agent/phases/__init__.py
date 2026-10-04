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
from app.agent.state import ChatTurn

BUDGET_MESSAGE = "بودجهٔ این گفتگو برای ساخت ربات تمام شد."


async def say(ctx: RunContext, text: str) -> None:
    """An agent message to the owner: emitted and kept in the conversation."""
    ctx.state.conversation.append(ChatTurn(role="agent", text=text))
    await ctx.emit(ev.agent_message(text))


async def fail(ctx: RunContext, message: str, detail: str | None = None) -> Next:
    """End the run as failed with a Persian explanation (error event + agent message)."""
    ctx.state.error = detail or message
    await ctx.emit(ev.error(message))
    await say(ctx, message)
    return Next("failed", "failed")


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
