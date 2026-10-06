"""Telegram groups and documents end to end with the fake Telegram client (W2-TG). Needs a database.

- ``my_chat_member`` records the groups the bot is in (``bot_chats``);
- an RSVP pressed on a group's event card is answered with a toast and the card is edited in place;
  nothing is sent to the group otherwise and nothing to the presser's private chat;
- private chats behave as before;
- documents: refused for customers (and while the spreadsheet module is off), downloaded with a cap
  and ingested for staff and managers;
- ``GET /bots/{bot_id}/groups`` and ``POST /bots/{bot_id}/groups/{chat_id}/publish`` (the outbox).
"""

import itertools
import sys
import types
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.api import uploads as uploads_api
from app.api.groups import PUBLISH_QUEUED
from app.api.webhook import DOCUMENT_MODULE_OFF, DOCUMENT_NOT_ALLOWED
from app.botspec.records import to_utc_iso
from app.config import get_settings
from app.db.models import Bot, BotChatRow, BotModuleRow, OutboundMessageRow, RecordRow, UploadedFileRow
from app.integrations.telegram import texts
from app.integrations.telegram.client import FakeTelegramClient
from app.roles.service import set_role
from app.runtime.pg_store import PgStore
from app.runtime.texts import booking as booking_texts
from app.spreadsheets.errors import UNSUPPORTED_MESSAGE, too_large_message
from app.spreadsheets.telegram_ingest import RECEIVED, RUN_MODULE
from tests.integration.helpers import SessionFactory
from tests.integration.tg_helpers import ALICE, Chat, LiveBot, make_live_bot, user

CAP = "events"
GROUP = -1001234567890
CARD = 4242  # the message id of the posted event card
OWNER = 900
CSV = b"name,amount\nali,10\nsara,20\n"

EVENTS_SPEC: dict[str, Any] = {
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
            "waitlist": {"enabled": True, "auto_promote": True},
            "notify_owner_on": ["booked"],
        }
    ],
    "menu": [
        {"key": "events_menu", "label": "رویدادها", "capability": CAP, "view": "main"},
        {"key": "my_events", "label": "ثبت‌نام‌های من", "capability": CAP, "view": "mine"},
    ],
}


@pytest.fixture
async def bot(session_factory: SessionFactory, tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, EVENTS_SPEC, owner_actor_id=str(OWNER))


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(root))
    monkeypatch.delenv("UPLOAD_MAX_BYTES", raising=False)
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()
    assert uploads_api.IN_FLIGHT.count == 0


