"""Telegram update <-> runtime contracts (roadmap: Telegram Integration, steps 4 and 6).

Inbound: ``parse_update`` turns a raw update dict into a ``ParsedUpdate`` (a ``RuntimeEvent`` plus the
Telegram-only details the runtime must not see). Only private chats are handled; `/start` becomes a
``start`` event (a deep-link payload is returned separately), other text a ``text`` event, a callback
query a ``callback`` event; everything else yields ``None``.

Outbound: ``send_out_message`` performs one ``OutMessage`` with the right Bot API call. All text is
HTML-escaped (``parse_mode=HTML``); button labels are plain text and are not escaped. The chat id of
a recipient is its actor id (private chats only).
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.integrations.telegram.client import TelegramApi, TelegramError
from app.runtime.contracts import Actor, OutMessage, RuntimeEvent

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 4000  # Telegram allows 4096 after entity parsing; stay below it
NOT_MODIFIED = "message is not modified"
_CHAT_ID = re.compile(r"-?[0-9]+")


@dataclass(frozen=True)
class TelegramOrigin:
    """Where an inbound event came from: needed to answer the button press and to edit its message."""

    chat_id: int
    callback_query_id: str | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class ParsedUpdate:
    event: RuntimeEvent
    origin: TelegramOrigin
    start_payload: str | None = None  # `/start <payload>` deep-link argument


def _display_name(user: dict[str, Any]) -> str:
    parts = [str(user.get("first_name") or "").strip(), str(user.get("last_name") or "").strip()]
    name = " ".join(p for p in parts if p)
    return name or str(user.get("username") or "") or str(user.get("id"))


def _actor(user: dict[str, Any], owner_actor_id: str | None) -> Actor:
    actor_id = str(user["id"])
    return Actor(
        id=actor_id,
        display_name=_display_name(user),
        is_owner=owner_actor_id is not None and actor_id == owner_actor_id,
    )


def _start_payload(text: str) -> tuple[bool, str | None]:
    """``(is_start, payload)`` for message text; handles ``/start`` and ``/start@botname``."""
    head, _, rest = text.strip().partition(" ")
    command = head.split("@", 1)[0]
    if command != "/start":
        return False, None
    payload = rest.strip()
    return True, payload or None


def parse_update(
    bot_id: str, update: dict[str, Any], *, owner_actor_id: str | None, now: datetime
) -> ParsedUpdate | None:
    """The runtime event for ``update``, or ``None`` when the update is not handled in V1."""
    try:
        return _parse(bot_id, update, owner_actor_id, now)
    except (KeyError, TypeError, ValueError):  # malformed update: ignore it
        return None


def _is_private_user(chat: Any, user: Any) -> bool:
    return (
        isinstance(chat, dict)
        and chat.get("type") == "private"
        and isinstance(user, dict)
        and isinstance(user.get("id"), int)
        and not user.get("is_bot", False)
    )


def _parse(
    bot_id: str, update: dict[str, Any], owner_actor_id: str | None, now: datetime
) -> ParsedUpdate | None:
    message = update.get("message")
    if isinstance(message, dict):
        chat, user = message.get("chat"), message.get("from")
        text = message.get("text")
        if not _is_private_user(chat, user) or not isinstance(text, str) or not text.strip():
            return None
        actor = _actor(user, owner_actor_id)  # type: ignore[arg-type]
        origin = TelegramOrigin(chat_id=int(chat["id"]))  # type: ignore[index]
        is_start, payload = _start_payload(text)
        if is_start:
            event = RuntimeEvent(bot_id=bot_id, env="live", actor=actor, kind="start", now=now)
            return ParsedUpdate(event, origin, payload)
        event = RuntimeEvent(bot_id=bot_id, env="live", actor=actor, kind="text", text=text, now=now)
        return ParsedUpdate(event, origin)

    query = update.get("callback_query")
    if isinstance(query, dict):
        user = query.get("from")
        carrier = query.get("message")
        chat = carrier.get("chat") if isinstance(carrier, dict) else None
        data = query.get("data")
        query_id = query.get("id")
        if not _is_private_user(chat, user) or not isinstance(data, str) or not isinstance(query_id, str):
            return None
        actor = _actor(user, owner_actor_id)
        message_id = carrier.get("message_id") if isinstance(carrier, dict) else None
        origin = TelegramOrigin(
            chat_id=int(chat["id"]),  # type: ignore[index]
            callback_query_id=query_id,
            message_id=message_id if isinstance(message_id, int) else None,
        )
        event = RuntimeEvent(bot_id=bot_id, env="live", actor=actor, kind="callback", data=data, now=now)
        return ParsedUpdate(event, origin)
    return None


# --- outbound -----------------------------------------------------------------------------------


def render_text(text: str) -> str:
    """Escape for ``parse_mode=HTML`` (and cap the length). Every outbound text goes through here."""
    if len(text) > MAX_TEXT_CHARS:
        text = text[: MAX_TEXT_CHARS - 1] + "…"
    return html.escape(text, quote=False)


def reply_markup(message: OutMessage) -> dict[str, Any] | None:
    rows = [[{"text": b.label, "callback_data": b.data} for b in row] for row in message.buttons if row]
    return {"inline_keyboard": rows} if rows else None


def chat_id_for(actor_id: str) -> int | str | None:
    """The Telegram chat id of a recipient: its actor id. ``None`` for a non-Telegram id.

    Only ASCII digits with at most one leading minus count: ``str.isdigit`` also accepts characters
    such as "²" that ``int`` rejects, and a ValueError here would escape dispatch after its commit.
    """
    return int(actor_id) if _CHAT_ID.fullmatch(actor_id) else None


async def send_out_message(
    client: TelegramApi, message: OutMessage, event: RuntimeEvent, origin: TelegramOrigin | None
) -> None:
    """Deliver one message. Raises ``TelegramError`` when Telegram refuses it.

    An ``edit`` message for the event's own chat edits the message that carried the pressed button;
    if editing fails (message too old or deleted) the text is sent as a new message instead. Telegram's
    "message is not modified" answer is not a failure: the chat already shows that text.
    """
    chat_id = chat_id_for(message.to_actor_id)
    if chat_id is None:
        log.warning("skipping message for non-Telegram recipient %r", message.to_actor_id)
        return
    text = render_text(message.text)
    markup = reply_markup(message)
    if (
        message.edit
        and message.to_actor_id == event.actor.id
        and origin is not None
        and origin.message_id is not None
    ):
        try:
            await client.edit_message_text(chat_id, origin.message_id, text, markup)
            return
        except TelegramError as exc:
            if NOT_MODIFIED in exc.description.lower():
                return
            log.info("editMessageText failed (%s); sending a new message instead", exc.description)
    await client.send_message(chat_id, text, markup)
