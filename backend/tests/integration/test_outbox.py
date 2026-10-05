"""Notification outbox, generators and ticker on Postgres. Telegram is the fake client throughout."""

import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.db.models import AnnouncementRow, BotChatRow, BotUser, OutboundMessageRow, RecordRow
from app.integrations.telegram.client import FakeTelegramClient, TelegramError
from app.notifications import outbox
from app.notifications.generators import Generator, announcements, reminders
from app.notifications.ticker import NotificationTicker
from app.runtime.pg_store import PgStore
from tests.integration.helpers import SessionFactory
from tests.integration.tg_helpers import CAP, LiveBot, make_live_bot

T0 = datetime(2031, 1, 10, 12, 0, tzinfo=UTC)  # far from other tests' item starts
OWNER, CUSTOMER, STAFF, MANAGER = 7000, 7001, 7002, 7003


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


def reminder_spec(golden: dict[str, Any], *, preset: str = "booking") -> dict[str, Any]:
    spec = copy.deepcopy(golden)
    for cap in spec["capabilities"]:
        if cap["key"] == CAP:
            cap["reminder_hours_before"] = 24
            cap["preset"] = preset
    return spec


@pytest.fixture
async def bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, reminder_spec(golden_spec), owner_actor_id=str(OWNER))


def ticker(
    session_factory: SessionFactory, fake: FakeTelegramClient, bot: LiveBot, **kw: Any
) -> NotificationTicker:
    clock = FakeClock()
    return NotificationTicker(
        session_factory, fake.provider, bot_ids={bot.id}, sleep=clock.sleep, clock=clock, now=lambda: T0, **kw
    )


async def rows(session_factory: SessionFactory, bot: LiveBot) -> list[OutboundMessageRow]:
    async with session_factory() as s:
        stmt = (
            select(OutboundMessageRow)
            .where(OutboundMessageRow.bot_id == bot.id)
            .order_by(OutboundMessageRow.id)
        )
        return list((await s.execute(stmt)).scalars())


async def put(
    session_factory: SessionFactory, bot: LiveBot, chat: int, key: str | None = None, **kw: Any
) -> bool:
    async with session_factory() as s:
        done = await outbox.enqueue(
            s, bot_id=bot.id, env=kw.pop("env", "live"), chat_id=chat, text="سلام", dedupe_key=key, **kw
        )
        await s.commit()
        return done


async def test_enqueue_dedupes_per_bot(session_factory: SessionFactory, bot: LiveBot) -> None:
    assert await put(session_factory, bot, 1, "k1", buttons=[[{"label": "باز", "data": "menu:open:x"}]])
    assert not await put(session_factory, bot, 2, "k1")
    assert await put(session_factory, bot, 1) and await put(session_factory, bot, 1)  # NULL never collides
    saved = await rows(session_factory, bot)
    assert len(saved) == 3 and saved[0].buttons == [[{"label": "باز", "data": "menu:open:x"}]]


async def test_claim_skips_rows_locked_by_another_transaction(
    session_factory: SessionFactory, bot: LiveBot
) -> None:
    for chat in (1, 2, 3):
        await put(session_factory, bot, chat)
    async with session_factory() as first, session_factory() as second:
        claimed = await outbox.claim_due(first, 2, only_bots={bot.id})
        rest = await outbox.claim_due(second, 10, only_bots={bot.id})
        assert len(claimed) == 2 and len(rest) == 1
        assert {r.id for r in claimed}.isdisjoint({r.id for r in rest})
        await second.rollback()
        again = await outbox.claim_due(second, 10, only_bots={bot.id})
        assert [r.id for r in again] == [r.id for r in rest]  # first still holds its two
        await first.rollback()
        await second.rollback()
        assert len(await outbox.claim_due(second, 10, only_bots={bot.id})) == 3


