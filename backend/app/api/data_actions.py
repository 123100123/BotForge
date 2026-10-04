"""Owner actions on booking and request records from the web admin.

``POST /bots/{bot_id}/data/{collection}/{record_id}/actions/{action}`` builds an ``admin`` runtime
event (live, actor = the owner) and runs it through ``dispatch``: the same path as a Telegram owner
button, so a cancel that promotes a waitlisted customer notifies that customer in Telegram.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.botspec.models import BookingCapability, BotSpec, RequestCapability
from app.db.models import Bot
from app.db.session import get_session
from app.integrations.telegram.client import TelegramProvider, get_telegram_provider
from app.runtime.callbacks import ACT_CANCEL, ACT_OWN, make_callback
from app.runtime.contracts import Actor, Outcome, RuntimeEvent
from app.runtime.pg_store import PgStore
from app.services.dispatch import dispatch
from app.services.specs import load_active_spec

router = APIRouter(tags=["data"])

OWNER_ACTOR_FALLBACK = "owner"  # the owner has not linked Telegram yet
OWNER_DISPLAY_NAME = "مدیر"


class ActionOut(BaseModel):
    ok: bool
    outcome: Outcome | None
    message: str


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def callback_for(spec: BotSpec, collection: str, record_id: int, action: str) -> str:
    """The admin callback data for ``action`` on ``collection``; HTTPException if it is not valid."""
    cap = spec.capability(collection)
    if isinstance(cap, BookingCapability):
        if action != ACT_CANCEL:
            raise _err(400, "invalid_action", "برای رزرو فقط عمل «لغو» وجود دارد.")
        return make_callback(cap.key, ACT_CANCEL, str(record_id))
    if isinstance(cap, RequestCapability):
        if action not in {a.key for a in cap.owner_actions}:
            raise _err(400, "invalid_action", "این عمل برای این درخواست تعریف نشده است.")
        return make_callback(cap.key, ACT_OWN, f"{record_id}.{action}")
    raise _err(404, "collection_not_found", "برای این مجموعه عملی تعریف نشده است.")


@router.post("/bots/{bot_id}/data/{collection}/{record_id}/actions/{action}", response_model=ActionOut)
async def run_action(
    collection: str,
    record_id: int,
    action: str,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    telegram: TelegramProvider = Depends(get_telegram_provider),
) -> ActionOut:
    active = await load_active_spec(session, bot)
    if active is None:
        raise _err(409, "no_active_revision", "این ربات هنوز نسخهٔ فعالی ندارد.")
    _, spec = active
    data = callback_for(spec, collection, record_id, action)
    if await PgStore(session, bot.id, "live", bot.owner_actor_id).get_record(collection, record_id) is None:
        raise _err(404, "record_not_found", "این رکورد پیدا نشد.")

    owner = Actor(
        id=bot.owner_actor_id or OWNER_ACTOR_FALLBACK, display_name=OWNER_DISPLAY_NAME, is_owner=True
    )
    event = RuntimeEvent(
        bot_id=str(bot.id), env="live", actor=owner, kind="admin", data=data, now=datetime.now(UTC)
    )
    response = await dispatch(session, bot, spec, event, telegram=telegram)

    outcome = response.outcomes[-1] if response.outcomes else None
    message = "\n\n".join(m.text for m in response.messages if m.to_actor_id == owner.id)
    return ActionOut(
        ok=outcome is not None and outcome.result != "rejected", outcome=outcome, message=message
    )
