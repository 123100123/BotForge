"""Update -> RuntimeEvent and OutMessage -> Bot API calls (no database, no network)."""

from datetime import UTC, datetime
from typing import Any

from app.integrations.telegram.adapter import (
    MAX_TEXT_CHARS,
    ParsedUpdate,
    TelegramOrigin,
    parse_update,
    render_text,
    reply_markup,
    send_out_message,
)
from app.integrations.telegram.client import FakeTelegramClient
from app.runtime.contracts import Actor, Button, OutMessage, RuntimeEvent

NOW = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
BOT = "11111111-1111-1111-1111-111111111111"


def msg(text: Any, *, chat_type: str = "private", user_id: int = 55, is_bot: bool = False) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": 1,
        "from": {"id": user_id, "is_bot": is_bot, "first_name": "سارا", "last_name": "احمدی"},
        "chat": {"id": user_id, "type": chat_type},
    }
    if text is not None:
        message["text"] = text
    return {"update_id": 1, "message": message}


def cb(data: Any = "menu:home:", *, chat_type: str = "private", message_id: int | None = 9) -> dict[str, Any]:
    carrier: dict[str, Any] = {"chat": {"id": 55, "type": chat_type}}
    if message_id is not None:
        carrier["message_id"] = message_id
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cq1",
            "from": {"id": 55, "first_name": "سارا"},
            "message": carrier,
            "data": data,
        },
    }


def parse(update: dict[str, Any], owner: str | None = None) -> ParsedUpdate | None:
    return parse_update(BOT, update, owner_actor_id=owner, now=NOW)


# --- inbound ------------------------------------------------------------------------------------


def test_start_command() -> None:
    parsed = parse(msg("/start"))
    assert parsed is not None
    event = parsed.event
    assert (event.kind, event.env, event.bot_id, event.now) == ("start", "live", BOT, NOW)
    assert event.actor == Actor(id="55", display_name="سارا احمدی", is_owner=False)
    assert parsed.start_payload is None
    assert parsed.origin == TelegramOrigin(chat_id=55)


def test_start_with_deep_link_payload() -> None:
    parsed = parse(msg("/start owner_abc123"))
    assert parsed is not None and parsed.event.kind == "start"
    assert parsed.start_payload == "owner_abc123"
    other = parse(msg("/start@my_bot  hello "))
    assert other is not None and other.event.kind == "start" and other.start_payload == "hello"


def test_plain_text_and_other_commands_are_text_events() -> None:
    for text in ("سلام", "/menu", "/startnow", "start"):
        parsed = parse(msg(text))
        assert parsed is not None and parsed.event.kind == "text" and parsed.event.text == text


def test_owner_actor_is_flagged() -> None:
    assert parse(msg("/start"), owner="55").event.actor.is_owner is True  # type: ignore[union-attr]
    assert parse(msg("/start"), owner="56").event.actor.is_owner is False  # type: ignore[union-attr]
    assert parse(msg("/start"), owner=None).event.actor.is_owner is False  # type: ignore[union-attr]


def test_callback_query() -> None:
    parsed = parse(cb("book_workshop:book:7"))
    assert parsed is not None
    assert (parsed.event.kind, parsed.event.data, parsed.event.text) == (
        "callback",
        "book_workshop:book:7",
        None,
    )
    assert parsed.origin == TelegramOrigin(chat_id=55, callback_query_id="cq1", message_id=9)


def test_callback_without_message_id_has_no_edit_target() -> None:
    parsed = parse(cb(message_id=None))
    assert parsed is not None and parsed.origin.message_id is None


def test_ignored_updates() -> None:
    assert parse(msg("hi", chat_type="group")) is None
    assert parse(msg("hi", chat_type="supergroup")) is None
    assert parse(msg("hi", chat_type="channel")) is None
    assert parse(msg(None)) is None  # a photo, sticker...: no text
    assert parse(msg("   ")) is None
    assert parse(msg("hi", is_bot=True)) is None
    assert parse(cb(chat_type="group")) is None
    assert parse(cb(data=None)) is None
    assert parse({"update_id": 3, "edited_message": {"text": "x"}}) is None
    assert parse({"update_id": 4, "inline_query": {"id": "1"}}) is None
    assert parse({"update_id": 5, "message": "garbage"}) is None
    assert parse({"update_id": 6, "message": {"chat": {"type": "private"}, "text": "x"}}) is None


def test_display_name_falls_back_to_username_then_id() -> None:
    update = msg("hi")
    update["message"]["from"] = {"id": 55, "username": "sara_x"}
    assert parse(update).event.actor.display_name == "sara_x"  # type: ignore[union-attr]
    update["message"]["from"] = {"id": 55}
    assert parse(update).event.actor.display_name == "55"  # type: ignore[union-attr]


