"""Telegram groups and documents without a database (W2-TG): parsing group button presses and
private documents, the client's toast, getFile and capped download, the fake client, the event card
read from a MemoryStore, and the early (no database) paths of the Telegram document handler.

The webhook, dispatch and the groups API end to end are in tests/integration/test_groups_api.py."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.api import uploads as uploads_api
from app.botspec.models import BookingCapability, BotSpec
from app.botspec.records import to_utc_iso
from app.config import Settings
from app.db.models import Bot
from app.integrations.telegram import client as client_module
from app.integrations.telegram.adapter import ParsedUpdate, TelegramDocument, TelegramOrigin, parse_update
from app.integrations.telegram.client import (
    MAX_TOAST_CHARS,
    FakeTelegramClient,
    TelegramClient,
    TelegramError,
    TelegramFileTooLarge,
    toast_text,
    valid_file_path,
)
from app.runtime.callbacks import parse_callback
from app.runtime.memory_store import MemoryStore
from app.services.group_cards import find_events_capability, is_events_capability, render_for_item
from app.spreadsheets import telegram_ingest
from app.spreadsheets.errors import BUSY_MESSAGE, too_large_message
from app.spreadsheets.telegram_ingest import (
    ANALYSIS_FAILED,
    DOWNLOAD_FAILED,
    RECEIVED,
    handle_document,
    run_reply,
)

NOW = datetime(2026, 10, 6, 8, 0, tzinfo=UTC)
BOT = "11111111-1111-1111-1111-111111111111"
TOKEN = "123456789:AAH-secretsecretsecretsecret_secret1234"
GROUP = -1001234567890
CAP = "events"


def parse(update: dict[str, Any], owner: str | None = None) -> ParsedUpdate | None:
    return parse_update(BOT, update, owner_actor_id=owner, now=NOW)


SAME: Any = object()  # the pressed message offers exactly the pressed button


def group_press(
    data: Any = f"{CAP}:book:7",
    *,
    chat_type: str = "supergroup",
    chat_id: Any = GROUP,
    user: Any = None,
    message_id: Any = 4242,
    markup: Any = SAME,
) -> dict[str, Any]:
    """A callback query as Telegram sends it: the pressed message comes with its own keyboard."""
    carrier: dict[str, Any] = {"chat": {"id": chat_id, "type": chat_type, "title": "گروه"}, "date": 1}
    if message_id is not None:
        carrier["message_id"] = message_id
    if markup is SAME:
        carrier["reply_markup"] = {"inline_keyboard": [[{"text": "شرکت می‌کنم", "callback_data": data}]]}
    elif markup is not None:
        carrier["reply_markup"] = markup
    return {
        "update_id": 10,
        "callback_query": {
            "id": "gcq",
            "from": user if user is not None else {"id": 601, "is_bot": False, "first_name": "علی"},
            "message": carrier,
            "data": data,
        },
    }


def document_message(document: Any, *, chat_type: str = "private", user_id: int = 55) -> dict[str, Any]:
    return {
        "update_id": 11,
        "message": {
            "message_id": 3,
            "from": {"id": user_id, "is_bot": False, "first_name": "سارا"},
            "chat": {"id": user_id if chat_type == "private" else GROUP, "type": chat_type},
            "document": document,
        },
    }


DOC = {
    "file_id": "BQACAgQAAxkBAAIB",
    "file_unique_id": "AgADBAAC",
    "file_name": "گزارش روزانه.xlsx",
    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "file_size": 2048,
}


# --- adapter: group button presses -------------------------------------------------------------


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
def test_a_button_press_in_a_group_is_a_group_event_from_the_presser(chat_type: str) -> None:
    parsed = parse(group_press(chat_type=chat_type), owner="601")
    assert parsed is not None
    event = parsed.event
    assert (event.kind, event.chat_type, event.data, event.env) == (
        "callback",
        "group",
        f"{CAP}:book:7",
        "live",
    )
    assert event.actor.id == "601" and event.actor.is_owner is True and event.actor.role == "customer"
    assert parsed.origin == TelegramOrigin(chat_id=GROUP, callback_query_id="gcq", message_id=4242)
    assert parsed.start_payload is None and parsed.document is None


def test_private_button_presses_stay_private_events() -> None:
    update = group_press(chat_type="private", chat_id=601)
    parsed = parse(update)
    assert parsed is not None and parsed.event.chat_type == "private"
    assert parsed.origin == TelegramOrigin(chat_id=601, callback_query_id="gcq", message_id=4242)


@pytest.mark.parametrize(
    "update",
    [
        group_press(user={"id": 601, "is_bot": True, "first_name": "x"}),  # a bot
        group_press(user={"first_name": "no id"}),
        group_press(user={"id": "601"}),  # not an int
        group_press(user={"id": True}),  # a bool is not an id
        group_press(user={"id": -5}),  # a chat id, not a person
        group_press(chat_id="-100"),  # a string chat id
        group_press(chat_id=True),
        group_press(chat_type="secret"),
        group_press(data=None),
        group_press(data=7),
        {"update_id": 1, "callback_query": {"id": "q", "from": {"id": 1}, "data": "x:y:"}},  # no message
        {"update_id": 1, "callback_query": "garbage"},
    ],
)
def test_malformed_group_presses_are_ignored(update: dict[str, Any]) -> None:
    assert parse(update) is None


def test_a_group_press_without_a_message_id_has_no_card_to_edit() -> None:
    for message_id in (None, "4242", True):
        parsed = parse(group_press(message_id=message_id))
        assert parsed is not None and parsed.origin.message_id is None


def test_a_press_the_message_does_not_offer_is_forged_and_ignored() -> None:
    card = {"inline_keyboard": [[{"text": "شرکت می‌کنم", "callback_data": f"{CAP}:book:7"}]]}
    assert parse(group_press(f"{CAP}:book:8", markup=card)) is None  # another event on card 7
    assert parse(group_press("menu:home:", markup=card)) is None
    assert parse(group_press(f"{CAP}:book:7", markup={"inline_keyboard": []})) is None
    two_rows = {
        "inline_keyboard": [[{"text": "a", "url": "https://x"}], [{"text": "b", "callback_data": "k:l:"}]]
    }
    assert parse(group_press("k:l:", markup=two_rows)) is not None


def test_a_message_without_a_readable_keyboard_is_no_edit_target() -> None:
    for markup in (None, "garbage", {"inline_keyboard": "x"}, {}):
        parsed = parse(group_press(markup=markup))
        assert parsed is not None and parsed.event.data == f"{CAP}:book:7"  # the RSVP still counts
        assert parsed.origin.message_id is None and parsed.origin.callback_query_id == "gcq"


def test_group_messages_and_group_documents_stay_ignored() -> None:
    text = {
        "update_id": 1,
        "message": {"from": {"id": 5}, "chat": {"id": GROUP, "type": "group"}, "text": "/start"},
    }
    assert parse(text) is None
    assert parse(document_message(DOC, chat_type="supergroup")) is None


# --- adapter: private documents ---------------------------------------------------------------


def test_a_private_document_is_parsed_with_its_metadata_and_no_text() -> None:
    parsed = parse(document_message(DOC), owner="55")
    assert parsed is not None
    assert parsed.document == TelegramDocument(
        file_id=DOC["file_id"],
        file_unique_id=DOC["file_unique_id"],
        file_name=DOC["file_name"],
        mime_type=DOC["mime_type"],
        file_size=2048,
    )
    event = parsed.event
    assert (event.kind, event.text, event.data, event.chat_type) == ("text", None, None, "private")
    assert event.actor.id == "55" and event.actor.is_owner is True
    assert parsed.origin == TelegramOrigin(chat_id=55)


def test_document_fields_are_type_checked() -> None:
    minimal = parse(document_message({"file_id": "a", "file_unique_id": "b"}))
    assert minimal is not None and minimal.document == TelegramDocument("a", "b")
    odd = parse(document_message({**DOC, "file_size": True, "file_name": 5, "mime_type": ["x"]}))
    assert odd is not None and odd.document is not None
    assert (odd.document.file_size, odd.document.file_name, odd.document.mime_type) == (None, None, None)
    negative = parse(document_message({**DOC, "file_size": -1}))
    assert negative is not None and negative.document is not None and negative.document.file_size is None
    long_name = parse(document_message({**DOC, "file_name": "x" * 5000}))
    assert long_name is not None and long_name.document is not None
    assert len(long_name.document.file_name or "") == 1024


@pytest.mark.parametrize(
    "document",
    [
        None,
        "BQAC",
        {"file_unique_id": "b"},
        {"file_id": "", "file_unique_id": "b"},
        {"file_id": "a", "file_unique_id": None},
        {"file_id": "a" * 257, "file_unique_id": "b"},
        {"file_id": 12, "file_unique_id": "b"},
    ],
)
def test_malformed_documents_are_ignored(document: Any) -> None:
    assert parse(document_message(document)) is None


def test_a_bot_sending_a_document_is_ignored() -> None:
    update = document_message(DOC)
    update["message"]["from"]["is_bot"] = True
    assert parse(update) is None


def test_text_messages_are_unchanged_by_document_support() -> None:
    parsed = parse(
        {"update_id": 1, "message": {"from": {"id": 5}, "chat": {"id": 5, "type": "private"}, "text": "سلام"}}
    )
    assert parsed is not None and parsed.document is None
    assert (parsed.event.kind, parsed.event.text) == ("text", "سلام")


# --- client: toast, getFile, download -----------------------------------------------------------


class Stub:
    """Scripted responses for a ``TelegramClient`` over ``httpx.MockTransport``; records requests."""

    def __init__(self, *responses: Callable[[httpx.Request], httpx.Response] | httpx.Response | Exception):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item

    def client(self) -> TelegramClient:
        return TelegramClient(TOKEN, http=httpx.AsyncClient(transport=httpx.MockTransport(self)))


def ok(result: Any = True) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


async def test_answer_callback_query_sends_the_toast_text_cut_to_the_limit() -> None:
    stub = Stub(ok(), ok(), ok(), ok())
    c = stub.client()
    await c.answer_callback_query("q1", text="شرکت شما ثبت شد")
    await c.answer_callback_query("q2", text="x" * 500, show_alert=True)
    await c.answer_callback_query("q3", text="   ")
    await c.answer_callback_query("q4", show_alert=True)  # no text: no alert either
    bodies = [json.loads(r.content) for r in stub.requests]
    assert bodies[0] == {"callback_query_id": "q1", "text": "شرکت شما ثبت شد"}
    assert bodies[1]["show_alert"] is True and len(bodies[1]["text"]) == MAX_TOAST_CHARS
    assert bodies[1]["text"].endswith("…")
    assert bodies[2] == {"callback_query_id": "q3"}
    assert bodies[3] == {"callback_query_id": "q4"}


def test_toast_text() -> None:
    assert toast_text(None) is None and toast_text("") is None and toast_text(" \n ") is None
    assert toast_text(" سلام ") == "سلام"
    assert len(toast_text("ب" * 181) or "") == MAX_TOAST_CHARS
    assert toast_text("ب" * 180) == "ب" * 180


async def test_get_file_returns_the_checked_file_path() -> None:
    stub = Stub(
        ok({"file_id": "f", "file_unique_id": "u", "file_size": 10, "file_path": "documents/file_12.xlsx"})
    )
    assert await stub.client().get_file("f") == "documents/file_12.xlsx"
    assert stub.requests[0].url.path == f"/bot{TOKEN}/getFile"
    assert json.loads(stub.requests[0].content) == {"file_id": "f"}


@pytest.mark.parametrize(
    "path",
    [
        None,
        "",
        "../bot1/getMe",
        "documents/../../bot1/deleteWebhook",
        "/etc/passwd",
        "documents//file.xlsx",
        "documents/file.xlsx?x=1",
        "documents/file name.xlsx",
        "https://evil.example/x",
        "documents/فایل.xlsx",
        "a/" * 200 + "b",
        ".",
        "documents/./file",
    ],
)
async def test_get_file_refuses_an_unsafe_or_missing_path(path: Any) -> None:
    result: dict[str, Any] = {"file_id": "f"} if path is None else {"file_id": "f", "file_path": path}
    with pytest.raises(TelegramError) as info:
        await Stub(ok(result)).client().get_file("f")
    assert info.value.method == "getFile"
    assert not valid_file_path(path)


def test_valid_file_paths() -> None:
    for path in ("documents/file_0.xlsx", "documents/file_1", "photos/file-2.JPG", "file.csv"):
        assert valid_file_path(path), path


def stream(chunks: list[bytes], *, delay: float = 0.0) -> AsyncIterator[bytes]:
    async def gen() -> AsyncIterator[bytes]:
        for chunk in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield chunk

    return gen()


async def test_download_file_returns_the_bytes_from_the_file_url_without_compression() -> None:
    stub = Stub(httpx.Response(200, content=b"name,amount\nali,10\n"))
    data = await stub.client().download_file("documents/file_3.csv", 1024)
    assert data == b"name,amount\nali,10\n"
    request = stub.requests[0]
    assert request.method == "GET" and request.url.host == "api.telegram.org"
    assert request.url.path == f"/file/bot{TOKEN}/documents/file_3.csv"
    assert request.headers["accept-encoding"] == "identity"


async def test_download_file_refuses_a_declared_size_over_the_cap() -> None:
    stub = Stub(httpx.Response(200, headers={"content-length": "5000"}, content=stream([b"x" * 10])))
    with pytest.raises(TelegramFileTooLarge) as info:
        await stub.client().download_file("documents/file_3.csv", 1000)
    assert info.value.error_code == 413 and info.value.method == "downloadFile"


async def test_download_file_cuts_a_stream_off_past_the_cap() -> None:
    pulled: list[int] = []

    async def gen() -> AsyncIterator[bytes]:
        for i in range(100):  # 100 KiB on offer, no Content-Length
            pulled.append(i)
            yield b"y" * 1024

    stub = Stub(httpx.Response(200, content=gen()))
    with pytest.raises(TelegramFileTooLarge):
        await stub.client().download_file("documents/file_3.csv", 4096)
    assert len(pulled) <= 6  # stopped right after the cap, not after reading everything


async def test_download_file_at_exactly_the_cap_is_accepted() -> None:
    stub = Stub(httpx.Response(200, content=stream([b"a" * 512, b"b" * 512])))
    assert len(await stub.client().download_file("documents/file_3.csv", 1024)) == 1024


async def test_download_file_never_follows_a_redirect() -> None:
    stub = Stub(httpx.Response(302, headers={"location": "https://evil.example/steal"}))
    with pytest.raises(TelegramError) as info:
        await stub.client().download_file("documents/file_3.csv", 1024)
    assert info.value.description == "HTTP 302" and len(stub.requests) == 1


async def test_download_file_refuses_an_encoded_body() -> None:
    stub = Stub(httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"\x1f\x8b"))
    with pytest.raises(TelegramError, match="encoding"):
        await stub.client().download_file("documents/file_3.csv", 1024)


async def test_download_file_error_status_is_a_telegram_error() -> None:
    stub = Stub(httpx.Response(404, json={"ok": False, "description": "Not Found"}))
    with pytest.raises(TelegramError) as info:
        await stub.client().download_file("documents/file_3.csv", 1024)
    assert info.value.error_code == 404 and not isinstance(info.value, TelegramFileTooLarge)


async def test_download_file_refuses_an_unsafe_path_without_a_request() -> None:
    stub = Stub()
    for path in ("../bot1/getMe", "/x", ""):
        with pytest.raises(TelegramError):
            await stub.client().download_file(path, 1024)
    assert stub.requests == []


async def test_download_errors_never_carry_the_token(caplog: pytest.LogCaptureFixture) -> None:
    leaky = httpx.ConnectError(f"cannot connect to https://api.telegram.org/file/bot{TOKEN}/documents/f")
    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramError) as info:
        await Stub(leaky).client().download_file("documents/f", 1024)
    exc = info.value
    assert exc.network is True and exc.method == "downloadFile"
    assert TOKEN not in str(exc) and TOKEN not in repr(exc) and TOKEN not in caplog.text
    assert exc.__cause__ is None and exc.__suppress_context__


async def test_download_file_has_a_wall_clock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)
    stub = Stub(httpx.Response(200, content=stream([b"a", b"b", b"c"], delay=0.2)))  # a trickle
    with pytest.raises(TelegramError) as info:
        await stub.client().download_file("documents/file_3.csv", 1024)
    assert info.value.network is True and "timed out" in info.value.description


async def test_fake_client_serves_canned_files_with_the_same_rules() -> None:
    fake = FakeTelegramClient()
    fake.files["doc"] = b"0123456789"
    path = await fake.get_file("doc")
    assert valid_file_path(path)
    assert await fake.download_file(path, 10) == b"0123456789"
    with pytest.raises(TelegramFileTooLarge):
        await fake.download_file(path, 9)
    with pytest.raises(TelegramError):
        await fake.get_file("unknown")
    with pytest.raises(TelegramError):
        await fake.download_file("documents/never_handed_out", 10)
    await fake.answer_callback_query("q", text="x" * 300)
    assert fake.calls_to("answerCallbackQuery")[-1]["text"] == toast_text("x" * 300)
    assert [n for n, _ in fake.calls] == [
        "getFile",
        "downloadFile",
        "downloadFile",
        "getFile",
        "downloadFile",
        "answerCallbackQuery",
    ]


# --- event cards from a store -----------------------------------------------------------------


def events_spec(**cap: Any) -> BotSpec:
    return BotSpec.model_validate(
        {
            "bot": {"name": "رویدادها", "welcome_text": "سلام"},
            "resources": [
                {
                    "key": "event",
                    "label": "رویداد",
                    "label_plural": "رویدادها",
                    "title_field": "title",
                    "fields": [
                        {"key": "title", "label": "عنوان", "type": "text"},
                        {"key": "starts_at", "label": "زمان شروع", "type": "datetime"},
                        {"key": "location", "label": "مکان", "type": "text", "required": False},
                        {"key": "capacity", "label": "ظرفیت", "type": "integer"},
                    ],
                }
            ],
            "capabilities": [
                {
                    "type": "booking",
                    "key": CAP,
                    "title": "رویدادها",
                    "resource": "event",
                    "capacity": {"mode": "per_item", "value": None, "field": "capacity"},
                    "start_field": "starts_at",
                    "detail_fields": ["location"],
                    "preset": "events",
                    **cap,
                }
            ],
            "menu": [{"key": "events_menu", "label": "رویدادها", "capability": CAP, "view": "main"}],
        }
    )


async def seed_event(store: MemoryStore, *, capacity: Any = 3, title: str = "همایش وب") -> int:
    data = {"title": title, "starts_at": to_utc_iso(NOW + timedelta(days=3)), "location": "تهران"}
    if capacity is not None:
        data["capacity"] = capacity
    return (await store.create_record("event", data, now=NOW)).id


async def test_render_for_item_counts_only_confirmed_bookings() -> None:
    spec = events_spec()
    cap = spec.capabilities[0]
    assert isinstance(cap, BookingCapability)
    store = MemoryStore()
    item = await seed_event(store)
    for actor, status in (("a", "confirmed"), ("b", "confirmed"), ("c", "waitlisted"), ("d", "cancelled")):
        await store.create_record(CAP, {}, status=status, actor_id=actor, item_id=item, now=NOW)
    card = await render_for_item(store, spec, cap, item, now=NOW)
    assert card is not None
    text, buttons = card
    assert text.split("\n")[0] == "📅 همایش وب" and "📍 تهران" in text
    assert text.split("\n")[-1].endswith("۲ / ۳")
    assert len(buttons) == 1 and len(buttons[0]) == 1
    assert parse_callback(buttons[0][0].data) == (CAP, "book", str(item))
    assert await render_for_item(store, spec, cap, 99999, now=NOW) is None


async def test_render_for_item_without_a_known_capacity_shows_only_the_count() -> None:
    spec = events_spec()
    cap = spec.capabilities[0]
    assert isinstance(cap, BookingCapability)
    store = MemoryStore()
    item = await seed_event(store, capacity=None)
    card = await render_for_item(store, spec, cap, item, now=NOW)
    assert card is not None and card[0].split("\n")[-1] == "۰ نفر شرکت می‌کنند"


def test_find_events_capability() -> None:
    spec = events_spec()
    assert find_events_capability(spec, "event") is spec.capabilities[0]
    assert find_events_capability(spec, "other") is None
    assert find_events_capability(events_spec(enabled=False), "event") is None
    assert find_events_capability(events_spec(preset="booking"), "event") is None
    assert is_events_capability(spec.capabilities[0]) and not is_events_capability(None)


# --- the Telegram document handler: paths that end before the database --------------------------


class NoSession:
    """Fails the test if the handler touches the database."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the session was used ({name})")


