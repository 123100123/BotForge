"""Telegram connection settings: status, connect (token), disconnect, retry after a polling conflict.

The response never contains the token or the webhook secret; ``connected`` is derived from the
stored (encrypted) token and the links are built from the public bot username.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.config import get_settings
from app.db.models import Bot
from app.db.session import get_session
from app.integrations.telegram import onboarding, texts
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
    settings = get_settings()
    try:
        await onboarding.connect(
            session,
            bot,
            body.token,
            telegram,
            public_base_url=settings.PUBLIC_BASE_URL,
            mode=settings.TELEGRAM_MODE,
        )
    except onboarding.OnboardingError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from None
    return _out(bot)


@router.post("/bots/{bot_id}/telegram/retry", response_model=TelegramStatusOut)
async def telegram_retry(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> TelegramStatusOut:
    """After the poller parked the bot because another server polls the same token
    (``POLLING_CONFLICT``): clear that error so the poller's next pass starts polling again. Any other
    error, and a bot that is not parked, is left as it is. Compare-and-set on the stored token."""
    if bot.tg_token_enc is not None:
        await session.execute(
            update(Bot)
            .where(
                Bot.id == bot.id,
                Bot.tg_token_enc == bot.tg_token_enc,
                Bot.tg_last_error.like(f"{texts.POLLING_CONFLICT_PREFIX}%"),
            )
            .values(tg_last_error=None)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        await session.refresh(bot)
    return _out(bot)


@router.delete("/bots/{bot_id}/telegram", response_model=TelegramStatusOut)
async def telegram_disconnect(
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    telegram: TelegramProvider = Depends(get_telegram_provider),
) -> TelegramStatusOut:
    await onboarding.disconnect(session, bot, telegram)
    return _out(bot)
