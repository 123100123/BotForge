"""Announcements: the owner broadcasts a text to an audience of the bot's Telegram users.

``POST`` stores the announcement in status ``queued`` and returns at once; the notification ticker's
``announcements`` generator fans it out into the outbox (one message per recipient) on its next tick,
sets ``recipients`` and moves the status to ``sent``. Zero recipients is a normal outcome, not an
error. With ``NOTIFICATIONS_TICKER`` off nothing is fanned out and the announcement stays queued.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot, http_error
from app.db.models import AnnouncementRow, Bot
from app.db.session import get_session
from app.schemas.business import AnnouncementIn, AnnouncementOut

router = APIRouter(tags=["announcements"])

LIST_LIMIT = 50
CATEGORY_MAX_CHARS = 40
INVALID_CATEGORY = ("invalid_category", "دسته‌بندی اطلاعیه حداکثر ۴۰ نویسه است.")


def _out(row: AnnouncementRow) -> AnnouncementOut:
    return AnnouncementOut(
        id=row.id,
        text=row.text,
        audience=row.audience,  # type: ignore[arg-type]
        recipients=row.recipients,
        created_at=row.created_at,
        status=row.status,
    )


@router.post("/bots/{bot_id}/announcements", response_model=AnnouncementOut, status_code=201)
async def create_announcement(
    body: AnnouncementIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> AnnouncementOut:
    category = body.category.strip() if body.category and body.category.strip() else None
    if category is not None and len(category) > CATEGORY_MAX_CHARS:  # announcements.category is 40 chars
        raise http_error(422, INVALID_CATEGORY)
    row = AnnouncementRow(
        bot_id=bot.id,
        text=body.text,
        audience=body.audience,
        category=category,
        group_chat_ids=list(dict.fromkeys(body.group_chat_ids)),
        recipients=0,
        status="queued",
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return _out(row)


@router.get("/bots/{bot_id}/announcements", response_model=list[AnnouncementOut])
async def list_announcements(
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> list[AnnouncementOut]:
    rows = await session.execute(
        select(AnnouncementRow)
        .where(AnnouncementRow.bot_id == bot.id)
        .order_by(AnnouncementRow.created_at.desc(), AnnouncementRow.id)
        .limit(LIST_LIMIT)
    )
    return [_out(r) for r in rows.scalars().all()]
