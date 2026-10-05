"""Connecting and disconnecting an owner's Telegram bot (roadmap: Telegram Integration, onboarding).

``connect`` verifies the token with ``getMe``, refuses a Telegram bot that another BotForge bot
already uses, stores the token Fernet-encrypted, generates the per-bot webhook secret and registers
``{PUBLIC_BASE_URL}/tg/{bot_id}``. Nothing here returns or logs the token or the secret. In polling
mode (``TELEGRAM_MODE=polling``) no webhook is registered: connect removes any webhook instead and the
poller (``poller.py``) fetches the bot's updates.
``scripts/reregister_webhooks.py`` moves registered webhooks to a new ``PUBLIC_BASE_URL`` with the
same ``webhook_url`` and ``status_after_connect``, keeping each bot's secret and owner link.

Owner link. The owner's Telegram account is linked by opening ``t.me/<bot>?start=owner_<code>``
(handled by the webhook). A code links an owner only while none is linked: it establishes the owner
and never replaces one (``armed_owner_code``). Every successful ``connect`` unlinks the owner and
arms a fresh single-use code; ``disconnect`` unlinks the owner and revokes the code. Changing the
linked Telegram account is therefore always "disconnect, reconnect, open the new link", and a code
that leaked earlier is dead after either action.

The caller's session is the unit of work: ``connect`` and ``disconnect`` commit on success. On any
failure the session is rolled back, so a failed ``setWebhook`` leaves the bot exactly as it was.
"""

import logging
import re
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import TelegramMode
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


def armed_owner_code(bot: Bot) -> str | None:
    """The owner-link code that links an owner right now, or ``None``.

    Only while no owner is linked: a code establishes the owner, it never replaces one. The webhook
    accepts exactly this code and ``status_of`` shows exactly this code, so the Settings page never
    hides a usable link and never shows a dead one.
    """
    if bot.owner_actor_id is not None or not bot.owner_link_code:
        return None
    return bot.owner_link_code


def status_of(bot: Bot) -> TelegramStatus:
    connected = bot.tg_token_enc is not None
    username = bot.tg_username if connected else None
    code = armed_owner_code(bot)
    return TelegramStatus(
        connected=connected,
        username=username,
        bot_link=f"https://t.me/{username}" if username else None,
        owner_linked=bot.owner_actor_id is not None,
        owner_link=f"https://t.me/{username}?start=owner_{code}" if username and code else None,
        last_error=bot.tg_last_error,
    )


def _reset_owner_link(bot: Bot, code: str | None) -> None:
    """Unlink the owner and arm ``code`` (``None``: arm nothing).

    Both columns are written even when they look unchanged. ``bot`` was read at the start of the
    request, and the webhook may have linked an owner since; without ``flag_modified`` the ORM would
    leave out a column whose value it believes unchanged, and that owner would stay linked. With
    the webhook's compare-and-set this makes connect and disconnect win over a link they race with,
    without holding the bot's lock across the Telegram calls.
    """
    bot.owner_actor_id = None
    bot.owner_link_code = code
    flag_modified(bot, "owner_actor_id")
    flag_modified(bot, "owner_link_code")


def _reset_poll_offset(bot: Bot) -> None:
    """Polling starts over for a new token: update ids, and so offsets, belong to one Telegram bot.

    Always written (``flag_modified``), as in ``_reset_owner_link``: the poller of the previous token
    may have saved an offset after ``bot`` was read, and the ORM would leave out a column it believes
    unchanged, carrying that offset over to the new token (where it could confirm, that is drop, the
    new bot's first updates). The poller saves by compare-and-set on the token, so nothing it writes
    after this commit survives either."""
    bot.tg_poll_offset = None
    flag_modified(bot, "tg_poll_offset")


def status_after_connect(bot: Bot) -> str:
    """The status of a bot whose webhook was just registered: a paused bot stays paused, otherwise
    it is live with an active revision and draft without one. ``scripts/reregister_webhooks.py``
    applies the same rule when it moves a webhook to a new host."""
    if bot.status == "paused":
        return "paused"
    return "live" if bot.active_revision_id is not None else "draft"


