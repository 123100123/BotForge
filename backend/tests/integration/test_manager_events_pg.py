"""Telegram event management on Postgres (U7): PgStore's optional runtime services (display names,
group chats, the outbox) and the creation form end to end through ``BotRuntime`` with a real
session row between events. Needs a database."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.botspec.models import BotSpec
from app.db.models import BotChatRow, BotUser, OutboundMessageRow
from app.runtime.contracts import Actor, Button, RuntimeEvent, RuntimeResponse
from app.runtime.pg_store import PgStore
from app.runtime.runtime import BotRuntime
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory
from tests.unit.runtime.test_manager_events import CAP, TITLE, events_data

OWNER = Actor(id="900", display_name="مدیر", is_owner=True)
T0 = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)  # 12 Mehr 1405, 11:30 in Tehran: the form's "today"


@pytest.fixture
async def bot_id(make_bot: MakeBot) -> uuid.UUID:
    return (await make_bot(active=False))[0]


async def test_display_names_are_per_env(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        live = PgStore(session, bot_id, "live")
        await live.upsert_user(Actor(id="1", display_name="علی"))
        await PgStore(session, bot_id, "sandbox").upsert_user(Actor(id="2", display_name="سارا"))
        assert await live.display_names(["1", "2", "3"]) == {"1": "علی"}
        assert await live.display_names([]) == {}


async def test_group_chats_and_outbox_are_live_only(
    session_factory: SessionFactory, bot_id: uuid.UUID
) -> None:
    async with session_factory() as session:
        session.add(BotChatRow(bot_id=bot_id, chat_id=-100555, title="گروه", kind="supergroup"))
        session.add(BotChatRow(bot_id=bot_id, chat_id=-100666, title="رفته", kind="group", active=False))
        await session.commit()
    async with session_factory() as session:
        live = PgStore(session, bot_id, "live")
        sandbox = PgStore(session, bot_id, "sandbox")
        assert await live.group_chats() == [(-100555, "گروه")]
        assert await sandbox.group_chats() == []
        buttons = [[Button(label="مشاهده", data=f"{CAP}:item:1")]]
        assert await live.enqueue_outbox([1001, 1002, 1001], "سلام", buttons) is True
        assert await sandbox.enqueue_outbox([1003], "سلام") is False
        card = [[Button(label="شرکت می‌کنم", data=f"{CAP}:book:7")]]
        assert await live.enqueue_card(-100555, "کارت", card) is True
        assert await live.enqueue_card(-100555, "کارت با شمارش تازه", card) is False  # still queued
        assert await live.enqueue_card(-100666, "کارت", card) is True  # another group
        assert await sandbox.enqueue_card(-100555, "کارت", card) is None  # not live: nothing queued
        await session.commit()
    async with session_factory() as session:
        rows = (
            await session.execute(select(OutboundMessageRow).where(OutboundMessageRow.bot_id == bot_id))
        ).scalars()
        got = sorted((r.env, r.chat_id, r.text, r.status, r.buttons) for r in rows)
    card_button = [{"label": "شرکت می‌کنم", "data": f"{CAP}:book:7"}]
    assert got == [
        ("live", -100666, "کارت", "queued", [card_button]),
        ("live", -100555, "کارت", "queued", [card_button]),
        ("live", 1001, "سلام", "queued", [[{"label": "مشاهده", "data": f"{CAP}:item:1"}]]),
        ("live", 1002, "سلام", "queued", [[{"label": "مشاهده", "data": f"{CAP}:item:1"}]]),
    ]


async def test_create_and_publish_an_event_from_telegram(
    session_factory: SessionFactory, bot_id: uuid.UUID
) -> None:
    spec = BotSpec.model_validate(events_data())
    async with session_factory() as session:
        session.add(BotChatRow(bot_id=bot_id, chat_id=-100555, title="گروه کافه", kind="supergroup"))
        await session.commit()

    async def step(kind: str, value: str) -> RuntimeResponse:
        event = RuntimeEvent(
            bot_id=str(bot_id),
            env="live",
            actor=OWNER,
            kind=kind,  # type: ignore[arg-type]
            text=value if kind == "text" else None,
            data=value if kind == "callback" else None,
            now=T0,
        )
        async with session_factory() as session:
            response = await BotRuntime().handle(event, spec, PgStore(session, bot_id, "live", "900"))
            await session.commit()
        return response

    await step("callback", "nav:go:mgr.evt.new")
    await step("text", TITLE)
    await step("callback", f"{CAP}:skip:")
    await step("callback", f"{CAP}:ans:dx")
    await step("text", "۱۴۰۵/۷/۲۰")
    await step("text", "۱۸:۳۰")
    await step("callback", f"{CAP}:ans:o1")
    await step("callback", f"{CAP}:skip:")
    await step("text", "۳۰")
    published = await step("callback", f"{CAP}:ans:pub")

    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        [event] = await store.list_records("event")
        assert await store.get_session("900") is None
    assert event.data["starts_at"] == "2026-10-12T15:00:00+00:00"
    assert (event.data["category"], event.data["capacity"]) == ("سازمانی", 30)
    data = [b.data for row in published.messages[-1].buttons for b in row]
    assert data[0] == f"nav:go:mgr.evt.pub.{event.id}"

    await step("callback", f"nav:go:mgr.evt.pub.{event.id}.n100555")
    async with session_factory() as session:
        [card] = (
            await session.execute(select(OutboundMessageRow).where(OutboundMessageRow.bot_id == bot_id))
        ).scalars()
        assert (card.env, card.chat_id) == ("live", -100555)
        assert card.text.startswith(f"📅 {TITLE}")
        assert [b["data"] for row in card.buttons for b in row] == [f"{CAP}:book:{event.id}"]
        names = (
            await session.execute(select(BotUser.display_name).where(BotUser.bot_id == bot_id))
        ).scalars()
        assert list(names) == ["مدیر"]
