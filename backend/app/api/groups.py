"""Telegram groups of a bot: ``GET /bots/{bot_id}/groups`` and
``POST /bots/{bot_id}/groups/{chat_id}/publish``.

The groups are the chats the bot was added to, recorded from Telegram's ``my_chat_member`` updates
(``app.api.webhook``); this router never creates one. Publishing posts the card of one event (an item
of an enabled booking capability with the events preset, rendered by ``services/group_cards.py``
from the live data) to one of those groups: the card is queued in the notification outbox (env live,
no dedupe key: publishing again posts again once the first card is sent, but not while an identical
card is still queued, see ``outbox.enqueue_unless_queued``) and the notification ticker sends it.

SECURITY: both routes resolve the bot through ``get_owned_bot`` (session cookie, CSRF for the POST,
ownership; another owner's bot is the 404 of a missing one). A message can only go to a chat that is
recorded for THIS bot and still active: an unknown chat id is a 404 and a chat the bot has left a 409,
so the endpoint cannot be used to make the bot post anywhere else. The card text is plain (the
ticker escapes it); its only button is the event's ``book:<item id>``.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot, http_error
from app.db.models import Bot, BotChatRow
from app.db.session import get_session
from app.notifications.outbox import enqueue_unless_queued
from app.runtime.ctx import MAX_RECORD_ID
from app.runtime.pg_store import PgStore
from app.schemas.business import GroupOut, PublishIn, PublishOut
from app.services.group_cards import find_events_capability, render_for_item
from app.services.specs import load_active_spec

router = APIRouter(tags=["groups"])

MAX_GROUPS = 200
# bot_chats.chat_id is a bigint: anything outside it is a 422, never a database error
ChatId = Annotated[int, Path(ge=-(2**63), le=2**63 - 1)]
GROUP_NOT_FOUND = ("group_not_found", "این گروه پیدا نشد. ربات را به گروه اضافه کنید.")
GROUP_INACTIVE = ("group_inactive", "ربات دیگر عضو این گروه نیست یا اجازهٔ ارسال پیام ندارد.")
EVENT_NOT_FOUND = ("event_not_found", "رویداد پیدا نشد.")
PUBLISH_QUEUED = "کارت رویداد در صف ارسال قرار گرفت"
PUBLISH_ALREADY_QUEUED = "این رویداد همین حالا در صف ارسال به این گروه است."


def _out(row: BotChatRow) -> GroupOut:
    return GroupOut(
        chat_id=row.chat_id,
        title=row.title,
        kind=row.kind,  # type: ignore[arg-type]  # written only from webhook.CHAT_KINDS
        added_at=row.added_at,
        active=row.active,
    )


@router.get("/bots/{bot_id}/groups", response_model=list[GroupOut])
async def list_groups(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> list[GroupOut]:
    """The bot's groups: active ones first, then by when the bot was added, newest first."""
    rows = await session.execute(
        select(BotChatRow)
        .where(BotChatRow.bot_id == bot.id)
        .order_by(BotChatRow.active.desc(), BotChatRow.added_at.desc(), BotChatRow.chat_id)
        .limit(MAX_GROUPS)
    )
    return [_out(row) for row in rows.scalars().all()]


@router.post("/bots/{bot_id}/groups/{chat_id}/publish", response_model=PublishOut)
async def publish_to_group(
    chat_id: ChatId,
    body: PublishIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> PublishOut:
    """Queue the card of event ``body.record_id`` (a record of ``body.collection``) for the group."""
    chat = await session.get(BotChatRow, (bot.id, chat_id))
    if chat is None:
        raise http_error(404, GROUP_NOT_FOUND)
    if not chat.active:
        raise http_error(409, GROUP_INACTIVE)
    active = await load_active_spec(session, bot)
    spec = active[1] if active is not None else None
    cap = find_events_capability(spec, body.collection) if spec is not None else None
    if spec is None or cap is None or body.record_id > MAX_RECORD_ID:  # records.id is a bigint
        raise http_error(404, EVENT_NOT_FOUND)
    store = PgStore(session, bot.id, "live", owner_actor_id=bot.owner_actor_id)
    card = await render_for_item(store, spec, cap, body.record_id, now=datetime.now(UTC))
    if card is None:
        raise http_error(404, EVENT_NOT_FOUND)
    text, buttons = card
    queued = await enqueue_unless_queued(
        session, bot_id=bot.id, env="live", chat_id=chat.chat_id, text=text, buttons=buttons
    )
    if not queued:
        return PublishOut(queued=False, message=PUBLISH_ALREADY_QUEUED)
    return PublishOut(queued=True, message=PUBLISH_QUEUED)