def webhook_base_url(public_base_url: str) -> str:
    """``PUBLIC_BASE_URL`` without surrounding whitespace and trailing slashes.

    ``OnboardingError`` (503, ``public_url_missing``) unless it is an https URL whose host is not
    localhost: Telegram delivers updates only to a public https address.
    """
    base = (public_base_url or "").strip().rstrip("/")
    host = base.removeprefix("https://").split("/", 1)[0].split(":", 1)[0].lower()
    if not base.startswith("https://") or host in ("", "localhost", "127.0.0.1", "0.0.0.0"):
        raise OnboardingError(503, "public_url_missing", texts.PUBLIC_URL_MISSING)
    return base


def webhook_url(public_base_url: str, bot_id: uuid.UUID | str) -> str:
    """``{PUBLIC_BASE_URL}/tg/{bot_id}``: where Telegram posts the bot's updates (``app.api.webhook``).
    Checked like ``webhook_base_url``."""
    return f"{webhook_base_url(public_base_url)}/tg/{bot_id}"


def _telegram_failure(exc: TelegramError, *, invalid_token_possible: bool = False) -> OnboardingError:
    if exc.network:
        return OnboardingError(502, "telegram_unreachable", texts.TELEGRAM_UNREACHABLE)
    if invalid_token_possible and exc.error_code in (401, 404):
        return OnboardingError(400, "invalid_token", texts.INVALID_TOKEN)
    return OnboardingError(502, "telegram_error", texts.TELEGRAM_REJECTED.format(description=exc.description))


async def connect(
    session: AsyncSession,
    bot: Bot,
    token: str,
    provider: TelegramProvider,
    *,
    public_base_url: str,
    mode: TelegramMode = "webhook",
) -> None:
    """``mode="polling"`` (``TELEGRAM_MODE``) registers no webhook and needs no public https
    ``PUBLIC_BASE_URL``: it calls ``deleteWebhook`` instead (dropping queued updates, as the webhook
    connect does), and the poller picks the bot up on its next pass. Everything else is identical."""
    token = token.strip()
    if not TOKEN_FORMAT.fullmatch(token):
        raise OnboardingError(400, "invalid_token", texts.INVALID_TOKEN)
    url = webhook_url(public_base_url, bot.id) if mode == "webhook" else None
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
    _reset_poll_offset(bot)
    bot.status = status_after_connect(bot)
    # Every connect starts a new owner link: the owner is unlinked and a fresh single-use code is
    # armed (the Settings page shows it). This is how the owner links again, or links another
    # Telegram account, and it revokes a code that leaked before it was used.
    _reset_owner_link(bot, secrets.token_urlsafe(12))
    try:
        await session.flush()
    except IntegrityError:  # lost a race for the same Telegram bot id
        await session.rollback()
        raise OnboardingError(409, "telegram_bot_in_use", texts.TOKEN_IN_USE) from None

    try:
        if url is not None:
            await client.set_webhook(url, bot.tg_webhook_secret)
        else:  # polling: a webhook left from webhook mode would make getUpdates fail with 409
            await client.delete_webhook(drop_pending_updates=True)
    except TelegramError as exc:
        await session.rollback()
        raise _telegram_failure(exc) from None
    await session.commit()

    if previous_token_enc and previous_tg_bot_id != tg_bot_id:
        await drop_webhook(previous_token_enc, provider)  # the owner switched to another Telegram bot


async def disconnect(session: AsyncSession, bot: Bot, provider: TelegramProvider) -> None:
    """Forget the token and the webhook, unlink the owner and revoke any owner-link code."""
    if bot.tg_token_enc:
        await drop_webhook(bot.tg_token_enc, provider)
    bot.tg_token_enc = None
    bot.tg_webhook_secret = None
    bot.tg_username = None
    bot.tg_bot_id = None
    bot.tg_last_error = None
    _reset_poll_offset(bot)
    if bot.status != "paused":
        bot.status = "draft"
    _reset_owner_link(bot, None)
    await session.commit()


async def drop_webhook(token_enc: str, provider: TelegramProvider) -> None:
    """Best effort ``deleteWebhook``: a dead token or an unreachable Telegram must not block a disconnect."""
    try:
        await provider(decrypt_token(token_enc)).delete_webhook()
    except TokenCryptoError:
        log.warning("could not decrypt the stored Telegram token while removing a webhook")
    except TelegramError as exc:
        log.warning("deleteWebhook failed: %s", exc.description)
