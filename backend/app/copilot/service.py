"""Manager Copilot service: the module toggle, the daily cap and the fast-tier tool loop.

``ask`` is stateless (the client sends its last turns). Order of events: the ``copilot`` module must be
enabled (409), the day's counter in ``bot_modules.config["usage"]`` is incremented under the bot's
advisory lock and committed (429 once ``COPILOT_DAILY_CAP`` is reached; the lock is released before
the model is called, so a slow answer never blocks the bot's events), then the tool loop runs. The
model sees only tool results (aggregates), never records, tokens or secrets.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import LLMClient, LLMError, Usage
from app.botspec.models import BotSpec
from app.capabilities import service as capabilities
from app.capabilities.registry import get_capability
from app.config import get_settings
from app.copilot.prompts import build_system_prompt
from app.copilot.tools import MAX_DATA_CALLS, CopilotTools
from app.db.models import Bot, BotModuleRow
from app.runtime.formatting import DEFAULT_TZ, format_jalali_date, get_tz
from app.runtime.pg_store import PgStore, advisory_lock
from app.schemas.business import ChatTurn, CopilotMessageOut

log = logging.getLogger(__name__)

MODULE = "copilot"
TASK = "copilot"
USAGE_DAYS_KEPT = 7
LIVE = "live"

DISABLED = ("capability_disabled", "دستیار کسب‌وکار را از بخش قابلیت‌ها فعال کنید.")
DAILY_CAP = (
    "copilot_daily_cap",
    "به سقف تعداد پرسش‌های امروز از دستیار رسیده‌اید. لطفاً فردا دوباره تلاش کنید.",
)
LLM_FAILED = ("llm_failed", "دستیار در حال حاضر پاسخ نمی‌دهد. لطفاً کمی بعد دوباره تلاش کنید.")
NO_ANSWER = "پاسخی آماده نشد. لطفاً پرسش را کوتاه‌تر یا دقیق‌تر بنویسید و دوباره بپرسید."


class CopilotError(Exception):
    """A refusal the API turns into ``{"code", "message"}`` with ``status``. ``message`` is Persian."""

    def __init__(self, status: int, error: tuple[str, str]) -> None:
        self.status = status
        self.code, self.message = error
        super().__init__(self.message)


async def _claim_question(session: AsyncSession, bot: Bot, day: str) -> None:
    """Count one question for ``day`` under the bot's lock and commit; 429 at ``COPILOT_DAILY_CAP``."""
    await advisory_lock(session, bot.id)
    stmt = (
        select(BotModuleRow)
        .where(BotModuleRow.bot_id == bot.id, BotModuleRow.module == MODULE)
        .execution_options(populate_existing=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:  # enabled by the registry default: keep the counter in a row from now on
        row = BotModuleRow(bot_id=bot.id, module=MODULE, enabled=True, config={})
        session.add(row)
    config: dict[str, Any] = dict(row.config or {})
    usage: dict[str, int] = {k: v for k, v in dict(config.get("usage") or {}).items() if isinstance(v, int)}
    if usage.get(day, 0) >= get_settings().COPILOT_DAILY_CAP:
        raise CopilotError(429, DAILY_CAP)
    usage[day] = usage.get(day, 0) + 1
    config["usage"] = dict(sorted(usage.items())[-USAGE_DAYS_KEPT:])
    row.config = config  # a new dict: JSONB change tracking sees the assignment
    await session.commit()  # also releases the advisory lock


def _capability_lines(spec: BotSpec | None, module_rows: capabilities.ModuleRows) -> list[str]:
    lines: list[str] = []
    if spec is not None:
        lines += [f"{c.title} (capability_key={c.key}، نوع {c.type})" for c in spec.capabilities if c.enabled]
    for cap_id in sorted(capabilities.enabled_ids(spec, module_rows)):
        cap = get_capability(cap_id)
        if cap is not None and cap.kind == "module" and cap_id != MODULE:
            lines.append(cap.name)
    return lines


def _client_turns(messages: list[ChatTurn]) -> list[dict[str, str]]:
    turns = [{"role": t.role, "content": t.content} for t in messages]
    while turns and turns[0]["role"] != "user":  # the API wants a conversation that starts with the user
        turns.pop(0)
    return turns


def _usage_dict(usage: Usage) -> dict[str, Any]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cached_tokens": usage.cached_tokens,
        "llm_calls": usage.llm_calls,
        "tool_calls": usage.tool_calls,
        "cost_usd": usage.cost_usd,
    }


async def ask(
    session: AsyncSession, bot: Bot, llm: LLMClient, messages: list[ChatTurn], *, now: datetime
) -> CopilotMessageOut:
    module = get_capability(MODULE)
    module_rows = await capabilities.load_module_rows(session, bot)
    if module is None or not capabilities.module_enabled(module, module_rows):
        raise CopilotError(409, DISABLED)

    spec = await capabilities.load_spec(session, bot)
    timezone = spec.bot.timezone if spec is not None else DEFAULT_TZ
    await _claim_question(session, bot, now.astimezone(get_tz(timezone)).date().isoformat())

    tools = CopilotTools(session, bot, spec, PgStore(session, bot.id, LIVE, bot.owner_actor_id), now)
    system = build_system_prompt(
        bot_name=spec.bot.name if spec is not None else bot.name,
        today=format_jalali_date(now, timezone),
        timezone=timezone,
        capabilities=_capability_lines(spec, module_rows),
        max_calls=MAX_DATA_CALLS,
    )
    try:
        result = await llm.tool_loop(
            task=TASK,
            system=system,
            messages=_client_turns(messages),
            tools=tools.definitions(),
            handler=tools.handle,
            max_tool_calls=MAX_DATA_CALLS + 1,  # the data calls and ``finish``
            tier="fast",
        )
    except LLMError as exc:
        log.warning("copilot llm error bot=%s code=%s", bot.id, exc.code)
        raise CopilotError(502, LLM_FAILED) from None
    except Exception as exc:  # provider or network failure (anthropic.APIError and friends)
        log.warning("copilot llm failure bot=%s: %s", bot.id, type(exc).__name__)
        raise CopilotError(502, LLM_FAILED) from None

    usage = result.usage
    log.info(
        "copilot bot=%s stop=%s tool_calls=%d in=%d out=%d cost_usd=%s",
        bot.id,
        result.stop_reason,
        len(tools.calls),
        usage.input_tokens,
        usage.output_tokens,
        usage.cost_usd,
    )
    reply = tools.answer or (result.text or "").strip() or NO_ANSWER
    return CopilotMessageOut(reply=reply, tool_calls=tools.calls, usage=_usage_dict(usage))