async def test_mark_failed_backs_off_then_fails(session_factory: SessionFactory, bot: LiveBot) -> None:
    await put(session_factory, bot, 1)
    async with session_factory() as s:
        (row,) = await outbox.claim_due(s, 1, only_bots={bot.id})
        outbox.mark_failed(row, "sendMessage: boom", now=T0)
        assert (row.status, row.attempts, row.not_before) == ("queued", 1, T0 + timedelta(seconds=30))
        outbox.mark_failed(row, "sendMessage: flood", now=T0, retry_after=600)
        assert row.not_before == T0 + timedelta(seconds=600)
        for _ in range(3):
            outbox.mark_failed(row, "sendMessage: boom", now=T0)
        assert (row.status, row.attempts) == ("failed", 5)
        await s.commit()
        assert not await outbox.claim_due(s, 10, only_bots={bot.id})
        await s.rollback()


async def seed_booking(
    session_factory: SessionFactory, bot: LiveBot, start: datetime, actor: str, status: str
) -> int:
    async with session_factory() as s:
        store = PgStore(s, bot.id, "live")
        item = await store.create_record(
            "workshop", {"title": "عکاسی", "starts_at": start.isoformat()}, now=T0
        )
        await store.create_record(CAP, {}, status=status, actor_id=actor, item_id=item.id, now=T0)
        await s.commit()
        return item.id


async def generate(session_factory: SessionFactory, fn: Any) -> None:
    async with session_factory() as s:
        await fn(s, T0)
        await s.commit()


