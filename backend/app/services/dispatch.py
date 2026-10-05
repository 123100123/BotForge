"""The one way to run the runtime against Postgres (roadmap: Runtime Architecture, Dispatch service).

The Telegram webhook, the simulator endpoint and the admin action endpoint all call ``dispatch``, so
locking, transactions and message delivery are identical for every caller.

Order of operations, and why it matters:

1. take the bot's advisory lock (events for one bot are processed one at a time) and re-read the
   bot; a live Telegram event's ``actor.is_owner`` is set from the owner link read here, and its
   ``actor.role`` from ``bot_users.role`` read here too (whatever the caller put in the event), so
   both are decided at the same moment and no role change lands in the middle of an event (role
   writes take the same lock, see ``app/roles/service.py``). Sandbox events keep the role the
   simulator persona carries; ``admin`` events keep their actor (the authenticated web owner);
2. run ``BotRuntime.handle`` against ``PgStore`` in the caller's session;
3. COMMIT;
4. only then, for ``env="live"``, deliver messages through Telegram.

The commit happens BEFORE delivery. The business state is therefore durable even if Telegram is
down, and a slow Telegram call never holds the advisory lock or an open transaction. The price is
that a delivery failure cannot undo the booking: it is logged and recorded in ``bots.tg_last_error``
(never raised to the caller), and the user can simply press the button again.

Delivery is skipped entirely for the sandbox. For ``kind="admin"`` events messages addressed to the
acting owner are not sent to Telegram either: the web admin receives them in the returned response,
and only notifications to other people (for example a promoted customer) go out.

Messages to an actor whose id is not a Telegram chat id (for example the seeded demo customers
``demo-01``) are skipped too: Telegram would reject them, and that rejection would show up in
Settings as a false error. The skip is logged and leaves ``bots.tg_last_error`` alone.
"""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec, Role
from app.db.models import Bot
from app.integrations.telegram.adapter import TelegramOrigin, render_text, send_out_message
from app.integrations.telegram.client import TelegramApi, TelegramError, TelegramProvider, default_provider
from app.roles.service import get_role
from app.runtime.contracts import RuntimeEvent, RuntimeResponse
from app.runtime.pg_store import PgStore, advisory_lock
from app.runtime.runtime import BotRuntime
from app.security.crypto import TokenCryptoError, decrypt_token

log = logging.getLogger(__name__)

SANDBOX_OWNER = "owner"
MAX_ERROR_CHARS = 500
_CHAT_ID = re.compile(r"-?[0-9]+")  # a Telegram chat id (ASCII digits: \d also matches Persian ones)


async def dispatch(
    session: AsyncSession,
    bot: Bot,
    spec: BotSpec,
    event: RuntimeEvent,
    *,
    telegram: TelegramProvider | None = None,
    origin: TelegramOrigin | None = None,
) -> RuntimeResponse:
    """Run ``event`` through the runtime for ``bot`` and, for live events, deliver the replies.

    ``telegram`` builds a client from a bot token (default: the real one; tests pass the fake's
    ``provider``). ``origin`` carries the Telegram-only details of an inbound update (the callback
    query to answer and the message to edit); it is ignored for non-Telegram callers.

    Commits the session. Raises only what the runtime or database raise; Telegram problems never
    propagate. A runtime failure rolls the transaction back and re-raises.
    """
    if event.bot_id != str(bot.id):
        raise ValueError("event.bot_id does not match the bot being dispatched")
    live = event.env == "live"
    provider = telegram or default_provider

    await advisory_lock(session, bot.id)
    fresh = await session.get(Bot, bot.id, populate_existing=True)  # owner link / token may have changed
    current = fresh or bot
    owner_actor_id = current.owner_actor_id if live else SANDBOX_OWNER
    if live and event.kind != "admin":
        event = _with_owner_flag(event, owner_actor_id)
        event = _with_role(event, await get_role(session, current.id, "live", event.actor.id))
    # Plain values: a rollback or commit may expire the ORM object, and async lazy loads fail.
    target = _Target(current.id, current.tg_token_enc, current.tg_last_error)
    store = PgStore(session, current.id, event.env, owner_actor_id=owner_actor_id)
    try:
        response = await BotRuntime().handle(event, spec, store)
        await session.commit()  # durable BEFORE anything is sent to Telegram
    except BaseException:
        await session.rollback()
        if live:
            await _answer_callback_best_effort(target, origin, provider)
        raise

    if live:
        await _deliver(session, target, response, event, origin, provider)
    return response


def _with_owner_flag(event: RuntimeEvent, owner_actor_id: str | None) -> RuntimeEvent:
    """A Telegram event whose ``actor.is_owner`` reflects the owner link read under the bot's lock.

    The adapter computes the flag from the bot row it loaded before the lock, so a relink that
    commits in between must neither leave the previous owner with owner rights nor deny them to the
    new one. ``admin`` events keep their flag: their caller is the authenticated web owner.
    """
    is_owner = owner_actor_id is not None and event.actor.id == owner_actor_id
    if is_owner == event.actor.is_owner:
        return event
    return event.model_copy(update={"actor": event.actor.model_copy(update={"is_owner": is_owner})})


