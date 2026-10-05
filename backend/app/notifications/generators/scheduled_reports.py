"""Scheduled reports: the business overview, rendered deterministically (no LLM) and queued for the
managers at the time of day the owner chose.

Configuration lives in ``bot_modules`` (module ``scheduled_reports``): ``config = {"schedules":
[ScheduleOut, ...]}``. With no ``schedules`` key the defaults apply: a ``daily_summary`` at 18:00
(enabled once the module is enabled; the generator only looks at bots whose module is enabled) and a
disabled ``weekly_summary`` on Friday at 17:00.

Weekday convention: ``ScheduleOut.weekday`` is Python's ``datetime.weekday()`` (Monday = 0 ...
Sunday = 6), as ``schemas/business.py`` documents, so Friday is 4. (Period maths such as
``this_week`` use the Persian Saturday-first week; the schedule weekday does not.)

A schedule is due once the bot's local time (``spec.bot.timezone``, Tehran by default) is at or past
its ``HH:MM`` today (and, for weekly, today is its weekday). Each recipient gets one outbox row per
schedule per local day with dedupe key ``rep:<bot_id>:<schedule_id>:<YYYY-MM-DD>:<chat_id>`` (the
chat id is part of the key because the unique key is per bot, so a key without it could serve one
chat only). A restart therefore never double-sends, and a report missed while the process was down
is sent once when it is back, on the same local day only. Daily reports cover ``today``, weekly ones
``this_week``. Recipients are the owner and every manager in ``bot_users``. Records are only read.
"""

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec
from app.db.models import Bot, BotModuleRow, OutboundMessageRow, Revision
from app.notifications.generators import active_spec
from app.notifications.outbox import Message, enqueue_many
from app.notifications.targets import resolve_recipients
from app.reporting import service as reporting
from app.reporting.telegram import render_overview_text
from app.runtime.formatting import format_jalali_date, get_tz
from app.runtime.pg_store import PgStore
from app.schemas.business import Period, ScheduleOut

log = logging.getLogger(__name__)

LIVE = "live"
MODULE = "scheduled_reports"
FRIDAY = 4
TITLES = {"daily_summary": "گزارش روزانه", "weekly_summary": "گزارش هفتگی"}
PERIODS: dict[str, Period] = {"daily_summary": "today", "weekly_summary": "this_week"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def default_schedules(module_enabled: bool = True) -> list[ScheduleOut]:
    return [
        ScheduleOut(id="daily", kind="daily_summary", time="18:00", enabled=module_enabled, metrics=[]),
        ScheduleOut(
            id="weekly", kind="weekly_summary", time="17:00", weekday=FRIDAY, enabled=False, metrics=[]
        ),
    ]


def effective_schedules(config: dict[str, Any] | None, module_enabled: bool) -> list[ScheduleOut]:
    """The stored schedules, or the defaults when none were ever saved. Entries that no longer
    validate are skipped (logged)."""
    raw = (config or {}).get("schedules")
    if not isinstance(raw, list):
        return default_schedules(module_enabled)
    out: list[ScheduleOut] = []
    for item in raw:
        try:
            out.append(ScheduleOut.model_validate(item))
        except ValidationError:
            log.warning("skipping an invalid stored report schedule")
    return out


def is_due(schedule: ScheduleOut, local: datetime) -> bool:
    """Enabled, today's weekday matches (weekly), and the local time has reached ``schedule.time``."""
    if not schedule.enabled:
        return False
    weekday = FRIDAY if schedule.weekday is None else schedule.weekday
    if schedule.kind == "weekly_summary" and local.weekday() != weekday:
        return False
    return local.strftime("%H:%M") >= schedule.time


def dedupe_key(bot_id: object, schedule_id: str, day: str, chat_id: int) -> str:
    return f"rep:{bot_id}:{schedule_id}:{day}:{chat_id}"


def report_text(schedule: ScheduleOut, overview_text: str, local: datetime, tz: str) -> str:
    return f"{TITLES[schedule.kind]} • {format_jalali_date(local, tz)}\n\n{overview_text}"


async def _send_schedule(
    session: AsyncSession,
    bot_id: uuid.UUID,
    owner_actor_id: str | None,
    spec: BotSpec,
    schedule: ScheduleOut,
    local: datetime,
    now: datetime,
) -> int:
    recipients = await resolve_recipients(
        session, bot_id=bot_id, owner_actor_id=owner_actor_id, spec=spec, audience="managers"
    )
    if not recipients:
        return 0
    day = local.date().isoformat()
    keys = {chat: dedupe_key(bot_id, schedule.id, day, chat) for chat in recipients}
    existing = set(
        (
            await session.execute(
                select(OutboundMessageRow.dedupe_key).where(
                    OutboundMessageRow.bot_id == bot_id,
                    OutboundMessageRow.dedupe_key.in_(list(keys.values())),
                )
            )
        ).scalars()
    )
    pending = [chat for chat in recipients if keys[chat] not in existing]
    if not pending:  # every tick after the first: no report is built
        return 0
    store = PgStore(session, bot_id, LIVE, owner_actor_id)
    overview = await reporting.overview(store, spec, PERIODS[schedule.kind], now)
    text = report_text(schedule, render_overview_text(overview), local, spec.bot.timezone)
    messages = [Message(chat, text, dedupe_key=keys[chat]) for chat in pending]
    return await enqueue_many(session, bot_id=bot_id, env=LIVE, messages=messages)


async def generate(session: AsyncSession, now: datetime) -> None:
    rows = await session.execute(
        select(Bot, BotModuleRow)
        .join(BotModuleRow, BotModuleRow.bot_id == Bot.id)
        .join(Revision, Revision.id == Bot.active_revision_id)
        .where(
            Revision.bot_id == Bot.id,
            Bot.tg_token_enc.is_not(None),
            BotModuleRow.module == MODULE,
            BotModuleRow.enabled.is_(True),
        )
    )
    for bot, module in rows.all():
        bot_id, owner_actor_id, config = bot.id, bot.owner_actor_id, module.config  # plain values: a
        # savepoint rollback expires the ORM objects and async sessions cannot lazy-load them
        spec = await active_spec(session, bot)
        if spec is None:
            continue
        local = now.astimezone(get_tz(spec.bot.timezone))
        for schedule in effective_schedules(config, True):
            if not is_due(schedule, local):
                continue
            try:
                async with session.begin_nested():
                    inserted = await _send_schedule(
                        session, bot_id, owner_actor_id, spec, schedule, local, now
                    )
            except Exception:
                log.exception("bot %s: scheduled report %s failed", bot_id, schedule.id)
                continue
            if inserted:
                log.info("bot %s: queued scheduled report %s for %d chats", bot_id, schedule.id, inserted)