async def test_reminder_once_per_start_then_delivered(
    session_factory: SessionFactory, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    item = await seed_booking(session_factory, bot, T0 + timedelta(hours=23), str(CUSTOMER), "confirmed")
    await seed_booking(session_factory, bot, T0 + timedelta(hours=23), str(STAFF), "waitlisted")
    await seed_booking(session_factory, bot, T0 + timedelta(hours=30), str(MANAGER), "confirmed")  # too early
    await generate(session_factory, reminders.generate)
    await generate(session_factory, reminders.generate)
    (row,) = await rows(session_factory, bot)
    assert (
        row.chat_id == CUSTOMER
        and row.text.startswith("یادآوری: «عکاسی»")
        and row.dedupe_key.startswith("rem:")
    )

    t = ticker(session_factory, fake_tg, bot)
    assert await t.tick() == 1  # the second tick's generator run must not add a row
    assert await t.tick() == 0
    (sent,) = fake_tg.sent_to(CUSTOMER)
    assert sent["text"].startswith("یادآوری") and len(await rows(session_factory, bot)) == 1
    assert (await rows(session_factory, bot))[0].status == "sent"

    async with session_factory() as s:  # the event moves: a new reminder for the new start
        new_start = (T0 + timedelta(hours=20)).isoformat()
        await s.execute(
            update(RecordRow)
            .where(RecordRow.id == item)
            .values(data={"title": "عکاسی", "starts_at": new_start})
        )
        await s.commit()
    await generate(session_factory, reminders.generate)
    assert len(await rows(session_factory, bot)) == 2


async def test_sandbox_rows_never_reach_telegram(
    session_factory: SessionFactory, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    await put(session_factory, bot, CUSTOMER, env="sandbox")
    assert await ticker(session_factory, fake_tg, bot, generators=[]).tick() == 0
    assert fake_tg.calls == [] and (await rows(session_factory, bot))[0].status == "sent"


class FloodClient(FakeTelegramClient):
    async def send_message(self, chat_id: int | str, text: str, reply_markup: Any = None) -> dict[str, Any]:
        self.calls.append(("sendMessage", {"chat_id": chat_id}))
        raise TelegramError("sendMessage", "Too Many Requests", error_code=429, retry_after=120)


async def test_telegram_errors_requeue_or_fail(session_factory: SessionFactory, bot: LiveBot) -> None:
    await put(session_factory, bot, CUSTOMER)
    await put(session_factory, bot, STAFF)
    flood = FloodClient()
    assert await ticker(session_factory, flood, bot, generators=[]).tick() == 0
    assert len(flood.calls) == 1  # the bot is paused after the 429; the other row waits untouched
    first, second = await rows(session_factory, bot)
    assert (first.status, first.attempts, second.attempts) == ("queued", 1, 0)
    assert first.not_before >= datetime.now(UTC) + timedelta(seconds=110)

    blocked = FakeTelegramClient()
    blocked.fail_methods["sendMessage"] = "Forbidden: bot was blocked by the user"
    await ticker(session_factory, blocked, bot, generators=[]).tick()
    assert (await rows(session_factory, bot))[1].status == "failed"  # 4xx: no retries


async def test_announcement_fans_out_by_audience(
    session_factory: SessionFactory, client: httpx.AsyncClient, bot: LiveBot
) -> None:
    async with session_factory() as s:
        for actor, role in (
            (CUSTOMER, "customer"),
            (STAFF, "staff"),
            (MANAGER, "manager"),
            ("demo-01", "customer"),
        ):
            s.add(BotUser(bot_id=bot.id, env="live", actor_id=str(actor), display_name="x", role=role))
        s.add(BotChatRow(bot_id=bot.id, chat_id=-100555, title="گروه", kind="supergroup"))
        await s.commit()
    url = f"/bots/{bot.id}/announcements"
    staff = await client.post(
        url, json={"text": "جلسه", "audience": "staff", "group_chat_ids": [-100555, -1]}
    )
    assert staff.status_code == 201 and staff.json()["status"] == "queued"
    assert (await client.post(url, json={"text": "تخفیف", "audience": "customers"})).status_code == 201
    await generate(session_factory, announcements.generate)
    await generate(session_factory, announcements.generate)  # fanned out once
    by_text: dict[str, set[int]] = {}
    for row in await rows(session_factory, bot):
        by_text.setdefault(row.text.split("\n")[-1], set()).add(row.chat_id)
    assert by_text == {"جلسه": {OWNER, STAFF, MANAGER, -100555}, "تخفیف": {CUSTOMER}}
    listed = (await client.get(url)).json()
    assert [(a["text"], a["status"], a["recipients"]) for a in listed] == [
        ("تخفیف", "sent", 1),
        ("جلسه", "sent", 4),
    ]
    assert (await client.get(url, headers={"X-Test-User": "bob"})).status_code == 404


async def test_subscribers_follow_their_category(
    session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None
) -> None:
    bot = await make_live_bot(session_factory, reminder_spec(golden_spec, preset="events"))
    async with session_factory() as s:
        store = PgStore(s, bot.id, "live")
        await store.create_record(f"{CAP}.subs", {"category": "art"}, actor_id=str(CUSTOMER), now=T0)
        await store.create_record(f"{CAP}.subs", {"category": "music"}, actor_id=str(STAFF), now=T0)
        s.add(
            AnnouncementRow(
                id=uuid.uuid4(), bot_id=bot.id, text="نمایشگاه", audience="subscribers", category="art"
            )
        )
        await s.commit()
    await generate(session_factory, announcements.generate)
    assert [r.chat_id for r in await rows(session_factory, bot)] == [CUSTOMER]


async def test_running_ticker_isolates_generator_failures_and_stops(
    session_factory: SessionFactory, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    async def boom(session: Any, now: datetime) -> None:
        raise RuntimeError("generator bug")

    async def one(session: Any, now: datetime) -> None:
        await outbox.enqueue(
            session, bot_id=bot.id, env="live", chat_id=CUSTOMER, text="سلام", dedupe_key="one"
        )

    t = ticker(session_factory, fake_tg, bot, generators=[Generator("boom", boom), Generator("one", one)])
    t.start()
    for _ in range(100):
        if fake_tg.sent_to(CUSTOMER):
            break
        await asyncio.sleep(0.02)
    await t.stop()
    assert len(fake_tg.sent_to(CUSTOMER)) == 1 and (await rows(session_factory, bot))[0].status == "sent"