def _with_role(event: RuntimeEvent, role: Role) -> RuntimeEvent:
    """A Telegram event whose ``actor.role`` is the stored role read under the bot's lock.

    The role in a Telegram event is never trusted: the adapter leaves the default, and anything
    else a caller put there is replaced. The owner stays a manager through ``is_owner``.
    """
    if event.actor.role == role:
        return event
    return event.model_copy(update={"actor": event.actor.model_copy(update={"role": role})})


@dataclass
class _Target:
    """What delivery needs to know about the bot, copied out of the ORM object."""

    id: uuid.UUID
    token_enc: str | None
    last_error: str | None


def _client_for(target: _Target, provider: TelegramProvider) -> TelegramApi | None:
    """A client with the decrypted token, or ``None`` (logged) if the bot has no usable token."""
    if not target.token_enc:
        log.warning("bot %s has no Telegram token; nothing delivered", target.id)
        return None
    try:
        return provider(decrypt_token(target.token_enc))
    except TokenCryptoError as exc:
        log.error("bot %s: Telegram token unusable (%s)", target.id, type(exc).__name__)
        return None


async def _answer_callback_best_effort(
    target: _Target, origin: TelegramOrigin | None, provider: TelegramProvider
) -> None:
    if origin is None or origin.callback_query_id is None:
        return
    client = _client_for(target, provider)
    if client is None:
        return
    try:
        await client.answer_callback_query(origin.callback_query_id)
    except TelegramError as exc:
        log.warning("bot %s: %s", target.id, exc)


async def _deliver(
    session: AsyncSession,
    bot: _Target,
    response: RuntimeResponse,
    event: RuntimeEvent,
    origin: TelegramOrigin | None,
    provider: TelegramProvider,
) -> None:
    errors: list[str] = []
    attempts = 0
    client = _client_for(bot, provider)
    if client is None:
        await _record_error(session, bot, "توکن تلگرام در دسترس نیست؛ پیام‌ها ارسال نشدند.")
        return

    if origin is not None and origin.callback_query_id is not None:
        attempts += 1
        try:
            await client.answer_callback_query(origin.callback_query_id)
        except TelegramError as exc:
            _log_failure(bot, exc)
            errors.append(f"{exc.method}: {exc.description}")

    for message in response.messages:
        if event.kind == "admin" and message.to_actor_id == event.actor.id:
            continue  # the web admin gets its own reply in the HTTP response
        if not _CHAT_ID.fullmatch(message.to_actor_id):
            log.info("bot %s: %r is not a Telegram chat id; not delivered", bot.id, message.to_actor_id)
            continue
        attempts += 1
        try:
            await send_out_message(client, message, event, origin)
        except TelegramError as exc:
            _log_failure(bot, exc)
            errors.append(f"{exc.method}: {exc.description}")
        except Exception:  # a delivery bug must not fail an event that already committed
            log.exception("bot %s: unexpected error while delivering a message", bot.id)
            errors.append("خطای غیرمنتظره در ارسال پیام")

    if attempts:  # a delivery that sent nothing says nothing about the last error
        await _record_error(session, bot, errors[-1] if errors else None)


async def reply_plain(
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    telegram: TelegramProvider | None = None,
    origin: TelegramOrigin | None = None,
) -> None:
    """Send one fixed text (the webhook's "not ready" and owner-link replies) and answer the pressed
    button, if any. Best effort like ``dispatch`` delivery: failures are logged and recorded."""
    provider = telegram or default_provider
    target = _Target(bot.id, bot.tg_token_enc, bot.tg_last_error)
    client = _client_for(target, provider)
    if client is None:
        return
    error: str | None = None
    try:
        if origin is not None and origin.callback_query_id is not None:
            await client.answer_callback_query(origin.callback_query_id)
        await client.send_message(chat_id, render_text(text))
    except TelegramError as exc:
        _log_failure(target, exc)
        error = f"{exc.method}: {exc.description}"
    await _record_error(session, target, error)


def _log_failure(bot: _Target, exc: TelegramError) -> None:
    log.warning("bot %s: Telegram %s failed: %s", bot.id, exc.method, exc.description)


async def _record_error(session: AsyncSession, bot: _Target, error: str | None) -> None:
    """Store the latest delivery error (cleared by a clean delivery); never raises."""
    error = error[:MAX_ERROR_CHARS] if error else None
    if bot.last_error == error:
        return
    try:
        await session.execute(update(Bot).where(Bot.id == bot.id).values(tg_last_error=error))
        bot.last_error = error
        await session.commit()
    except Exception:
        log.exception("bot %s: could not record the Telegram error", bot.id)
        await session.rollback()
