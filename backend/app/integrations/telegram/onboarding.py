"""Connecting and disconnecting an owner's Telegram bot (roadmap: Telegram Integration, onboarding).

``connect`` verifies the token with ``getMe``, refuses a Telegram bot that another BotForge bot
already uses, stores the token Fernet-encrypted, generates the per-bot webhook secret and registers
``{PUBLIC_BASE_URL}/tg/{bot_id}``. Nothing here returns or logs the token or the secret.

The caller's session is the unit of work: ``connect`` and ``disconnect`` commit on success. On any
failure the session is rolled back, so a failed ``setWebhook`` leaves the bot exactly as it was.
"""

import logging
import re
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot
from app.integrations.telegram import texts
from app.integrations.telegram.client import TelegramError, TelegramProvider
from app.security.crypto import (
    TokenCryptoError,
    decrypt_token,
    encrypt_token,
    generate_webhook_secret,
)

log = logging.getLogger(__name__)

# "<bot id>:<secret>" as BotFather issues it; checked before any network call. ASCII only ("\d" would
# admit other scripts' digits), and never shorter than what the log redaction (app.security.redact)
# recognizes as a token, so every token held here is one the safety net can catch.
TOKEN_FORMAT = re.compile(r"^[0-9]{6,}:[A-Za-z0-9_-]{30,}$")


class OnboardingError(Exception):
    """A Telegram connection problem the owner should see. ``message`` is Persian."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TelegramStatus:
    connected: bool
    username: str | None
    bot_link: str | None
    owner_linked: bool
    owner_link: str | None
    last_error: str | None


def status_of(bot: Bot) -> TelegramStatus:
    connected = bot.tg_token_enc is not None
    username = bot.tg_username if connected else None
    return TelegramStatus(
        connected=connected,
        username=username,
        bot_link=f"https://t.me/{username}" if username else None,
        owner_linked=bot.owner_actor_id is not None,
        owner_link=(
            f"https://t.me/{username}?start=owner_{bot.owner_link_code}"
            if username and bot.owner_link_code
            else None
        ),
        last_error=bot.tg_last_error,
    )


def _status_after_connect(bot: Bot) -> str:
    if bot.status == "paused":
        return "paused"
    return "live" if bot.active_revision_id is not None else "draft"


def _webhook_url(public_base_url: str, bot: Bot) -> str:
    base = (public_base_url or "").strip().rstrip("/")
    host = base.removeprefix("https://").split("/", 1)[0].split(":", 1)[0].lower()
    if not base.startswith("https://") or host in ("", "localhost", "127.0.0.1", "0.0.0.0"):
        raise OnboardingError(503, "public_url_missing", texts.PUBLIC_URL_MISSING)
    return f"{base}/tg/{bot.id}"


def _telegram_failure(exc: TelegramError, *, invalid_token_possible: bool = False) -> OnboardingError:
    if exc.network:
        return OnboardingError(502, "telegram_unreachable", texts.TELEGRAM_UNREACHABLE)
    if invalid_token_possible and exc.error_code in (401, 404):
        return OnboardingError(400, "invalid_token", texts.INVALID_TOKEN)
    return OnboardingError(502, "telegram_error", texts.TELEGRAM_REJECTED.format(description=exc.description))


async def connect(
    session: AsyncSession, bot: Bot, token: str, provider: TelegramProvider, *, public_base_url: str
) -> None:
    token = token.strip()
    if not TOKEN_FORMAT.fullmatch(token):
        raise OnboardingError(400, "invalid_token", texts.INVALID_TOKEN)
    url = _webhook_url(public_base_url, bot)
    client = provider(token)
    try:
        me = await client.get_me()
    except TelegramError as exc:
        raise _telegram_failure(exc, invalid_token_possible=True) from None
    tg_bot_id, username = me.get("id"), me.get("username")
    if not isinstance(tg_bot_id, int) or not isinstance(username, str) or not username:
        raise OnboardingError(400, "invalid_token", texts.INVALID_TOKEN)

    taken = (
        await session.execute(select(Bot.id).where(Bot.tg_bot_id == tg_bot_id, Bot.id != bot.id))
    ).first()
    if taken is not None:
        raise OnboardingError(409, "telegram_bot_in_use", texts.TOKEN_IN_USE)

    try:
        token_enc = encrypt_token(token)
    except TokenCryptoError:
        log.error("TOKEN_ENC_KEY is missing or invalid; cannot store a Telegram token")
        raise OnboardingError(503, "server_misconfigured", texts.SERVER_MISCONFIGURED) from None

    previous_token_enc, previous_tg_bot_id = bot.tg_token_enc, bot.tg_bot_id
    bot.tg_token_enc = token_enc
    bot.tg_bot_id = tg_bot_id
    bot.tg_username = username
    bot.tg_webhook_secret = generate_webhook_secret()
    bot.tg_last_error = None
    bot.status = _status_after_connect(bot)
    # A fresh single-use owner link on every connect: this is how the owner gets a new one after a
    # link was consumed, and reconnecting revokes a link that leaked before it was used.
    bot.owner_link_code = secrets.token_urlsafe(12)
    try:
        await session.flush()
    except IntegrityError:  # lost a race for the same Telegram bot id
        await session.rollback()
        raise OnboardingError(409, "telegram_bot_in_use", texts.TOKEN_IN_USE) from None

    try:
        await client.set_webhook(url, bot.tg_webhook_secret)
    except TelegramError as exc:
        await session.rollback()
        raise _telegram_failure(exc) from None
    await session.commit()

    if previous_token_enc and previous_tg_bot_id != tg_bot_id:
        await drop_webhook(previous_token_enc, provider)  # the owner switched to another Telegram bot


async def disconnect(session: AsyncSession, bot: Bot, provider: TelegramProvider) -> None:
    if bot.tg_token_enc:
        await drop_webhook(bot.tg_token_enc, provider)
    bot.tg_token_enc = None
    bot.tg_webhook_secret = None
    bot.tg_username = None
    bot.tg_bot_id = None
    bot.tg_last_error = None
    if bot.status != "paused":
        bot.status = "draft"
    await session.commit()


async def drop_webhook(token_enc: str, provider: TelegramProvider) -> None:
    """Best effort ``deleteWebhook``: a dead token or an unreachable Telegram must not block a disconnect."""
    try:
        await provider(decrypt_token(token_enc)).delete_webhook()
    except TokenCryptoError:
        log.warning("could not decrypt the stored Telegram token while removing a webhook")
    except TelegramError as exc:
        log.warning("deleteWebhook failed: %s", exc.description)
