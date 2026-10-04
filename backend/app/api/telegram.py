"""Telegram connection settings: status, connect (token), disconnect.

The response never contains the token or the webhook secret; ``connected`` is derived from the
stored (encrypted) token and the links are built from the public bot username.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.config import get_settings
from app.db.models import Bot
from app.db.session import get_session
from app.integrations.telegram import onboarding
from app.integrations.telegram.client import TelegramProvider, get_telegram_provider

router = APIRouter(tags=["telegram"])


class ConnectBody(BaseModel):
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TelegramStatusOut(BaseModel):
    connected: bool
    username: str | None
    bot_link: str | None
    owner_linked: bool
    owner_link: str | None
    last_error: str | None


def _out(bot: Bot) -> TelegramStatusOut:
    status = onboarding.status_of(bot)
    return TelegramStatusOut(
        connected=status.connected,
        username=status.username,
        bot_link=status.bot_link,
        owner_linked=status.owner_linked,
        owner_link=status.owner_link,
        last_error=status.last_error,
    )


@router.get("/bots/{bot_id}/telegram", response_model=TelegramStatusOut)
async def telegram_status(bot: Bot = Depends(get_owned_bot)) -> TelegramStatusOut:
    return _out(bot)


@router.post("/bots/{bot_id}/telegram/connect", response_model=TelegramStatusOut)
async def telegram_connect(
    body: ConnectBody,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    telegram: TelegramProvider = Depends(get_telegram_provider),
) -> TelegramStatusOut:
    try:
        await onboarding.connect(
            session, bot, body.token, telegram, public_base_url=get_settings().PUBLIC_BASE_URL
        )
    except onboarding.OnboardingError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from None
    return _out(bot)


@router.delete("/bots/{bot_id}/telegram", response_model=TelegramStatusOut)
async def telegram_disconnect(
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    telegram: TelegramProvider = Depends(get_telegram_provider),
) -> TelegramStatusOut:
    await onboarding.disconnect(session, bot, telegram)
    return _out(bot)
