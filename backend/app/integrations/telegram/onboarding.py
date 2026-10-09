"""Connecting and disconnecting an owner's Telegram bot (roadmap: Telegram Integration, onboarding).

``connect`` verifies the token with ``getMe``, refuses a Telegram bot that another BotForge bot
already uses (on this server: ``bots.tg_bot_id`` is unique; on another server: ``getWebhookInfo`` and
a short ``getUpdates`` probe, because Telegram is the only state two servers share), stores the
token Fernet-encrypted, generates the per-bot webhook secret and registers
``{PUBLIC_BASE_URL}/tg/{bot_id}``. Nothing here returns or logs the token or the secret. In polling
mode (``TELEGRAM_MODE=polling``) no webhook is registered: connect removes any webhook instead and the
poller (``poller.py``) fetches the bot's updates.
``scripts/reregister_webhooks.py`` moves registered webhooks to a new ``PUBLIC_BASE_URL`` with the
same ``webhook_url`` and ``status_after_connect``, keeping each bot's secret and owner link.

Bale («بله», ``platform="bale"``; see ``platforms.py``): the same flow against Bale's API, with these
differences. The webhook is ``{PUBLIC_BASE_URL}/bale/{bot_id}/{secret}`` (Bale sends no secret
header, so the secret is in the path) and is registered in either ``TELEGRAM_MODE`` (polling is
Telegram-only); ``setWebhook`` gets only the URL. The other-server checks (``getWebhookInfo`` and the
probe) are Telegram-only. A 403 from ``getMe`` means an invalid token. The uniqueness rule is per
platform: ``(platform, tg_bot_id)``. Links use ``ble.ir``.

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
from app.integrations.telegram.client import (
    ALLOWED_UPDATES,
    COMPETING_POLLER,
    TelegramApi,
    TelegramError,
    TelegramProvider,
)
from app.integrations.telegram.commands import register_default_commands
from app.integrations.telegram.platforms import (
    BALE_WEBHOOK_PORTS,
    DEFAULT_PLATFORM,
    Platform,
    as_platform,
    bot_link,
    is_invalid_token,
    localize,
)
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
# Seconds connect's getUpdates probe waits for a competing poller to end it (see _refuse_if_used_elsewhere).
PROBE_TIMEOUT = 6


class OnboardingError(Exception):
    """A Telegram connection problem the owner should see. ``message`` is Persian."""

    def __init__(self, status: int, code: str, message: str, platform: str = DEFAULT_PLATFORM) -> None:
        message = localize(message, platform)
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TelegramStatus:
    platform: Platform
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
    platform = as_platform(bot.platform)
    return TelegramStatus(
        platform=platform,
        connected=connected,
        username=username,
        bot_link=bot_link(platform, username) if username else None,
        owner_linked=bot.owner_actor_id is not None,
        owner_link=bot_link(platform, username, f"owner_{code}") if username and code else None,
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


def webhook_base_url(public_base_url: str, platform: str = DEFAULT_PLATFORM) -> str:
    """``PUBLIC_BASE_URL`` without surrounding whitespace and trailing slashes.

    ``OnboardingError`` (503, ``public_url_missing``) unless it is an https URL whose host is not
    localhost: Telegram and Bale deliver updates only to a public https address. Bale also accepts
    only the ports 443 and 88.
    """
    base = (public_base_url or "").strip().rstrip("/")
    authority = base.removeprefix("https://").split("/", 1)[0]
    host, _, port = authority.partition(":")
    if not base.startswith("https://") or host.lower() in ("", "localhost", "127.0.0.1", "0.0.0.0"):
        raise OnboardingError(503, "public_url_missing", texts.PUBLIC_URL_MISSING, platform)
    if as_platform(platform) == "bale" and port and not (port.isdigit() and int(port) in BALE_WEBHOOK_PORTS):
        raise OnboardingError(503, "public_url_missing", texts.BALE_PORT_UNSUPPORTED, platform)
    return base


def webhook_url(
    public_base_url: str,
    bot_id: uuid.UUID | str,
    platform: str = DEFAULT_PLATFORM,
    secret: str | None = None,
) -> str:
    """Where the platform posts the bot's updates (``app.api.webhook``), checked like
    ``webhook_base_url``: ``{PUBLIC_BASE_URL}/tg/{bot_id}`` for Telegram (the secret travels in a
    header), ``{PUBLIC_BASE_URL}/bale/{bot_id}/{secret}`` for Bale. The Bale URL holds the secret:
    never log it."""
    base = webhook_base_url(public_base_url, platform)
    if as_platform(platform) == "bale":
        if not secret:
            raise ValueError("a Bale webhook URL needs the bot's webhook secret")
        return f"{base}/bale/{bot_id}/{secret}"
    return f"{base}/tg/{bot_id}"


def _telegram_failure(
    exc: TelegramError, platform: str = DEFAULT_PLATFORM, *, invalid_token_possible: bool = False
) -> OnboardingError:
    if exc.network:
        return OnboardingError(502, "telegram_unreachable", texts.TELEGRAM_UNREACHABLE, platform)
    if invalid_token_possible and is_invalid_token(platform, exc.error_code):
        return OnboardingError(400, "invalid_token", texts.INVALID_TOKEN, platform)
    message = localize(texts.TELEGRAM_REJECTED, platform).format(description=exc.description)
    return OnboardingError(502, "telegram_error", message, platform)


def _used_elsewhere() -> OnboardingError:
    return OnboardingError(409, "telegram_bot_in_use_elsewhere", texts.TOKEN_IN_USE_ELSEWHERE)


def _is_own_connection(bot: Bot, token: str, tg_bot_id: int) -> bool:
    """Whether this very bot already stores this token: this server's poller may be polling it right
    now, and would make the probe see a competing consumer that is only ourselves."""
    if bot.tg_token_enc is None or bot.tg_bot_id != tg_bot_id:
        return False
    try:
        return decrypt_token(bot.tg_token_enc) == token
    except TokenCryptoError:
        return False


async def _refuse_if_used_elsewhere(
    bot: Bot, token: str, tg_bot_id: int, client: TelegramApi, public_base_url: str
) -> None:
    """Telegram is the only state two BotForge servers share, so ask it whether another server serves
    this Telegram bot. Runs after ``getMe`` and before anything is stored.

    1. ``getWebhookInfo``: a webhook that is not this bot's own ``webhook_url`` belongs to another
       server. An own webhook (a reconnect here) is fine, and with any webhook set no one can be
       polling (``getUpdates`` fails), so the probe is skipped.
    2. Probe: one ``getUpdates(limit=1)`` with no offset, so nothing is confirmed and its result is
       dropped. Telegram ends the older of two concurrent ``getUpdates`` with 409 "terminated by
       other getUpdates request": a competing poller re-polls within the probe's window and ends
       ours. Skipped when this bot already stores this token (our own poller would be the
       "competitor").

    ``OnboardingError`` (409, ``telegram_bot_in_use_elsewhere``) when either finds another server.
    Other Telegram errors of the probe are ignored: the calls that follow report them.
    """
    try:
        info = await client.get_webhook_info()
    except TelegramError as exc:
        raise _telegram_failure(exc) from None
    hook = info.get("url")
    if isinstance(hook, str) and hook:
        try:
            own = webhook_url(public_base_url, bot.id)
        except OnboardingError:  # no usable public URL here: no webhook can be ours
            own = None
        if hook != own:
            raise _used_elsewhere()
        return
    if _is_own_connection(bot, token, tg_bot_id):
        return
    try:
        await client.get_updates(offset=None, timeout=PROBE_TIMEOUT, allowed_updates=ALLOWED_UPDATES, limit=1)
    except TelegramError as exc:
        if exc.error_code == 409 and COMPETING_POLLER in exc.description.lower():
            raise _used_elsewhere() from None
        log.warning("Telegram connect probe failed: %s", exc.description)


async def connect(
    session: AsyncSession,
    bot: Bot,
    token: str,
    provider: TelegramProvider,
    *,
    public_base_url: str,
    mode: TelegramMode = "webhook",
    platform: Platform = DEFAULT_PLATFORM,
) -> None:
    """``mode="polling"`` (``TELEGRAM_MODE``) registers no webhook and needs no public https
    ``PUBLIC_BASE_URL``: it calls ``deleteWebhook`` instead (dropping queued updates, as the webhook
    connect does), and the poller picks the bot up on its next pass. Everything else is identical.
    ``platform="bale"`` always registers its webhook (module docstring)."""
    platform = as_platform(platform)
    use_webhook = mode == "webhook" or platform == "bale"
    token = token.strip()
    if not TOKEN_FORMAT.fullmatch(token):
        raise OnboardingError(400, "invalid_token", texts.INVALID_TOKEN, platform)
    if use_webhook:
        webhook_base_url(public_base_url, platform)  # fail before any network call
    client = provider(token, platform)
    try:
        me = await client.get_me()
    except TelegramError as exc:
        raise _telegram_failure(exc, platform, invalid_token_possible=True) from None
    tg_bot_id, username = me.get("id"), me.get("username")
    if not isinstance(tg_bot_id, int) or not isinstance(username, str) or not username:
        raise OnboardingError(400, "invalid_token", texts.INVALID_TOKEN, platform)

    in_use = localize(texts.TOKEN_IN_USE, platform).format(username=username)
    taken = (
        await session.execute(
            select(Bot.id).where(Bot.platform == platform, Bot.tg_bot_id == tg_bot_id, Bot.id != bot.id)
        )
    ).first()
    if taken is not None:
        raise OnboardingError(409, "telegram_bot_in_use", in_use)
    if platform == "telegram":  # getWebhookInfo and the probe are Telegram's (module docstring)
        await _refuse_if_used_elsewhere(bot, token, tg_bot_id, client, public_base_url)

    try:
        token_enc = encrypt_token(token)
    except TokenCryptoError:
        log.error("TOKEN_ENC_KEY is missing or invalid; cannot store a Telegram token")
        raise OnboardingError(503, "server_misconfigured", texts.SERVER_MISCONFIGURED, platform) from None

    previous_token_enc, previous_tg_bot_id = bot.tg_token_enc, bot.tg_bot_id
    previous_platform = as_platform(bot.platform)
    bot.platform = platform
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
        raise OnboardingError(409, "telegram_bot_in_use", in_use) from None

    try:
        if use_webhook:
            url = webhook_url(public_base_url, bot.id, platform, bot.tg_webhook_secret)
            # Bale has no secret header: the secret is in the URL, and nothing else is sent.
            await client.set_webhook(url, bot.tg_webhook_secret if platform == "telegram" else None)
        else:  # polling: a webhook left from webhook mode would make getUpdates fail with 409
            await client.delete_webhook(drop_pending_updates=True)
    except TelegramError as exc:
        await session.rollback()
        raise _telegram_failure(exc, platform) from None
    await session.commit()

    await register_default_commands(client)  # best effort: never fails the connect
    if previous_token_enc and (previous_tg_bot_id != tg_bot_id or previous_platform != platform):
        # the owner switched to another bot (or messenger)
        await drop_webhook(previous_token_enc, provider, previous_platform)


async def disconnect(session: AsyncSession, bot: Bot, provider: TelegramProvider) -> None:
    """Forget the token and the webhook, unlink the owner and revoke any owner-link code."""
    if bot.tg_token_enc:
        await drop_webhook(bot.tg_token_enc, provider, as_platform(bot.platform))
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


async def drop_webhook(
    token_enc: str, provider: TelegramProvider, platform: Platform = DEFAULT_PLATFORM
) -> None:
    """Best effort ``deleteWebhook``: a dead token or an unreachable Telegram must not block a disconnect."""
    try:
        await provider(decrypt_token(token_enc), platform).delete_webhook()
    except TokenCryptoError:
        log.warning("could not decrypt the stored Telegram token while removing a webhook")
    except TelegramError as exc:
        log.warning("deleteWebhook failed: %s", exc.description)
