"""Manager Copilot end to end: POST /bots/{id}/copilot/messages with a scripted FakeLLM, the module
toggle (409), the daily cap kept in ``bot_modules`` (429), unconfigured LLM (503) and the tools that
read analysis runs and the team. Needs a database."""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app.agent.llm import FakeLLM, LLMError, ToolCall
from app.api.copilot import get_copilot_llm
from app.config import get_settings
from app.db.models import AnalysisProfileRow, AnalysisRunRow, BotModuleRow, BotUser
from app.main import create_app
from app.roles.service import set_role
from app.runtime.pg_store import PgStore
from tests.integration.helpers import SessionFactory, signed_in_client
from tests.integration.test_team_api import repair_spec
from tests.integration.tg_helpers import LiveBot, make_live_bot

OWNER_TG = "900"
REPAIR = {"device": "یخچال", "problem": "صدا می‌دهد", "phone": "09123456789", "address": "تهران"}
ASK = {"messages": [{"role": "user", "content": "درخواست‌های تعمیر این هفته چطور بود؟"}]}


def script(*turns: Any) -> dict[str, list[list[Any]]]:
    return {"copilot": [list(turns)]}


def report_call() -> ToolCall:
    return ToolCall("get_capability_report", {"capability_key": "repair", "period": "7d"})


@asynccontextmanager
async def copilot_client(
    session_factory: SessionFactory, llm: FakeLLM | None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    if llm is not None:
        app.dependency_overrides[get_copilot_llm] = lambda: llm
    async with signed_in_client(app, session_factory) as c:
        yield c


@pytest.fixture
async def bot(session_factory: SessionFactory, tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, repair_spec(), owner_actor_id=OWNER_TG)


async def enable_copilot(session_factory: SessionFactory, bot_id: uuid.UUID, **config: Any) -> None:
    async with session_factory() as session:
        session.add(BotModuleRow(bot_id=bot_id, module="copilot", enabled=True, config=config))
        await session.commit()


async def usage_of(session_factory: SessionFactory, bot_id: uuid.UUID) -> dict[str, int]:
    async with session_factory() as session:
        row = await session.get(BotModuleRow, (bot_id, "copilot"))
        assert row is not None
        return row.config["usage"]


def url(bot_id: uuid.UUID) -> str:
    return f"/bots/{bot_id}/copilot/messages"


async def test_round_trip_with_tools(session_factory: SessionFactory, bot: LiveBot) -> None:
    await enable_copilot(session_factory, bot.id)
    async with session_factory() as session:
        store = PgStore(session, bot.id, "live", OWNER_TG)
        await store.create_record("repair", REPAIR, status="new", actor_id="1", now=datetime.now(UTC))
        await session.commit()
    fake = FakeLLM(loops=script([report_call()], [ToolCall("finish", {"reply": "۱ درخواست تعمیر ثبت شد."})]))
    async with copilot_client(session_factory, fake) as client:
        response = await client.post(url(bot.id), json=ASK)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == "۱ درخواست تعمیر ثبت شد."
    assert [(c["name"], c["arguments"]) for c in body["tool_calls"]] == [
        ("get_capability_report", {"capability_key": "repair", "period": "7d"})
    ]
    assert body["tool_calls"][0]["summary"] == "گزارش درخواست تعمیر برای ۷ روز گذشته"
    assert body["usage"]["input_tokens"] == 2000 and body["usage"]["output_tokens"] == 400
    assert {"cost_usd", "tool_calls", "llm_calls"} <= set(body["usage"])

    (call,) = fake.calls
    assert call.tier == "fast" and call.task == "copilot"
    assert call.messages == [{"role": "user", "content": ASK["messages"][0]["content"]}]
    assert "تعمیرات لوازم خانگی" in call.system and "capability_key=repair" in call.system
    result = fake.tool_results[0]
    assert result.is_error is False
    assert result.content["capability_key"] == "repair" and result.content["metrics"]
    blob = json.dumps(result.content, ensure_ascii=False)
    assert "09123456789" not in blob and "یخچال" not in blob  # aggregates only: no raw record fields


async def test_plain_text_answer_and_leading_assistant_turn_dropped(
    session_factory: SessionFactory, bot: LiveBot
) -> None:
    await enable_copilot(session_factory, bot.id)
    fake = FakeLLM(loops=script("داده‌ای برای نمایش نیست."))
    turns = [
        {"role": "assistant", "content": "سلام! چه کمکی از من برمی‌آید؟"},
        {"role": "user", "content": "گزارش امروز؟"},
    ]
    async with copilot_client(session_factory, fake) as client:
        response = await client.post(url(bot.id), json={"messages": turns})
    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "داده‌ای برای نمایش نیست." and response.json()["tool_calls"] == []
    assert fake.calls[0].messages == [{"role": "user", "content": "گزارش امروز؟"}]


async def test_disabled_module_is_409(session_factory: SessionFactory, bot: LiveBot) -> None:
    fake = FakeLLM()
    async with copilot_client(session_factory, fake) as client:
        response = await client.post(url(bot.id), json=ASK)
        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "capability_disabled",
            "message": "دستیار کسب‌وکار را از بخش قابلیت‌ها فعال کنید.",
        }
        async with session_factory() as session:  # an explicit "disabled" row behaves the same
            session.add(BotModuleRow(bot_id=bot.id, module="copilot", enabled=False, config={}))
            await session.commit()
        assert (await client.post(url(bot.id), json=ASK)).status_code == 409
    assert fake.calls == []