# --- outbound -----------------------------------------------------------------------------------

HOSTILE = '<b>bold</b> & <script>alert("x")</script> <a href="https://evil">link</a>'


def event(actor_id: str = "55") -> RuntimeEvent:
    return RuntimeEvent(
        bot_id=BOT,
        env="live",
        actor=Actor(id=actor_id, display_name="x"),
        kind="callback",
        data="m:h:",
        now=NOW,
    )


def test_render_text_escapes_html() -> None:
    assert render_text(HOSTILE) == (
        '&lt;b&gt;bold&lt;/b&gt; &amp; &lt;script&gt;alert("x")&lt;/script&gt; '
        '&lt;a href="https://evil"&gt;link&lt;/a&gt;'
    )
    assert "<" not in render_text(HOSTILE).replace("&lt;", "")
    assert render_text("سلام ۱۲۳") == "سلام ۱۲۳"
    assert len(render_text("x" * 10_000)) <= MAX_TEXT_CHARS


def test_reply_markup_from_buttons() -> None:
    message = OutMessage(
        to_actor_id="55",
        text="t",
        buttons=[
            [Button(label="<b>یک</b>", data="a:b:1"), Button(label="دو", data="a:b:2")],
            [Button(label="سه", data="a:b:3")],
        ],
    )
    assert reply_markup(message) == {
        "inline_keyboard": [
            [{"text": "<b>یک</b>", "callback_data": "a:b:1"}, {"text": "دو", "callback_data": "a:b:2"}],
            [{"text": "سه", "callback_data": "a:b:3"}],
        ]
    }
    assert reply_markup(OutMessage(to_actor_id="55", text="t")) is None


async def test_plain_message_is_sent_escaped_with_keyboard() -> None:
    fake = FakeTelegramClient()
    message = OutMessage(to_actor_id="55", text=HOSTILE, buttons=[[Button(label="باشه", data="a:b:1")]])
    await send_out_message(fake, message, event(), TelegramOrigin(chat_id=55, message_id=9))
    [(method, call)] = fake.calls
    assert method == "sendMessage"
    assert call["chat_id"] == 55
    assert call["text"] == render_text(HOSTILE) and "<script>" not in call["text"]
    assert call["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "a:b:1"


async def test_edit_message_edits_the_pressed_message() -> None:
    fake = FakeTelegramClient()
    message = OutMessage(to_actor_id="55", text=HOSTILE, edit=True)
    await send_out_message(
        fake, message, event(), TelegramOrigin(chat_id=55, callback_query_id="cq", message_id=9)
    )
    [(method, call)] = fake.calls
    assert method == "editMessageText"
    assert (call["chat_id"], call["message_id"]) == (55, 9)
    assert "<script>" not in call["text"]


async def test_edit_falls_back_to_send_when_editing_fails() -> None:
    fake = FakeTelegramClient()
    fake.fail_methods["editMessageText"] = "Bad Request: message to edit not found"
    message = OutMessage(to_actor_id="55", text="سلام", edit=True)
    await send_out_message(fake, message, event(), TelegramOrigin(chat_id=55, message_id=9))
    assert [m for m, _ in fake.calls] == ["editMessageText", "sendMessage"]


async def test_not_modified_is_not_a_failure_and_sends_nothing_more() -> None:
    fake = FakeTelegramClient()
    fake.fail_methods["editMessageText"] = (
        "Bad Request: message is not modified: specified new message content"
    )
    await send_out_message(
        fake,
        OutMessage(to_actor_id="55", text="سلام", edit=True),
        event(),
        TelegramOrigin(chat_id=55, message_id=9),
    )
    assert [m for m, _ in fake.calls] == ["editMessageText"]


async def test_edit_without_a_message_to_edit_or_for_another_chat_is_sent() -> None:
    fake = FakeTelegramClient()
    await send_out_message(
        fake, OutMessage(to_actor_id="55", text="a", edit=True), event(), TelegramOrigin(chat_id=55)
    )
    await send_out_message(
        fake,
        OutMessage(to_actor_id="77", text="b", edit=True),
        event(),
        TelegramOrigin(chat_id=55, message_id=9),
    )
    assert [m for m, _ in fake.calls] == ["sendMessage", "sendMessage"]
    assert fake.calls[1][1]["chat_id"] == 77


async def test_non_telegram_recipient_is_skipped() -> None:
    fake = FakeTelegramClient()
    await send_out_message(fake, OutMessage(to_actor_id="owner", text="a"), event(), None)
    assert fake.calls == []