class FakeAnalysis:
    """Stands in for ``app.spreadsheets.run`` (W2-PROF): records calls, returns ``result``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result: Any = None

    async def run_for_upload(
        self, session: Any, bot: Any, upload_row: Any, *, submitted_by: str, llm: Any = None
    ) -> Any:
        self.calls.append(
            {
                "upload_id": upload_row.id,
                "source": upload_row.source,
                "submitted_by": submitted_by,
                "llm": llm,
            }
        )
        return self.result


@pytest.fixture
def analysis(monkeypatch: pytest.MonkeyPatch) -> FakeAnalysis:
    fake = FakeAnalysis()
    module = types.ModuleType(RUN_MODULE)
    module.run_for_upload = fake.run_for_upload  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUN_MODULE, module)
    return fake


class Telegram:
    """Posts raw updates for one bot through the webhook (fresh update ids)."""

    def __init__(self, client: httpx.AsyncClient, bot: LiveBot, fake: FakeTelegramClient) -> None:
        self.chat = Chat(client, bot, fake, 0)
        self.bot = bot
        self.ids = itertools.count(uuid.uuid4().int % 10**6 * 1000)

    async def post(self, update: dict[str, Any]) -> None:
        response = await self.chat.post({"update_id": next(self.ids), **update})
        assert response.status_code == 200 and response.json() == {"ok": True}

    async def member(
        self,
        status: str,
        *,
        chat_id: int = GROUP,
        title: str = "گروه کارگاه",
        kind: str = "supergroup",
        subject: int | None = None,
    ) -> None:
        bot_user = {
            "id": subject if subject is not None else self.bot.tg_bot_id,
            "is_bot": True,
            "first_name": "bot",
        }
        await self.post(
            {
                "my_chat_member": {
                    "chat": {"id": chat_id, "title": title, "type": kind},
                    "from": user(OWNER),
                    "date": 1,
                    "old_chat_member": {"user": bot_user, "status": "left"},
                    "new_chat_member": {"user": bot_user, "status": status},
                }
            }
        )

    async def press_in_group(
        self, user_id: int, data: str, *, message_id: int = CARD, card_data: str | None = None
    ) -> str:
        """A button press on the group message ``message_id`` whose keyboard (sent along by Telegram)
        holds one button with ``card_data`` (default: the pressed ``data``, an honest press)."""
        query_id = f"gcq-{next(self.ids)}"
        keyboard = [[{"text": "شرکت می‌کنم", "callback_data": card_data or data}]]
        await self.post(
            {
                "callback_query": {
                    "id": query_id,
                    "from": user(user_id),
                    "message": {
                        "message_id": message_id,
                        "chat": {"id": GROUP, "type": "supergroup"},
                        "date": 1,
                        "reply_markup": {"inline_keyboard": keyboard},
                    },
                    "data": data,
                }
            }
        )
        return query_id

    async def send_document(
        self, user_id: int, file_id: str = "doc-1", *, name: str = "report.csv", size: int | None = None
    ) -> None:
        document: dict[str, Any] = {"file_id": file_id, "file_unique_id": f"u-{file_id}", "file_name": name}
        if size is not None:
            document["file_size"] = size
        await self.post(
            {
                "message": {
                    "message_id": 5,
                    "from": user(user_id),
                    "chat": {"id": user_id, "type": "private"},
                    "date": 1,
                    "document": document,
                }
            }
        )


async def add_event(
    session_factory: SessionFactory, bot: LiveBot, *, title: str = "همایش وب", capacity: int = 2
) -> int:
    async with session_factory() as session:
        store = PgStore(session, bot.id, "live")
        record = await store.create_record(
            "event",
            {
                "title": title,
                "starts_at": to_utc_iso(datetime.now(UTC) + timedelta(days=30)),
                "location": "تهران",
                "capacity": capacity,
            },
            now=datetime.now(UTC),
        )
        await session.commit()
        return record.id


async def rows(session_factory: SessionFactory, model: Any, bot: LiveBot) -> list[Any]:
    async with session_factory() as session:
        result = await session.execute(select(model).where(model.bot_id == bot.id))
        return list(result.scalars().all())


async def bookings(session_factory: SessionFactory, bot: LiveBot) -> dict[str, str | None]:
    return {r.actor_id: r.status for r in await rows(session_factory, RecordRow, bot) if r.collection == CAP}


async def last_error(session_factory: SessionFactory, bot: LiveBot) -> str | None:
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None
        return row.tg_last_error


def toasts(fake: FakeTelegramClient) -> list[dict[str, Any]]:
    return fake.calls_to("answerCallbackQuery")


def chat_ids(fake: FakeTelegramClient, method: str) -> list[int]:
    return [int(k["chat_id"]) for k in fake.calls_to(method)]


# --- my_chat_member -------------------------------------------------------------------------------


async def test_my_chat_member_records_the_groups_and_their_state(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    tg = Telegram(tg_client, bot, fake_tg)
    await tg.member("member")
    [row] = await rows(session_factory, BotChatRow, bot)
    assert (row.chat_id, row.title, row.kind, row.active) == (GROUP, "گروه کارگاه", "supergroup", True)

    # promoted and renamed; a control character and a bidi override do not survive in the label
    await tg.member("administrator", title="گروه\x00‮ کارگاه  ۲")
    [row] = await rows(session_factory, BotChatRow, bot)
    assert (row.title, row.active) == ("گروه کارگاه ۲", True)

    for status in ("restricted", "left", "kicked"):
        await tg.member(status)
        [row] = await rows(session_factory, BotChatRow, bot)
        assert row.active is False, status
    await tg.member("member")
    assert [r.active for r in await rows(session_factory, BotChatRow, bot)] == [True]

    await tg.member("administrator", chat_id=-1009, title="کانال", kind="channel")
    await tg.member("member", chat_id=-42, title="", kind="group")  # a title is never empty
    # ignored: a private chat (a user blocking the bot), another account, nonsense
    await tg.member("kicked", chat_id=601, kind="private")
    await tg.member("member", chat_id=-77, subject=123456)
    await tg.post({"my_chat_member": {"chat": {"id": -78, "type": "group"}}})
    await tg.post({"my_chat_member": "garbage"})
    found = {r.chat_id: (r.kind, r.title, r.active) for r in await rows(session_factory, BotChatRow, bot)}
    assert found == {
        GROUP: ("supergroup", "گروه کارگاه", True),  # the title follows the latest update
        -1009: ("channel", "کانال", True),
        -42: ("group", "-42", True),
    }
    assert fake_tg.calls == []  # membership changes are recorded silently


async def test_groups_api_lists_active_groups_first_and_only_for_the_owner(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    tg = Telegram(tg_client, bot, fake_tg)
    await tg.member("member", chat_id=-1, title="قدیمی")
    await tg.member("kicked", chat_id=-1, title="قدیمی")
    await tg.member("member", chat_id=-2, title="فعال")
    response = await tg_client.get(f"/bots/{bot.id}/groups", headers=ALICE)
    assert response.status_code == 200
    groups = response.json()
    assert [(g["chat_id"], g["title"], g["kind"], g["active"]) for g in groups] == [
        (-2, "فعال", "supergroup", True),
        (-1, "قدیمی", "supergroup", False),
    ]
    assert all(g["added_at"] for g in groups)
    other = await tg_client.get(f"/bots/{bot.id}/groups", headers={"X-Test-User": "bob"})
    assert other.status_code == 404 and other.json()["error"]["code"] == "bot_not_found"
    anonymous = await tg_client.get(f"/bots/{bot.id}/groups", headers={"X-Test-User": "anonymous"})
    assert anonymous.status_code == 401


# --- RSVP from a group ----------------------------------------------------------------------------


async def test_group_rsvp_is_a_toast_plus_an_edited_card_and_nothing_private(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_event(session_factory, bot, capacity=2)
    tg = Telegram(tg_client, bot, fake_tg)

    query = await tg.press_in_group(601, f"{CAP}:book:{item}")
    [toast] = toasts(fake_tg)
    assert (
        toast["callback_query_id"] == query and "شرکت شما" in toast["text"] and toast["show_alert"] is False
    )
    [card] = fake_tg.calls_to("editMessageText")
    assert (card["chat_id"], card["message_id"]) == (GROUP, CARD)
    assert "همایش وب" in card["text"] and card["text"].split("\n")[-1].endswith("۱ / ۲")
    assert card["reply_markup"] == {
        "inline_keyboard": [[{"text": "شرکت می‌کنم", "callback_data": f"{CAP}:book:{item}"}]]
    }
    assert await bookings(session_factory, bot) == {"601": "confirmed"}

    await tg.press_in_group(602, f"{CAP}:book:{item}")
    assert fake_tg.calls_to("editMessageText")[-1]["text"].split("\n")[-1].endswith("۲ / ۲")
    await tg.press_in_group(603, f"{CAP}:book:{item}")  # full: waitlisted
    assert "فهرست انتظار" in toasts(fake_tg)[-1]["text"]
    assert await bookings(session_factory, bot) == {
        "601": "confirmed",
        "602": "confirmed",
        "603": "waitlisted",
    }

    edits = len(fake_tg.calls_to("editMessageText"))
    await tg.press_in_group(601, f"{CAP}:book:{item}")  # a duplicate is refused: toast only, no edit
    assert toasts(fake_tg)[-1]["text"] and len(fake_tg.calls_to("editMessageText")) == edits

    # nothing went to the group as a new message, nor to any presser's private chat; the owner got
    # the two "booked" alerts in their own chat, as for private bookings
    assert chat_ids(fake_tg, "sendMessage") == [OWNER, OWNER]
    assert set(chat_ids(fake_tg, "editMessageText")) == {GROUP}
    assert len(toasts(fake_tg)) == 4


async def test_card_not_modified_is_no_error_and_a_failed_edit_is_recorded(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_event(session_factory, bot)
    tg = Telegram(tg_client, bot, fake_tg)
    fake_tg.fail_methods["editMessageText"] = (
        "Bad Request: message is not modified: specified new message content"
    )
    await tg.press_in_group(601, f"{CAP}:book:{item}")
    assert await last_error(session_factory, bot) is None
    fake_tg.fail_methods["editMessageText"] = "Bad Request: message can't be edited"
    await tg.press_in_group(602, f"{CAP}:book:{item}")
    assert "can't be edited" in (await last_error(session_factory, bot) or "")
    assert chat_ids(fake_tg, "sendMessage") == [OWNER, OWNER]  # still nothing in the group
    assert await bookings(session_factory, bot) == {"601": "confirmed", "602": "confirmed"}


async def test_a_forged_press_on_a_card_is_ignored(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    shown = await add_event(session_factory, bot, title="همایش وب")
    other = await add_event(session_factory, bot, title="رویداد دیگر")
    tg = Telegram(tg_client, bot, fake_tg)
    # a modified client sends data that the card does not offer: the card must not become another
    # event's card, and nothing is booked
    await tg.press_in_group(601, f"{CAP}:book:{other}", card_data=f"{CAP}:book:{shown}")
    assert fake_tg.calls == [] and await bookings(session_factory, bot) == {}
    await tg.press_in_group(601, f"{CAP}:book:{shown}")  # the honest press still works
    assert fake_tg.calls_to("editMessageText")[-1]["text"].startswith("📅 همایش وب")


async def test_other_group_presses_only_answer_and_post_nothing(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_event(session_factory, bot)
    tg = Telegram(tg_client, bot, fake_tg)
    for data in (f"{CAP}:item:{item}", f"{CAP}:mine:", f"{CAP}:list:0"):
        await tg.press_in_group(601, data)
        assert toasts(fake_tg)[-1]["text"] == booking_texts.EVENTS_GROUP_PRIVATE
    for data in ("menu:home:", "menu:open:events_menu", "garbage", f"{CAP}:own:1.x"):
        await tg.press_in_group(601, data)
        assert toasts(fake_tg)[-1]["text"] in (None, booking_texts.EVENTS_GROUP_PRIVATE), data
    await tg.press_in_group(OWNER, f"{CAP}:book:{item}")  # the owner RSVPs: no alert to themselves
    assert "شرکت شما" in toasts(fake_tg)[-1]["text"]
    assert fake_tg.calls_to("sendMessage") == []
    assert set(chat_ids(fake_tg, "editMessageText")) == {GROUP}  # only the owner's RSVP card edit
    assert await bookings(session_factory, bot) == {str(OWNER): "confirmed"}


async def test_a_group_press_on_a_bot_that_is_not_ready_only_answers(
    tg_client: httpx.AsyncClient, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    bot = await make_live_bot(session_factory, None)
    tg = Telegram(tg_client, bot, fake_tg)
    await tg.press_in_group(601, f"{CAP}:book:1")
    assert [k["text"] for k in toasts(fake_tg)] == [texts.NOT_READY]
    assert fake_tg.calls_to("sendMessage") == [] and fake_tg.calls_to("editMessageText") == []


async def test_private_booking_is_unchanged(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_event(session_factory, bot)
    ali = Chat(tg_client, bot, fake_tg, 601)
    await ali.say("/start")
    await ali.press(ali.data_with("menu:open:events_menu"))
    await ali.press(ali.data_with(f"{CAP}:item:"))
    await ali.press(ali.data_with(f"{CAP}:book:"))
    assert fake_tg.calls[-2][0] == "editMessageText" and fake_tg.calls[-2][1]["message_id"] == 77
    assert "شرکت شما" in ali.last_text() and ali.buttons()  # the private reply keeps its buttons
    assert [k["text"] for k in toasts(fake_tg)] == [None, None, None]  # answered, no toast text
    assert chat_ids(fake_tg, "sendMessage") == [601, OWNER]  # the start reply, the owner's alert
    assert set(chat_ids(fake_tg, "editMessageText")) == {601}
    assert await bookings(session_factory, bot) == {"601": "confirmed"}
    assert item


# --- documents ------------------------------------------------------------------------------------


async def enable_spreadsheets(session_factory: SessionFactory, bot: LiveBot, enabled: bool = True) -> None:
    async with session_factory() as session:
        session.add(
            BotModuleRow(bot_id=bot.id, module="spreadsheet_intelligence", enabled=enabled, config={})
        )
        await session.commit()


async def make_staff(
    session_factory: SessionFactory, bot: LiveBot, actor_id: int, role: str = "staff"
) -> None:
    async with session_factory() as session:
        await set_role(session, bot.id, "live", str(actor_id), role)  # type: ignore[arg-type]
        await session.commit()


def replies_to(fake: FakeTelegramClient, chat_id: int) -> list[str]:
    return [k["text"] for k in fake.sent_to(chat_id)]


async def test_a_customer_document_is_refused_without_a_download(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    upload_dir: Path,
) -> None:
    await enable_spreadsheets(session_factory, bot)
    fake_tg.files["doc-1"] = CSV
    await Telegram(tg_client, bot, fake_tg).send_document(701)
    assert replies_to(fake_tg, 701) == [DOCUMENT_NOT_ALLOWED]
    assert fake_tg.calls_to("getFile") == [] and fake_tg.calls_to("downloadFile") == []
    assert await rows(session_factory, UploadedFileRow, bot) == []


async def test_a_staff_document_is_refused_while_the_module_is_off(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    upload_dir: Path,
) -> None:
    await make_staff(session_factory, bot, 702)
    fake_tg.files["doc-1"] = CSV
    tg = Telegram(tg_client, bot, fake_tg)
    await tg.send_document(702)  # no bot_modules row: the registry default (off)
    await enable_spreadsheets(session_factory, bot, enabled=False)
    await tg.send_document(702, "doc-1")
    await tg.send_document(701)  # a customer still gets the customer line, not the module's
    assert replies_to(fake_tg, 702) == [DOCUMENT_MODULE_OFF, DOCUMENT_MODULE_OFF]
    assert replies_to(fake_tg, 701) == [DOCUMENT_NOT_ALLOWED]
    assert fake_tg.calls_to("getFile") == []


async def test_a_staff_document_is_downloaded_with_the_cap_and_ingested(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    upload_dir: Path,
    analysis: FakeAnalysis,
) -> None:
    await enable_spreadsheets(session_factory, bot)
    await make_staff(session_factory, bot, 702)
    fake_tg.files["doc-1"] = CSV
    await Telegram(tg_client, bot, fake_tg).send_document(702, size=len(CSV))
    assert replies_to(fake_tg, 702) == [RECEIVED]
    assert [k["file_id"] for k in fake_tg.calls_to("getFile")] == ["doc-1"]
    assert [k["max_bytes"] for k in fake_tg.calls_to("downloadFile")] == [get_settings().UPLOAD_MAX_BYTES]
    [upload] = await rows(session_factory, UploadedFileRow, bot)
    assert (upload.source, upload.uploaded_by, upload.filename, upload.size) == (
        "telegram",
        "702",
        "report.csv",
        len(CSV),
    )
    assert upload.content_type == "text/csv"
    assert (upload_dir / upload.storage_key).read_bytes() == CSV
    assert analysis.calls == [
        {"upload_id": upload.id, "source": "telegram", "submitted_by": "702", "llm": None}
    ]


async def test_the_owner_may_send_documents_and_gets_the_analysis_summary(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    upload_dir: Path,
    analysis: FakeAnalysis,
) -> None:
    await enable_spreadsheets(session_factory, bot)
    fake_tg.files["doc-1"] = CSV
    analysis.result = {
        "id": str(uuid.uuid4()),
        "profile_id": str(uuid.uuid4()),
        "upload_id": None,
        "filename": "report.csv",
        "status": "ok",
        "submitted_by": str(OWNER),
        "created_at": datetime.now(UTC).isoformat(),
        "metrics": [{"id": "sum", "label": "جمع مبلغ", "kind": "scalar", "value": 30.0}],
        "anomalies": [{"check_id": "c", "label": "پرت", "field": "amount", "severity": "warning"}],
    }
    await Telegram(tg_client, bot, fake_tg).send_document(OWNER)
    [reply] = replies_to(fake_tg, OWNER)
    assert reply.split("\n") == ["فایل «report.csv» تحلیل شد ✅", "• جمع مبلغ: ۳۰", "موارد غیرعادی: ۱"]
    assert [c["submitted_by"] for c in analysis.calls] == [str(OWNER)]


async def test_a_changed_layout_lists_the_missing_columns(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    upload_dir: Path,
    analysis: FakeAnalysis,
) -> None:
    await enable_spreadsheets(session_factory, bot)
    await make_staff(session_factory, bot, 703, role="manager")
    fake_tg.files["doc-1"] = CSV
    analysis.result = {
        "id": str(uuid.uuid4()),
        "profile_id": str(uuid.uuid4()),
        "upload_id": None,
        "filename": "report.csv",
        "status": "schema_changed",
        "submitted_by": "703",
        "created_at": datetime.now(UTC).isoformat(),
        "metrics": [],
        "anomalies": [],
        "schema_diff": {"missing": ["تاریخ", "شعبه"], "new": []},
    }
    await Telegram(tg_client, bot, fake_tg).send_document(703)
    [reply] = replies_to(fake_tg, 703)
    assert "فرق دارد" in reply and "ستون‌های جاافتاده: تاریخ، شعبه" in reply


async def test_documents_over_the_limit_are_refused(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    upload_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await enable_spreadsheets(session_factory, bot)
    await make_staff(session_factory, bot, 702)
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "64")
    get_settings.cache_clear()
    fake_tg.files["big"] = b"name,amount\n" + b"ali,10\n" * 20  # 152 bytes
    tg = Telegram(tg_client, bot, fake_tg)
    await tg.send_document(702, "big", size=152)  # declared: refused before any download
    assert fake_tg.calls_to("getFile") == []
    await tg.send_document(702, "big")  # undeclared: the download is cut off at the cap
    assert [k["max_bytes"] for k in fake_tg.calls_to("downloadFile")] == [64]
    assert replies_to(fake_tg, 702) == [too_large_message(64), too_large_message(64)]
    assert await rows(session_factory, UploadedFileRow, bot) == []


async def test_a_file_that_is_not_a_spreadsheet_gets_the_service_message(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    upload_dir: Path,
    analysis: FakeAnalysis,
) -> None:
    await enable_spreadsheets(session_factory, bot)
    await make_staff(session_factory, bot, 702)
    fake_tg.files["pdf"] = b"%PDF-1.7\n\x00\x01\x02\x03binary"
    await Telegram(tg_client, bot, fake_tg).send_document(702, "pdf", name="report.pdf")
    assert replies_to(fake_tg, 702) == [UNSUPPORTED_MESSAGE]
    assert await rows(session_factory, UploadedFileRow, bot) == [] and analysis.calls == []


# --- publishing an event card ---------------------------------------------------------------------


async def test_publish_queues_the_event_card_for_the_group(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_event(session_factory, bot, title="کنسرت پاییزی", capacity=50)
    await Telegram(tg_client, bot, fake_tg).member("administrator")
    response = await tg_client.post(
        f"/bots/{bot.id}/groups/{GROUP}/publish",
        json={"collection": "event", "record_id": item},
        headers=ALICE,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"queued": True, "message": PUBLISH_QUEUED}
    [row] = await rows(session_factory, OutboundMessageRow, bot)
    assert (row.env, row.chat_id, row.status, row.dedupe_key) == ("live", GROUP, "queued", None)
    assert row.text.split("\n")[0] == "📅 کنسرت پاییزی" and row.text.split("\n")[-1].endswith("۰ / ۵۰")
    assert row.buttons == [[{"label": "شرکت می‌کنم", "data": f"{CAP}:book:{item}"}]]
    assert fake_tg.calls == []  # the ticker sends it, not the request

    again = await tg_client.post(
        f"/bots/{bot.id}/groups/{GROUP}/publish",
        json={"collection": "event", "record_id": item},
        headers=ALICE,
    )
    assert again.status_code == 200 and len(await rows(session_factory, OutboundMessageRow, bot)) == 2


async def test_publish_refusals_queue_nothing(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_event(session_factory, bot)
    tg = Telegram(tg_client, bot, fake_tg)
    await tg.member("member")
    await tg.member("kicked", chat_id=-5)

    async def publish(
        chat_id: int, body: dict[str, Any], headers: dict[str, str] | None = None
    ) -> httpx.Response:
        return await tg_client.post(
            f"/bots/{bot.id}/groups/{chat_id}/publish", json=body, headers=headers or ALICE
        )

    good = {"collection": "event", "record_id": item}
    cases = [
        (await publish(-5, good), 409, "group_inactive"),
        (await publish(-6, good), 404, "group_not_found"),
        (await publish(GROUP, {"collection": "events", "record_id": item}), 404, "event_not_found"),
        (await publish(GROUP, {"collection": "event", "record_id": item + 1000}), 404, "event_not_found"),
        (await publish(GROUP, good, {"X-Test-User": "bob"}), 404, "bot_not_found"),
        (await publish(GROUP, good, {"X-Test-User": "anonymous"}), 401, "auth_required"),
        (await publish(GROUP, good, {"X-BotForge-CSRF": "0"}), 403, "csrf_failed"),
    ]
    for response, status, code in cases:
        assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    invalid = await publish(GROUP, {"collection": "event", "record_id": 0})
    assert invalid.status_code == 422
    huge_chat = await publish(2**64, good)  # outside bigint: refused before the database
    assert huge_chat.status_code == 422
    huge_record = await publish(GROUP, {"collection": "event", "record_id": 2**64})
    assert (huge_record.status_code, huge_record.json()["error"]["code"]) == (404, "event_not_found")
    assert await rows(session_factory, OutboundMessageRow, bot) == []


async def test_publish_needs_an_enabled_events_capability(
    tg_client: httpx.AsyncClient, fake_tg: FakeTelegramClient, session_factory: SessionFactory, tg_env: None
) -> None:
    disabled = {**EVENTS_SPEC, "capabilities": [{**EVENTS_SPEC["capabilities"][0], "enabled": False}]}
    for spec in (disabled, None):
        bot = await make_live_bot(session_factory, spec)
        await Telegram(tg_client, bot, fake_tg).member("member")
        response = await tg_client.post(
            f"/bots/{bot.id}/groups/{GROUP}/publish",
            json={"collection": "event", "record_id": 1},
            headers=ALICE,
        )
        assert (response.status_code, response.json()["error"]["code"]) == (404, "event_not_found")
        assert await rows(session_factory, OutboundMessageRow, bot) == []