async def test_daily_cap_is_kept_in_bot_modules(
    session_factory: SessionFactory, bot: LiveBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COPILOT_DAILY_CAP", "2")
    get_settings.cache_clear()
    old = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    await enable_copilot(session_factory, bot.id, usage={old: 9}, other="kept")
    fake = FakeLLM(loops={"copilot": [["ا"], ["ب"], ["ج"]]})
    async with copilot_client(session_factory, fake) as client:
        first = await client.post(url(bot.id), json=ASK)
        second = await client.post(url(bot.id), json=ASK)
        third = await client.post(url(bot.id), json=ASK)
    assert (first.status_code, second.status_code, third.status_code) == (200, 200, 429)
    assert third.json()["error"]["code"] == "copilot_daily_cap"
    assert len(fake.calls) == 2  # the refused question never reached the model
    usage = await usage_of(session_factory, bot.id)
    assert usage[old] == 9 and sum(v for k, v in usage.items() if k != old) == 2
    assert len(usage) == 2  # the old day is kept (within a week would be too); today's day has the count
    async with session_factory() as session:
        row = await session.get(BotModuleRow, (bot.id, "copilot"))
        assert row is not None and row.config["other"] == "kept"


async def test_unconfigured_llm_is_503(
    session_factory: SessionFactory, bot: LiveBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    await enable_copilot(session_factory, bot.id)
    async with copilot_client(session_factory, None) as client:
        response = await client.post(url(bot.id), json=ASK)
    assert response.status_code == 503 and response.json()["error"]["code"] == "llm_unavailable"
    assert await usage_of_or_none(session_factory, bot.id) is None  # nothing was counted


async def usage_of_or_none(session_factory: SessionFactory, bot_id: uuid.UUID) -> Any:
    async with session_factory() as session:
        row = await session.get(BotModuleRow, (bot_id, "copilot"))
        return None if row is None else row.config.get("usage")


async def test_llm_failure_is_502(session_factory: SessionFactory, bot: LiveBot) -> None:
    await enable_copilot(session_factory, bot.id)

    class Broken(FakeLLM):
        async def tool_loop(self, **_: Any) -> Any:
            raise LLMError("api_error", "boom")

    async with copilot_client(session_factory, Broken()) as client:
        response = await client.post(url(bot.id), json=ASK)
    assert response.status_code == 502 and response.json()["error"]["code"] == "llm_failed"


async def test_ownership_and_request_validation(session_factory: SessionFactory, bot: LiveBot) -> None:
    await enable_copilot(session_factory, bot.id)
    async with copilot_client(session_factory, FakeLLM()) as client:
        other = await client.post(url(bot.id), json=ASK, headers={"X-Test-User": "bob"})
        assert other.status_code == 404
        last_is_assistant = {"messages": [{"role": "assistant", "content": "x"}]}
        assert (await client.post(url(bot.id), json=last_is_assistant)).status_code == 422
        assert (await client.post(url(bot.id), json={"messages": []})).status_code == 422
        assert (await client.post(url(uuid.uuid4()), json=ASK)).status_code == 404


async def test_invalid_tool_arguments_reach_the_model_as_errors(
    session_factory: SessionFactory, bot: LiveBot
) -> None:
    await enable_copilot(session_factory, bot.id)
    fake = FakeLLM(
        loops=script(
            [
                ToolCall("get_capability_report", {"capability_key": "nope", "period": "7d"}),
                ToolCall("get_capability_report", {"capability_key": "repair", "period": "fortnight"}),
            ],
            "نتوانستم گزارش را بگیرم.",
        )
    )
    async with copilot_client(session_factory, fake) as client:
        response = await client.post(url(bot.id), json=ASK)
    assert response.status_code == 200
    assert [r.content["error"] for r in fake.tool_results] == ["invalid_capability_key", "invalid_period"]
    assert all(r.is_error for r in fake.tool_results)
    assert len(response.json()["tool_calls"]) == 2  # rejected calls are still shown


async def seed_analysis(session_factory: SessionFactory, bot: LiveBot) -> None:
    """Profile «فروش روزانه» with two runs today (one by staff 111, one by the owner) and one old run;
    staff 111 and 222 plus the owner as members."""
    async with session_factory() as session:
        await set_role(session, bot.id, "live", "111", "staff", display_name="علی")
        await set_role(session, bot.id, "live", "222", "staff", display_name="سارا")
        session.add(
            BotUser(bot_id=bot.id, env="live", actor_id=OWNER_TG, display_name="مالک", role="customer")
        )
        profile = AnalysisProfileRow(
            bot_id=bot.id, name="فروش روزانه", signature="sig", sheet="Sheet1", expected_columns=["a"]
        )
        session.add(profile)
        await session.flush()
        result = {
            "metrics": [
                {
                    "id": "total",
                    "label": "جمع فروش",
                    "kind": "scalar",
                    "value": 1250000.0,
                    "previous": 1000000.0,
                },
                {"id": "by_day", "label": "روزانه", "kind": "series", "series": [{"label": "a", "value": 1}]},
            ],
            "anomalies": [
                {
                    "check_id": "c",
                    "label": "فروش بالا",
                    "field": "amount",
                    "group": "شعبه ۲",
                    "value": 9.0,
                    "expected": 3.0,
                    "severity": "warning",
                }
            ],
        }
        now = datetime.now(UTC)
        for who, at in [("111", now), (OWNER_TG, now), ("222", now - timedelta(days=3))]:
            session.add(
                AnalysisRunRow(
                    bot_id=bot.id,
                    profile_id=profile.id,
                    status="ok",
                    submitted_by=who,
                    result=result,
                    created_at=at,
                )
            )
        await session.commit()


async def test_spreadsheet_and_submission_tools(session_factory: SessionFactory, bot: LiveBot) -> None:
    await enable_copilot(session_factory, bot.id)
    await seed_analysis(session_factory, bot)
    fake = FakeLLM(
        loops=script(
            [
                ToolCall("get_spreadsheet_report", {"profile_name": "فروش روزانه", "latest": True}),
                ToolCall("get_spreadsheet_report", {"profile_name": None, "latest": False}),
                ToolCall("get_spreadsheet_report", {"profile_name": "ناشناس", "latest": True}),
                ToolCall("who_submitted", {"profile_name": "فروش روزانه", "date": "today"}),
                ToolCall("who_submitted", {"profile_name": "فروش روزانه", "date": "پریروز"}),
                ToolCall("list_pending_approvals", {"limit": 3}),
            ],
            "ok",
        )
    )
    async with copilot_client(session_factory, fake) as client:
        response = await client.post(url(bot.id), json=ASK)
    assert response.status_code == 200, response.text
    latest, recent, unknown, today, bad_date, pending = (r.content for r in fake.tool_results)

    assert latest["ok"] is True and latest["profiles"] == ["فروش روزانه"]
    run = latest["run"]
    assert run["status"] == "ok" and [m["id"] for m in run["metrics"]] == ["total"]  # scalars only
    assert run["metrics"][0]["value"] == 1250000 and run["metrics"][0]["previous"] == 1000000
    assert run["anomalies"] == [
        {
            "label": "فروش بالا",
            "field": "amount",
            "group": "شعبه ۲",
            "value": 9.0,
            "expected": 3.0,
            "severity": "warning",
        }
    ]
    assert len(recent["runs"]) == 3 and recent["runs"][0]["anomaly_count"] == 1
    assert unknown["error"] == "invalid_profile_name" and unknown["valid"] == ["فروش روزانه"]

    assert today["submitted"] == ["علی"] and today["not_submitted"] == ["سارا"]  # the owner is not staff
    assert today["total_staff"] == 2 and today["profile"] == "فروش روزانه"
    assert bad_date["error"] == "invalid_date"
    assert pending["ok"] is True and pending["items"] == [] and pending["total_pending"] == 0
    summaries = [c["summary"] for c in response.json()["tool_calls"]]
    assert summaries[3] == "بررسی ارسال گزارش «فروش روزانه» برای امروز"


async def test_who_submitted_for_a_past_day(session_factory: SessionFactory, bot: LiveBot) -> None:
    await enable_copilot(session_factory, bot.id)
    await seed_analysis(session_factory, bot)
    day = (datetime.now(UTC) - timedelta(days=3)).astimezone(ZoneInfo("Asia/Tehran")).date().isoformat()
    probe = ToolCall("who_submitted", {"profile_name": "فروش روزانه", "date": day})
    fake = FakeLLM(loops=script([probe], "ok"))
    async with copilot_client(session_factory, fake) as client:
        assert (await client.post(url(bot.id), json=ASK)).status_code == 200
    out = fake.tool_results[0].content
    assert out["ok"] is True and out["date"] == day
    assert out["submitted"] == ["سارا"] and out["not_submitted"] == ["علی"] and out["total_staff"] == 2


async def test_no_spreadsheet_data_yet(session_factory: SessionFactory, bot: LiveBot) -> None:
    await enable_copilot(session_factory, bot.id)
    fake = FakeLLM(loops=script([ToolCall("get_spreadsheet_report", {})], "ok"))
    async with copilot_client(session_factory, fake) as client:
        assert (await client.post(url(bot.id), json=ASK)).status_code == 200
    assert fake.tool_results[0].content["runs"] == [] and fake.tool_results[0].content["profiles"] == []


async def test_pending_approvals_reads_open_requests(session_factory: SessionFactory, bot: LiveBot) -> None:
    await enable_copilot(session_factory, bot.id)
    now = datetime.now(UTC)
    async with session_factory() as session:
        store = PgStore(session, bot.id, "live", OWNER_TG)
        await store.create_record("repair", REPAIR, status="new", actor_id="1", now=now)
        await store.create_record(
            "repair", {**REPAIR, "device": "پنکه"}, status="done", actor_id="2", now=now
        )
        await session.commit()
    fake = FakeLLM(loops=script([ToolCall("list_pending_approvals", {})], "ok"))
    async with copilot_client(session_factory, fake) as client:
        assert (await client.post(url(bot.id), json=ASK)).status_code == 200
    out = fake.tool_results[0].content
    assert out["total_pending"] == 1
    assert out["items"][0]["title"] == "یخچال" and "phone" not in json.dumps(out)  # never the phone number


async def test_members_listing_is_scoped_to_the_bot(session_factory: SessionFactory, bot: LiveBot) -> None:
    """Another bot's staff never show up in who_submitted."""
    await enable_copilot(session_factory, bot.id)
    await seed_analysis(session_factory, bot)
    other = await make_live_bot(session_factory, repair_spec(), owner_actor_id="901")
    async with session_factory() as session:
        await set_role(session, other.id, "live", "333", "staff", display_name="غریبه")
        await session.commit()
    fake = FakeLLM(
        loops=script([ToolCall("who_submitted", {"profile_name": "فروش روزانه", "date": "today"})], "ok")
    )
    async with copilot_client(session_factory, fake) as client:
        assert (await client.post(url(bot.id), json=ASK)).status_code == 200
    content = fake.tool_results[0].content
    assert "غریبه" not in json.dumps(content, ensure_ascii=False)
    async with session_factory() as session:
        rows = (
            (await session.execute(select(BotUser.actor_id).where(BotUser.bot_id == other.id)))
            .scalars()
            .all()
        )
        assert "333" in rows
