"""Scheduled reports (W2-SCHED): the schedules API and the generator, on Postgres."""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.models import BotModuleRow, BotUser, OutboundMessageRow
from app.notifications.generators import scheduled_reports
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory
from tests.integration.tg_helpers import ALICE, LiveBot, make_live_bot

BOB = {"X-Test-User": "bob"}
OWNER, MANAGER, CUSTOMER = "7100", "7101", "7102"
FRIDAY_EVENING = datetime(2031, 1, 10, 15, 0, tzinfo=UTC)  # Friday 18:30 in Tehran
FRIDAY_NOON = datetime(2031, 1, 10, 8, 0, tzinfo=UTC)  # Friday 11:30 in Tehran
SATURDAY_EVENING = datetime(2031, 1, 11, 15, 0, tzinfo=UTC)
NEXT_FRIDAY_EVENING = datetime(2031, 1, 17, 15, 0, tzinfo=UTC)


def schedule(
    id_: str, kind: str, time: str, *, weekday: int | None = None, enabled: bool = True
) -> dict[str, Any]:
    return {"id": id_, "kind": kind, "time": time, "weekday": weekday, "enabled": enabled, "metrics": []}


def url(bot_id: uuid.UUID) -> str:
    return f"/bots/{bot_id}/schedules"


