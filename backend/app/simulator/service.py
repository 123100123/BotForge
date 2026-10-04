"""The web simulator as an adapter over the one runtime (roadmap: Simulator).

Events run with ``env="sandbox"`` through ``dispatch`` (so locking and transactions match Telegram),
against the chosen revision's spec: the active revision, or any draft/active revision of the same
bot. Nothing is sent to Telegram from here. Sandbox rows never mix with live rows (``env`` column).
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec
from app.db.models import Bot, Revision
from app.revisions.service import load_sample_data
from app.runtime.contracts import Actor, RuntimeEvent, RuntimeResponse
from app.runtime.pg_store import advisory_lock
from app.services.dispatch import dispatch
from app.services.specs import get_bot_revision
from app.testing.drivers import DISPLAY_NAMES
from app.testing.scenario import OWNER

Persona = Literal["ali", "sara", "reza", "owner"]
EventKind = Literal["start", "text", "callback"]
SIMULATABLE = ("draft", "active")


class SimulatorError(Exception):
    """A simulator request problem. ``message`` is Persian."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def persona_actor(persona: Persona) -> Actor:
    return Actor(id=persona, display_name=DISPLAY_NAMES[persona], is_owner=persona == OWNER)


async def resolve_revision(session: AsyncSession, bot: Bot, revision_id: uuid.UUID | None) -> Revision:
    """``None`` means the active revision. A given revision must belong to the bot (a foreign or
    unknown id is a plain "not found") and be a draft or the active one."""
    revision = await get_bot_revision(session, bot, revision_id)
    if revision is None:
        if revision_id is None:
            raise SimulatorError(409, "no_active_revision", "این ربات هنوز نسخهٔ فعالی ندارد.")
        raise SimulatorError(404, "revision_not_found", "نسخه پیدا نشد.")
    if revision.status not in SIMULATABLE:
        raise SimulatorError(409, "revision_not_simulatable", "فقط پیش‌نویس یا نسخهٔ فعال قابل آزمایش است.")
    return revision


async def simulate_event(
    session: AsyncSession,
    bot: Bot,
    revision_id: uuid.UUID | None,
    persona: Persona,
    kind: EventKind,
    *,
    text: str | None = None,
    data: str | None = None,
) -> RuntimeResponse:
    if kind == "text" and not text:
        raise SimulatorError(400, "invalid_event", "برای پیام متنی، متن لازم است.")
    if kind == "callback" and not data:
        raise SimulatorError(400, "invalid_event", "برای دکمه، دادهٔ دکمه لازم است.")
    revision = await resolve_revision(session, bot, revision_id)
    spec = BotSpec.model_validate(revision.spec)
    event = RuntimeEvent(
        bot_id=str(bot.id),
        env="sandbox",
        actor=persona_actor(persona),
        kind=kind,
        text=text if kind == "text" else None,
        data=data if kind == "callback" else None,
        now=datetime.now(UTC),
    )
    return await dispatch(session, bot, spec, event)


async def reset_sandbox(session: AsyncSession, bot: Bot, revision_id: uuid.UUID | None) -> int:
    """Delete the bot's sandbox records and sessions, then load the revision's sample data.

    Returns the number of sample records loaded."""
    revision = await resolve_revision(session, bot, revision_id)
    await advisory_lock(session, bot.id)
    loaded = await load_sample_data(session, bot.id, revision, datetime.now(UTC))
    await session.commit()
    return len(loaded)
