"""Telegram update <-> runtime contracts (roadmap: Telegram Integration, steps 4 and 6).

Inbound: ``parse_update`` turns a raw update dict into a ``ParsedUpdate`` (a ``RuntimeEvent`` plus the
Telegram-only details the runtime must not see). Private chats: `/start` becomes a ``start`` event (a
deep-link payload is returned separately), other text a ``text`` event, a callback query a
``callback`` event, and a document (a file sent as a file) a ``ParsedUpdate.document`` beside an
event that carries only the actor (``kind="text"``, no text; the webhook handles documents itself
and never dispatches them). Groups (Business OS, Telegram groups): only a button press on a message
of a group, supergroup or channel is handled, as a ``callback`` event with ``chat_type="group"``
whose actor is the person who pressed (``dispatch`` resolves their role and owner flag as for any
live event) and whose origin is the group chat and the pressed message (the event card). Group
messages stay ignored (privacy mode: the bot reads no group conversation). Everything else yields
``None``.

SECURITY (group presses): the pressed message is shared by the whole group and is edited in place
after an RSVP, so its own keyboard is the proof of what was pressed. Telegram sends the message,
keyboard included, with the callback query, while the callback data is what the client sent: data
that is not one of the message's buttons (a modified client) is ignored, and a message without a
readable keyboard (an inaccessible one) is not an edit target (``origin.message_id`` is None).

Outbound: ``send_out_message`` performs one ``OutMessage`` with the right Bot API call. All text goes
through ``render_text`` for the client's platform: HTML-escaped on Telegram (``parse_mode=HTML``),
Markdown-neutralised plain text on Bale (``platforms.render_bale``); button labels are plain text and
are not escaped. The chat id of
a recipient is its actor id (a private chat); group delivery rules live in ``services/dispatch.py``.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.integrations.telegram.client import TelegramApi, TelegramError
from app.integrations.telegram.platforms import DEFAULT_PLATFORM, as_platform, localize, render_bale
from app.runtime.contracts import Actor, OutMessage, RuntimeEvent
from app.runtime.texts import nav as nav_texts

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 4000  # Telegram allows 4096 after entity parsing; stay below it
NOT_MODIFIED = "message is not modified"
# Chats whose button presses are group-context callbacks (an event card can be posted to any of them).
GROUP_CHAT_TYPES = frozenset({"group", "supergroup", "channel"})
MAX_FILE_ID_CHARS = 256  # Telegram's ids are far shorter; anything longer is not a real one
MAX_FILE_NAME_CHARS = 1024  # a label only (the spreadsheet service sanitises and shortens it)
_CHAT_ID = re.compile(r"-?[0-9]+")


@dataclass(frozen=True)
class TelegramOrigin:
    """Where an inbound event came from: needed to answer the button press and to edit its message."""

    chat_id: int
    callback_query_id: str | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class TelegramDocument:
    """A file sent as a document in a private chat. Every field comes from the update as is (types
    checked): ``file_name`` and ``mime_type`` are advisory labels, ``file_size`` may be absent."""

    file_id: str
    file_unique_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


@dataclass(frozen=True)
class ParsedUpdate:
    event: RuntimeEvent
    origin: TelegramOrigin
    start_payload: str | None = None  # `/start <payload>` deep-link argument
    document: TelegramDocument | None = None  # private chats only; the event then has no text


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


def _is_person(user: Any) -> bool:
    """A human Telegram user (a positive int id that is not a bool, not a bot): who pressed a button
    in a group."""
    return (
        isinstance(user, dict)
        and type(user.get("id")) is int
        and user["id"] > 0
        and not user.get("is_bot", False)
    )


def _group_chat_id(chat: Any) -> int | None:
    """The id of a group, supergroup or channel chat, else ``None``."""
    if not isinstance(chat, dict) or chat.get("type") not in GROUP_CHAT_TYPES:
        return None
    chat_id = chat.get("id")
    return chat_id if type(chat_id) is int else None


def _offers_button(carrier: Any, data: str) -> bool | None:
    """Whether the pressed message's inline keyboard has a button with callback data ``data``;
    ``None`` when the message carries no readable keyboard (an inaccessible message)."""
    markup = carrier.get("reply_markup") if isinstance(carrier, dict) else None
    rows = markup.get("inline_keyboard") if isinstance(markup, dict) else None
    if not isinstance(rows, list):
        return None
    return any(
        isinstance(button, dict) and button.get("callback_data") == data
        for row in rows
        if isinstance(row, list)
        for button in row
    )


def _is_file_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_FILE_ID_CHARS


def _document(raw: Any) -> TelegramDocument | None:
    """The ``document`` of a message, or ``None`` when absent or malformed."""
    if not isinstance(raw, dict):
        return None
    file_id, unique_id = raw.get("file_id"), raw.get("file_unique_id")
    if not _is_file_id(file_id) or not _is_file_id(unique_id):
        return None
    name, mime, size = raw.get("file_name"), raw.get("mime_type"), raw.get("file_size")
    return TelegramDocument(
        file_id=file_id,
        file_unique_id=unique_id,
        file_name=name[:MAX_FILE_NAME_CHARS] if isinstance(name, str) else None,
        mime_type=mime[:MAX_FILE_ID_CHARS] if isinstance(mime, str) else None,
        file_size=size if type(size) is int and size >= 0 else None,
    )


def _parse(
    bot_id: str, update: dict[str, Any], owner_actor_id: str | None, now: datetime
) -> ParsedUpdate | None:
    message = update.get("message")
    if isinstance(message, dict):
        chat, user = message.get("chat"), message.get("from")
        if not _is_private_user(chat, user):
            return None  # group conversations are never read
        text = message.get("text")
        if isinstance(text, str) and text.strip():
            actor = _actor(user, owner_actor_id)
            origin = TelegramOrigin(chat_id=int(chat["id"]))
            is_start, payload = _start_payload(text)
            if is_start:
                event = RuntimeEvent(bot_id=bot_id, env="live", actor=actor, kind="start", now=now)
                return ParsedUpdate(event, origin, payload)
            event = RuntimeEvent(bot_id=bot_id, env="live", actor=actor, kind="text", text=text, now=now)
            return ParsedUpdate(event, origin)
        document = _document(message.get("document"))
        if document is None:
            return None
        actor = _actor(user, owner_actor_id)
        origin = TelegramOrigin(chat_id=int(chat["id"]))
        event = RuntimeEvent(bot_id=bot_id, env="live", actor=actor, kind="text", now=now)
        return ParsedUpdate(event, origin, document=document)

    query = update.get("callback_query")
    if isinstance(query, dict):
        user = query.get("from")
        carrier = query.get("message")
        chat = carrier.get("chat") if isinstance(carrier, dict) else None
        data = query.get("data")
        query_id = query.get("id")
        if not isinstance(data, str) or not isinstance(query_id, str):
            return None
        if _is_private_user(chat, user):
            actor = _actor(user, owner_actor_id)
            message_id = carrier.get("message_id") if isinstance(carrier, dict) else None
            origin = TelegramOrigin(
                chat_id=int(chat["id"]),  # type: ignore[index]
                callback_query_id=query_id,
                message_id=message_id if isinstance(message_id, int) else None,
            )
            event = RuntimeEvent(bot_id=bot_id, env="live", actor=actor, kind="callback", data=data, now=now)
            return ParsedUpdate(event, origin)
        group_id = _group_chat_id(chat)
        if group_id is None or not _is_person(user):
            return None
        offered = _offers_button(carrier, data)
        if offered is False:
            return None  # not a button of the pressed message: forged by the client
        message_id = carrier.get("message_id") if isinstance(carrier, dict) else None
        origin = TelegramOrigin(
            chat_id=group_id,
            callback_query_id=query_id,
            message_id=message_id if offered and type(message_id) is int else None,
        )
        event = RuntimeEvent(
            bot_id=bot_id,
            env="live",
            actor=_actor(user, owner_actor_id),
            kind="callback",
            data=data,
            now=now,
            chat_type="group",
        )
        return ParsedUpdate(event, origin)
    return None


# --- outbound -----------------------------------------------------------------------------------


def render_text(text: str, platform: str = DEFAULT_PLATFORM) -> str:
    """Every outbound text goes through here (the length is capped first). Telegram: escaped for
    ``parse_mode=HTML``. Bale: plain text whose Markdown control characters are neutralised, so user
    content can add no link or formatting, and the runtime's fixed notice naming Telegram names Bale."""
    if len(text) > MAX_TEXT_CHARS:
        text = text[: MAX_TEXT_CHARS - 1] + "…"
    if as_platform(platform) == "bale":
        text = text.replace(nav_texts.COMING_SOON, localize(nav_texts.COMING_SOON, platform))
        return render_bale(text)
    return html.escape(text, quote=False)


def client_platform(client: object) -> str:
    """The platform a client talks to (Telegram for a client that does not say)."""
    return as_platform(getattr(client, "platform", DEFAULT_PLATFORM))


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
    text = render_text(message.text, client_platform(client))
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
