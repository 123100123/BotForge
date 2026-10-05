"""Who receives an announcement: audience -> Telegram chat ids (live environment only).

Roles follow ``contracts.Actor.effective_role``: the bot owner (``bots.owner_actor_id``) is a manager
whatever ``bot_users.role`` says, so the owner is never a "customer" and always among "staff" and
"managers", even before they have a ``bot_users`` row.

  everyone     every ``bot_users`` row of the bot
  customers    effective role customer
  staff        effective role staff or manager
  managers     effective role manager (stored managers plus the owner)
  subscribers  actors with a record in ``<cap>.subs`` (every enabled booking capability with
               ``preset="events"``) whose ``data.category`` equals the announcement's category;
               without a category, every subscriber

``group_chat_ids`` are added as they are, but only chats the bot is an active member of
(``bot_chats``), so a stale or mistyped id never becomes a message that can only fail.
Actor ids that are not Telegram chat ids (the seeded demo customers, ``demo-01``) are skipped.
"""

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BookingCapability, BotSpec
from app.db.models import BotChatRow, BotUser, RecordRow

LIVE = "live"
_CHAT_ID = re.compile(r"-?[0-9]+")  # ASCII digits only: \d also matches Persian ones
SUBSCRIPTIONS_SUFFIX = ".subs"


def chat_id_of(actor_id: str | None) -> int | None:
    """The Telegram chat id of a private-chat actor (its actor id), or ``None``."""
    if actor_id is None or not _CHAT_ID.fullmatch(actor_id):
        return None
    return int(actor_id)


def subscription_collections(spec: BotSpec | None) -> list[str]:
    if spec is None:
        return []
    return [
        f"{cap.key}{SUBSCRIPTIONS_SUFFIX}"
        for cap in spec.capabilities
        if isinstance(cap, BookingCapability) and cap.preset == "events" and cap.enabled
    ]


async def _role_actors(
    session: AsyncSession, bot_id: uuid.UUID, audience: str, owner_actor_id: str | None
) -> set[str]:
    rows = (
        await session.execute(
            select(BotUser.actor_id, BotUser.role).where(BotUser.bot_id == bot_id, BotUser.env == LIVE)
        )
    ).all()
    actors: set[str] = set()
    for actor_id, stored in rows:
        role = "manager" if actor_id == owner_actor_id else stored
        if (
            audience == "everyone"
            or (audience == "customers" and role == "customer")
            or (audience == "staff" and role in ("staff", "manager"))
            or (audience == "managers" and role == "manager")
        ):
            actors.add(actor_id)
    if owner_actor_id is not None and audience in ("everyone", "staff", "managers"):
        actors.add(owner_actor_id)
    return actors


async def _subscribers(
    session: AsyncSession, bot_id: uuid.UUID, spec: BotSpec | None, category: str | None
) -> set[str]:
    collections = subscription_collections(spec)
    if not collections:
        return set()
    stmt = select(RecordRow.actor_id).where(
        RecordRow.bot_id == bot_id,
        RecordRow.env == LIVE,
        RecordRow.collection.in_(collections),
        RecordRow.actor_id.is_not(None),
    )
    if category is not None:
        stmt = stmt.where(RecordRow.data["category"].astext == category)
    return {a for a in (await session.execute(stmt.distinct())).scalars() if a is not None}


async def _active_groups(session: AsyncSession, bot_id: uuid.UUID, wanted: Iterable[int]) -> set[int]:
    ids = {int(c) for c in wanted}
    if not ids:
        return set()
    stmt = select(BotChatRow.chat_id).where(
        BotChatRow.bot_id == bot_id, BotChatRow.active.is_(True), BotChatRow.chat_id.in_(ids)
    )
    return set((await session.execute(stmt)).scalars())


async def resolve_recipients(
    session: AsyncSession,
    *,
    bot_id: uuid.UUID,
    owner_actor_id: str | None,
    spec: BotSpec | None,
    audience: str,
    category: str | None = None,
    group_chat_ids: Iterable[int] = (),
) -> list[int]:
    """Distinct chat ids for the audience plus the bot's active groups among ``group_chat_ids``,
    in ascending order (deterministic). An unknown audience resolves to the groups only."""
    if audience == "subscribers":
        actors = await _subscribers(session, bot_id, spec, category)
    else:
        actors = await _role_actors(session, bot_id, audience, owner_actor_id)
    chats = {c for c in (chat_id_of(a) for a in actors) if c is not None}
    chats |= await _active_groups(session, bot_id, group_chat_ids)
    return sorted(chats)
