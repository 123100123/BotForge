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

If the runtime raises, the transaction is rolled back (nothing happened), the pressed button is
answered, and for a live private-chat event the user gets a NEW message «نتوانستم این کار را انجام
دهم…» with [تلاش دوباره] (the same callback data again) and [🏠 خانه] (``error_notice``); the
exception is re-raised for the caller to log (``webhook.process_update`` logs and drops it).

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

Group interactions (``event.chat_type == "group"``: a button press on a group message, in practice
the RSVP button of an event card) are delivered differently (``_deliver_group``), after the runtime
ran and the state committed like every live event:

- the button press is answered once, and the first reply to the presser that is not an edit becomes
  the ``answerCallbackQuery`` toast text (seen by the presser only);
- after a successful RSVP (book or cancel) on an events capability, the pressed message (the card)
  is rendered again (``services/group_cards.py``, read after the commit) and edited in place;
  Telegram's "message is not modified" is not an error;
- notices to other people (an owner alert) go to their private chats as usual;
- nothing else is sent: no message to the group, and nothing at all to the presser's private chat
  (their other replies, edits included, belong to a private conversation and are dropped).
"""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec, Role
from app.db.models import Bot
from app.integrations.telegram.adapter import (
    NOT_MODIFIED,
    TelegramOrigin,
    render_text,
    reply_markup,
    send_out_message,
)
from app.integrations.telegram.client import TelegramApi, TelegramError, TelegramProvider, default_provider
from app.roles.service import get_role
from app.runtime import nav
from app.runtime.callbacks import MAX_CALLBACK_BYTES
from app.runtime.contracts import Button, OutMessage, RuntimeEvent, RuntimeResponse
from app.runtime.pg_store import PgStore, advisory_lock
from app.runtime.runtime import BotRuntime
from app.runtime.texts import nav as nav_texts
from app.security.crypto import TokenCryptoError, decrypt_token
from app.services.group_cards import Card, is_events_capability, render_for_item

log = logging.getLogger(__name__)

SANDBOX_OWNER = "owner"
MAX_ERROR_CHARS = 500
NO_TOKEN = "توکن تلگرام در دسترس نیست؛ پیام‌ها ارسال نشدند."
_CHAT_ID = re.compile(r"-?[0-9]+")  # a Telegram chat id (ASCII digits: \d also matches Persian ones)
_USER_ID = re.compile(r"[0-9]+")  # a person's private chat (group and channel ids are negative)
# Outcomes after which a group's event card shows a different count.
_CARD_ACTIONS = frozenset({"book", "cancel"})
_CARD_RESULTS = frozenset({"confirmed", "waitlisted", "cancelled"})


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
    except BaseException as exc:
        await session.rollback()
        if live:
            await _answer_callback_best_effort(target, origin, provider)
            if isinstance(exc, Exception):  # not on cancellation
                await _send_error_notice_best_effort(target, event, origin, provider)
        raise

    if live:
        if event.chat_type == "group":
            await _deliver_group(session, target, spec, response, event, origin, provider)
        else:
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


def client_for_bot(bot: Bot, telegram: TelegramProvider | None = None) -> TelegramApi | None:
    """A Telegram client with ``bot``'s decrypted token (the webhook's document download), or ``None``
    (logged) when the bot has no usable token. The token never leaves the client."""
    return _client_for(_Target(bot.id, bot.tg_token_enc, bot.tg_last_error), telegram or default_provider)


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


def error_notice(event: RuntimeEvent) -> OutMessage:
    """What the user sees when the runtime failed on their event (the transaction was rolled back,
    so nothing happened): an actionable notice, [تلاش دوباره] re-sending the pressed button's data
    when there was one, and [🏠 خانه]."""
    rows: list[list[Button]] = []
    # Longer data than Telegram allows cannot have come from a button: no retry then.
    if event.kind == "callback" and event.data and len(event.data.encode("utf-8")) <= MAX_CALLBACK_BYTES:
        rows.append([Button(label=nav_texts.RETRY, data=event.data)])
    rows.append([nav.home_button()])
    return OutMessage(to_actor_id=event.actor.id, text=nav_texts.ERROR, buttons=rows)


async def _send_error_notice_best_effort(
    target: _Target, event: RuntimeEvent, origin: TelegramOrigin | None, provider: TelegramProvider
) -> None:
    """After a runtime failure on a private-chat event: send ``error_notice`` as a NEW message (the
    pressed message is left as it is). Group presses got their answer already and nothing is ever
    posted to a group; admin events answer through the web. Never raises."""
    if event.chat_type != "private" or event.kind == "admin" or not _CHAT_ID.fullmatch(event.actor.id):
        return
    client = _client_for(target, provider)
    if client is None:
        return
    try:
        await send_out_message(client, error_notice(event), event, None)  # no origin: never an edit
    except TelegramError as exc:
        _log_failure(target, exc)
    except Exception:
        log.exception("bot %s: could not send the error notice", target.id)


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
        await _record_error(session, bot, NO_TOKEN)
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


def _toast(response: RuntimeResponse, event: RuntimeEvent) -> str | None:
    """The toast of a group button press: the first reply to the presser that is not an edit."""
    return next((m.text for m in response.messages if m.to_actor_id == event.actor.id and not m.edit), None)


async def _refreshed_card(
    session: AsyncSession, bot_id: uuid.UUID, spec: BotSpec, response: RuntimeResponse, event: RuntimeEvent
) -> Card | None:
    """The card of the event that a successful RSVP (book or cancel) in ``response`` changed, read
    after the commit so it shows the latest count; ``None`` when there is no such RSVP on an events
    capability, the booking or its item is gone, or the read fails (logged: the card is cosmetic and
    the RSVP is already committed)."""
    outcome = next(
        (
            o
            for o in response.outcomes
            if o.action in _CARD_ACTIONS and o.result in _CARD_RESULTS and o.record_id is not None
        ),
        None,
    )
    if outcome is None or outcome.record_id is None:
        return None
    cap = spec.capability(outcome.capability)
    if not is_events_capability(cap):
        return None
    try:
        store = PgStore(session, bot_id, event.env)
        booking = await store.get_record(cap.key, outcome.record_id)
        card = None
        if booking is not None and booking.item_id is not None:
            card = await render_for_item(store, spec, cap, booking.item_id, now=event.now)
        await session.commit()  # ends the read-only transaction (nothing is pending after dispatch)
        return card
    except Exception:
        log.exception("bot %s: could not render the event card again", bot_id)
        try:
            await session.rollback()
        except Exception:
            log.exception("bot %s: rollback failed", bot_id)
        return None


async def _deliver_group(
    session: AsyncSession,
    bot: _Target,
    spec: BotSpec,
    response: RuntimeResponse,
    event: RuntimeEvent,
    origin: TelegramOrigin | None,
    provider: TelegramProvider,
) -> None:
    """Delivery for a group interaction (module docstring): the toast, the card edit, notices to
    other people; nothing to the group otherwise and nothing to the presser's private chat."""
    errors: list[str] = []
    attempts = 0
    client = _client_for(bot, provider)
    if client is None:
        await _record_error(session, bot, NO_TOKEN)
        return

    if origin is not None and origin.callback_query_id is not None:
        attempts += 1
        try:
            await client.answer_callback_query(origin.callback_query_id, text=_toast(response, event))
        except TelegramError as exc:
            _log_failure(bot, exc)
            errors.append(f"{exc.method}: {exc.description}")

    if origin is not None and origin.message_id is not None:
        card = await _refreshed_card(session, bot.id, spec, response, event)
        if card is not None:
            text, buttons = card
            markup = reply_markup(OutMessage(to_actor_id=event.actor.id, text=text, buttons=buttons))
            attempts += 1
            try:
                await client.edit_message_text(origin.chat_id, origin.message_id, render_text(text), markup)
            except TelegramError as exc:
                if NOT_MODIFIED not in exc.description.lower():  # else the card already shows it
                    _log_failure(bot, exc)
                    errors.append(f"{exc.method}: {exc.description}")

    for message in response.messages:
        if message.to_actor_id == event.actor.id:
            continue  # the toast above, or a private-chat reply that has no place in a group
        if not _USER_ID.fullmatch(message.to_actor_id):
            log.info("bot %s: %r is not a person's chat id; not delivered", bot.id, message.to_actor_id)
            continue
        attempts += 1
        try:
            await send_out_message(client, message, event, None)  # no origin: never an edit
        except TelegramError as exc:
            _log_failure(bot, exc)
            errors.append(f"{exc.method}: {exc.description}")
        except Exception:  # a delivery bug must not fail an event that already committed
            log.exception("bot %s: unexpected error while delivering a message", bot.id)
            errors.append("خطای غیرمنتظره در ارسال پیام")

    if attempts:
        await _record_error(session, bot, errors[-1] if errors else None)


async def answer_callback(
    session: AsyncSession,
    bot: Bot,
    origin: TelegramOrigin | None,
    text: str | None = None,
    *,
    telegram: TelegramProvider | None = None,
) -> None:
    """Answer a button press, with ``text`` as its toast, and send nothing else (the webhook's answer
    to a group button press that never reaches the runtime). Best effort like ``reply_plain``."""
    if origin is None or origin.callback_query_id is None:
        return
    target = _Target(bot.id, bot.tg_token_enc, bot.tg_last_error)
    client = _client_for(target, telegram or default_provider)
    if client is None:
        return
    error: str | None = None
    try:
        await client.answer_callback_query(origin.callback_query_id, text=text)
    except TelegramError as exc:
        _log_failure(target, exc)
        error = f"{exc.method}: {exc.description}"
    await _record_error(session, target, error)


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
