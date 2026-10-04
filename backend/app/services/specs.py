"""Loading a bot's revision spec for the adapters (webhook, simulator, admin actions)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec
from app.db.models import Bot, Revision


async def get_bot_revision(session: AsyncSession, bot: Bot, revision_id: uuid.UUID | None) -> Revision | None:
    """Revision ``revision_id`` if it belongs to ``bot`` (the active one when ``None``), else ``None``.

    The bot check matters: ``bots.active_revision_id`` and revision ids are plain foreign keys, so a
    mismatched id must never serve another bot's spec.
    """
    target = bot.active_revision_id if revision_id is None else revision_id
    if target is None:
        return None
    revision = await session.get(Revision, target)
    if revision is None or revision.bot_id != bot.id:
        return None
    return revision


async def load_active_spec(session: AsyncSession, bot: Bot) -> tuple[Revision, BotSpec] | None:
    revision = await get_bot_revision(session, bot, None)
    if revision is None:
        return None
    return revision, BotSpec.model_validate(revision.spec)
