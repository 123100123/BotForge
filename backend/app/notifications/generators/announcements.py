"""Announcement fan-out: each ``announcements`` row in status ``queued`` becomes one outbox row per
recipient (``targets.resolve_recipients``), dedupe key ``ann:<announcement_id>:<chat_id>``; then
``recipients`` is set and the status becomes ``sent`` ("fanned out", not "delivered": delivery is
the ticker's job, per outbox row).

Rows are claimed ``FOR UPDATE SKIP LOCKED`` and fanned out in the same transaction as the status
change, so an announcement is fanned out exactly once even with two tickers; the dedupe keys make a
replay after a crash harmless anyway. One announcement that raises is marked ``failed`` (inside a
savepoint, so its partial rows are discarded) instead of blocking the others on every tick.
"""

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnnouncementRow, Bot
from app.notifications.generators import active_spec
from app.notifications.outbox import Message, enqueue_many
from app.notifications.targets import resolve_recipients

log = logging.getLogger(__name__)

LIVE = "live"
BATCH = 20  # announcements per tick
HEADER = "اطلاعیه"


def announcement_text(text: str) -> str:
    return f"{HEADER}\n\n{text}"


async def fan_out(session: AsyncSession, announcement: AnnouncementRow) -> int:
    """Queue the announcement's messages; returns the number of recipients."""
    bot = await session.get(Bot, announcement.bot_id)
    if bot is None:
        return 0
    spec = await active_spec(session, bot) if announcement.audience == "subscribers" else None
    recipients = await resolve_recipients(
        session,
        bot_id=bot.id,
        owner_actor_id=bot.owner_actor_id,
        spec=spec,
        audience=announcement.audience,
        category=announcement.category,
        group_chat_ids=announcement.group_chat_ids or [],
    )
    text = announcement_text(announcement.text)
    messages = [Message(chat, text, dedupe_key=f"ann:{announcement.id}:{chat}") for chat in recipients]
    await enqueue_many(session, bot_id=bot.id, env=LIVE, messages=messages)
    return len(recipients)


async def generate(session: AsyncSession, now: datetime) -> None:
    rows = await session.execute(
        select(AnnouncementRow)
        .where(AnnouncementRow.status == "queued")
        .order_by(AnnouncementRow.created_at, AnnouncementRow.id)
        .limit(BATCH)
        .with_for_update(skip_locked=True)
    )
    for announcement in rows.scalars().all():
        announcement_id = announcement.id  # a savepoint rollback expires the object; no lazy loads
        try:
            async with session.begin_nested():
                announcement.recipients = await fan_out(session, announcement)
                announcement.status = "sent"
        except Exception:
            log.exception("announcement %s: fan-out failed; marked failed", announcement_id)
            await session.execute(
                update(AnnouncementRow)
                .where(AnnouncementRow.id == announcement_id)
                .values(status="failed")
                .execution_options(synchronize_session=False)
            )