def doc(size: int | None = None) -> TelegramDocument:
    return TelegramDocument(file_id="doc-1", file_unique_id="u1", file_name="r.csv", file_size=size)


def settings(max_bytes: int = 100) -> Settings:
    return Settings(UPLOAD_MAX_BYTES=max_bytes)


def a_bot() -> Bot:
    return Bot(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="ربات")


async def handle(fake: FakeTelegramClient, document: TelegramDocument, max_bytes: int = 100) -> str:
    return await handle_document(NoSession(), a_bot(), "702", document, fake, settings(max_bytes))  # type: ignore[arg-type]


async def test_a_declared_oversize_document_is_refused_before_any_download() -> None:
    fake = FakeTelegramClient()
    fake.files["doc-1"] = b"x"
    assert await handle(fake, doc(size=101)) == too_large_message(100)
    assert fake.calls == []  # not even getFile


async def test_a_download_past_the_cap_is_refused() -> None:
    fake = FakeTelegramClient()
    fake.files["doc-1"] = b"x" * 101  # no file_size in the update: the download cap decides
    assert await handle(fake, doc()) == too_large_message(100)
    assert [k["max_bytes"] for k in fake.calls_to("downloadFile")] == [100]
    assert uploads_api.IN_FLIGHT.count == 0


async def test_a_failed_download_gets_one_generic_line(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeTelegramClient()  # the file id is unknown: getFile fails
    assert await handle(fake, doc()) == DOWNLOAD_FAILED
    fake.files["doc-1"] = b"x"
    fake.fail_methods["downloadFile"] = "HTTP 500"
    assert await handle(fake, doc()) == DOWNLOAD_FAILED
    assert "doc-1" not in caplog.text and "r.csv" not in caplog.text


async def test_documents_share_the_uploads_in_flight_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegramClient()
    fake.files["doc-1"] = b"x"
    monkeypatch.setattr(uploads_api.IN_FLIGHT, "count", uploads_api.IN_FLIGHT.limit)
    assert await handle(fake, doc()) == BUSY_MESSAGE
    assert fake.calls == []


# --- the reply for an analysis result --------------------------------------------------------------


def run(status: str = "ok", **extra: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "profile_id": str(uuid.uuid4()),
        "upload_id": str(uuid.uuid4()),
        "filename": "فروش.xlsx",
        "status": status,
        "submitted_by": "702",
        "created_at": NOW.isoformat(),
        "metrics": [],
        "anomalies": [],
        **extra,
    }


def scalar(label: str, value: float | None, unit: str | None = None) -> dict[str, Any]:
    return {"id": label, "label": label, "kind": "scalar", "value": value, "unit": unit}


ANOMALY = {"check_id": "c", "label": "پرت", "field": "amount", "severity": "warning"}


def test_run_reply_summarises_scalar_metrics_and_anomalies() -> None:
    metrics = [
        scalar("جمع فروش", 1234567.0, "تومان"),
        scalar("میانگین", 12.3456),
        {"id": "s", "label": "روند", "kind": "series", "series": []},  # not a scalar: left out
        scalar("خالی", None),
        scalar("بی‌نهایت", float("inf")),
        scalar("چهارم", 4),
        scalar("پنجم", 5),
        scalar("ششم", 6),
    ]
    text = run_reply(run(metrics=metrics, anomalies=[ANOMALY, ANOMALY]), "x.xlsx")
    lines = text.split("\n")
    assert 3 <= len(lines) <= 6
    assert lines[0] == "فایل «فروش.xlsx» تحلیل شد ✅"
    assert lines[1] == "• جمع فروش: ۱٬۲۳۴٬۵۶۷ تومان"
    assert lines[2] == "• میانگین: ۱۲٫۳۵"
    assert "روند" not in text and "خالی" not in text and "بی‌نهایت" not in text and "ششم" not in text
    assert lines[-1] == "موارد غیرعادی: ۲"


def test_run_reply_without_metrics_is_still_three_lines() -> None:
    lines = run_reply(run(), "x.xlsx").split("\n")
    assert len(lines) == 3 and lines[-1] == "موارد غیرعادی: ۰"


def test_run_reply_for_a_changed_layout_lists_the_missing_columns() -> None:
    missing = [f"ستون {i}" for i in range(12)]
    text = run_reply(run("schema_changed", schema_diff={"missing": missing, "new": ["تازه"]}), "x.xlsx")
    lines = text.split("\n")
    assert "فرق دارد" in lines[0]
    assert lines[1].startswith("ستون‌های جاافتاده: ستون 0، ستون 1")
    assert lines[1].endswith(" و ۲ ستون دیگر") and "ستون 11" not in lines[1]
    assert lines[2] == "ستون‌های جدید: تازه"


def test_run_reply_for_nothing_or_a_failure_acknowledges_the_file() -> None:
    assert run_reply(None, "x.xlsx") == RECEIVED
    assert run_reply({"not": "a run"}, "x.xlsx") == RECEIVED
    assert run_reply(run("failed", error="boom"), "x.xlsx") == f"{RECEIVED}\n{ANALYSIS_FAILED}"


def test_the_runner_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, telegram_ingest.RUN_MODULE, None)  # import halts: as if absent
    assert telegram_ingest._runner() is None