@pytest.fixture
async def live(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    bot = await make_live_bot(session_factory, golden_spec, owner_actor_id=OWNER)
    async with session_factory() as s:
        s.add_all(
            [
                BotUser(bot_id=bot.id, env="live", actor_id=MANAGER, display_name="مدیر", role="manager"),
                BotUser(bot_id=bot.id, env="live", actor_id=CUSTOMER, display_name="مشتری", role="customer"),
            ]
        )
        await s.commit()
    return bot


async def configure(
    session_factory: SessionFactory,
    bot: LiveBot,
    schedules: list[dict[str, Any]] | None,
    *,
    enabled: bool = True,
) -> None:
    config = {} if schedules is None else {"schedules": schedules}
    async with session_factory() as s:
        s.add(BotModuleRow(bot_id=bot.id, module="scheduled_reports", enabled=enabled, config=config))
        await s.commit()


async def tick(session_factory: SessionFactory, now: datetime) -> None:
    async with session_factory() as s:
        await scheduled_reports.generate(s, now)
        await s.commit()


async def outbox_rows(session_factory: SessionFactory, bot: LiveBot) -> list[OutboundMessageRow]:
    async with session_factory() as s:
        stmt = (
            select(OutboundMessageRow)
            .where(OutboundMessageRow.bot_id == bot.id)
            .order_by(OutboundMessageRow.id)
        )
        return list((await s.execute(stmt)).scalars())


# --- API ---------------------------------------------------------------------------------------


async def test_get_returns_defaults_then_put_round_trips_in_bot_modules(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice")
    first = await client.get(url(bot_id), headers=ALICE)
    assert first.status_code == 200
    defaults = first.json()
    assert [(s["kind"], s["time"], s["weekday"]) for s in defaults] == [
        ("daily_summary", "18:00", None),
        ("weekly_summary", "17:00", 4),
    ]
    assert not any(s["enabled"] for s in defaults)  # the module is not enabled

    wanted = [
        schedule("morning", "daily_summary", "08:30"),
        schedule("fri", "weekly_summary", "17:00", weekday=4, enabled=False),
    ]
    put = await client.put(url(bot_id), json={"schedules": wanted}, headers=ALICE)
    assert put.status_code == 200 and put.json() == wanted
    assert (await client.get(url(bot_id), headers=ALICE)).json() == wanted

    async with session_factory() as s:
        row = await s.get(BotModuleRow, (bot_id, "scheduled_reports"))
        assert row is not None and row.config == {"schedules": wanted} and row.enabled is False

    assert (await client.put(url(bot_id), json={"schedules": []}, headers=ALICE)).json() == []
    assert (await client.get(url(bot_id), headers=ALICE)).json() == []  # saved empty is not "defaults"


async def test_put_validates_and_get_is_owner_only(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice")
    daily = schedule("a", "daily_summary", "09:00")
    bad: list[Any] = [
        [daily, schedule("a", "daily_summary", "10:00")],  # duplicate id
        [schedule("a", "daily_summary", "9:00")],  # not HH:MM
        [schedule("a", "daily_summary", "24:00")],
        [schedule("a", "weekly_summary", "09:00")],  # weekly needs a weekday
        [schedule("bad id!", "daily_summary", "09:00")],
        [schedule(f"s{i}", "daily_summary", "09:00") for i in range(21)],  # more than 20
    ]
    for schedules in bad:
        response = await client.put(url(bot_id), json={"schedules": schedules}, headers=ALICE)
        assert response.status_code == 422, schedules
    assert (await client.get(url(bot_id), headers=ALICE)).status_code == 200
    assert (await client.get(url(bot_id), headers=BOB)).status_code == 404
    assert (await client.put(url(bot_id), json={"schedules": [daily]}, headers=BOB)).status_code == 404


async def test_enabling_the_module_makes_the_default_daily_report_enabled(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice")
    async with session_factory() as s:
        s.add(BotModuleRow(bot_id=bot_id, module="scheduled_reports", enabled=True, config={}))
        await s.commit()
    got = (await client.get(url(bot_id), headers=ALICE)).json()
    assert [s["enabled"] for s in got] == [True, False]


# --- generator ---------------------------------------------------------------------------------


async def test_a_due_daily_schedule_queues_one_row_per_manager_once_a_day(
    session_factory: SessionFactory, live: LiveBot
) -> None:
    await configure(session_factory, live, [schedule("daily", "daily_summary", "18:00")])
    await tick(session_factory, FRIDAY_NOON)
    assert await outbox_rows(session_factory, live) == []  # 11:30 is before 18:00

    await tick(session_factory, FRIDAY_EVENING)
    rows = await outbox_rows(session_factory, live)
    assert sorted(r.chat_id for r in rows) == [int(OWNER), int(MANAGER)]  # never the customer
    assert {r.dedupe_key for r in rows} == {
        f"rep:{live.id}:daily:2031-01-10:{OWNER}",
        f"rep:{live.id}:daily:2031-01-10:{MANAGER}",
    }
    assert all(r.status == "queued" and r.env == "live" for r in rows)
    text = rows[0].text
    assert text.startswith("گزارش روزانه") and "۲۰ دی ۱۴۰۹" in text  # Jalali date of 10 Jan 2031
    assert "نمای کلی کسب‌وکار" in text and "امروز" in text

    await tick(session_factory, FRIDAY_EVENING)
    await tick(session_factory, datetime(2031, 1, 10, 19, 0, tzinfo=UTC))  # later the same day
    assert len(await outbox_rows(session_factory, live)) == 2

    await tick(session_factory, SATURDAY_EVENING)  # the next day reports again
    assert len(await outbox_rows(session_factory, live)) == 4


async def test_weekly_schedule_respects_the_weekday(session_factory: SessionFactory, live: LiveBot) -> None:
    await configure(session_factory, live, [schedule("week", "weekly_summary", "17:00", weekday=4)])
    await tick(session_factory, SATURDAY_EVENING)  # Saturday: not Friday
    assert await outbox_rows(session_factory, live) == []
    await tick(session_factory, FRIDAY_EVENING)
    rows = await outbox_rows(session_factory, live)
    assert len(rows) == 2 and rows[0].text.startswith("گزارش هفتگی") and "این هفته" in rows[0].text
    await tick(session_factory, FRIDAY_EVENING)
    assert len(await outbox_rows(session_factory, live)) == 2
    await tick(session_factory, NEXT_FRIDAY_EVENING)
    assert len(await outbox_rows(session_factory, live)) == 4


async def test_disabled_schedule_disabled_module_and_missing_row_send_nothing(
    session_factory: SessionFactory, live: LiveBot
) -> None:
    await tick(session_factory, FRIDAY_EVENING)  # no bot_modules row: the module is off
    await configure(session_factory, live, [schedule("daily", "daily_summary", "18:00", enabled=False)])
    await tick(session_factory, FRIDAY_EVENING)
    async with session_factory() as s:
        row = await s.get(BotModuleRow, (live.id, "scheduled_reports"))
        assert row is not None
        row.config = {"schedules": [schedule("daily", "daily_summary", "18:00")]}
        row.enabled = False
        await s.commit()
    await tick(session_factory, FRIDAY_EVENING)
    assert await outbox_rows(session_factory, live) == []


async def test_default_schedules_apply_when_the_module_has_no_saved_list(
    session_factory: SessionFactory, live: LiveBot
) -> None:
    await configure(session_factory, live, None)
    await tick(session_factory, FRIDAY_EVENING)
    rows = await outbox_rows(session_factory, live)
    # the default daily report is on, the default weekly one is off
    assert len(rows) == 2 and all(":daily:" in (r.dedupe_key or "") for r in rows)
