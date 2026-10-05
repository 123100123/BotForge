"""Capability Center API: toggles become ACTIVE revisions, modules write bot_modules. Needs a database."""

import asyncio
import uuid
from typing import Any

import httpx
from sqlalchemy import func, select

from app.botspec.models import BookingCapability, BotSpec
from app.db.models import Bot, BotModuleRow, Revision
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory

BOB = {"X-Test-User": "bob"}


async def active(session_factory: SessionFactory, bot_id: uuid.UUID) -> Revision:
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None and bot.active_revision_id is not None
        revision = await session.get(Revision, bot.active_revision_id)
        assert revision is not None
        return revision


async def revision_count(session_factory: SessionFactory, bot_id: uuid.UUID) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(Revision).where(Revision.bot_id == bot_id)
        return (await session.execute(stmt)).scalar_one()


async def modules(session_factory: SessionFactory, bot_id: uuid.UUID) -> dict[str, BotModuleRow]:
    async with session_factory() as session:
        rows = (await session.execute(select(BotModuleRow).where(BotModuleRow.bot_id == bot_id))).scalars()
        return {r.module: r for r in rows}


def caps_by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for cat in body["categories"] for c in cat["capabilities"]}


async def test_list(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot()
    res = await client.get(f"/bots/{bot_id}/capabilities")
    assert res.status_code == 200, res.text
    caps = caps_by_id(res.json())
    assert caps["booking"]["enabled"] and caps["booking"]["spec_keys"] == ["book_workshop"]
    assert caps["reporting"]["enabled"] and not caps["events"]["enabled"]
    assert caps["payments"]["configurable"] is False


async def test_other_owner_gets_404(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice")
    res = await client.get(f"/bots/{bot_id}/capabilities", headers=BOB)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "bot_not_found"


async def test_unknown_capability_404(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot()
    res = await client.post(f"/bots/{bot_id}/capabilities/teleport/enable", json={})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "capability_not_found"


async def test_enable_then_disable_events(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, first = await make_bot()
    base = await active(session_factory, bot_id)

    # dry run: plan only, nothing written
    res = await client.post(f"/bots/{bot_id}/capabilities/events/enable", json={"dry_run": True})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["applied"] is False and body["revision_id"] is None
    assert body["plan"]["will_enable"] == ["events"] and not body["plan"]["needs_agent"]
    assert await revision_count(session_factory, bot_id) == 1

    res = await client.post(f"/bots/{bot_id}/capabilities/events/enable", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["applied"] is True and body["revision_number"] == base.number + 1
    rev = await active(session_factory, bot_id)
    assert str(rev.id) == body["revision_id"] and rev.status == "active" and rev.parent_id == first
    spec = BotSpec.model_validate(rev.spec)
    events = spec.capability("events")
    assert isinstance(events, BookingCapability) and events.preset == "events" and events.enabled
    assert any(m.capability == "events" and m.view == "main" for m in spec.menu)
    assert rev.test_report and rev.test_report["failed"] == 0 and rev.test_report["total"] > 0
    assert any(s["id"].startswith("derived:events:") for s in rev.scenarios or [])
    assert rev.patch and rev.change_request

    caps = caps_by_id((await client.get(f"/bots/{bot_id}/capabilities")).json())
    assert caps["events"]["enabled"] and caps["events"]["spec_keys"] == ["events"]

    res = await client.post(f"/bots/{bot_id}/capabilities/events/disable", json={})
    assert res.status_code == 200, res.text
    assert res.json()["revision_number"] == base.number + 2
    off = await active(session_factory, bot_id)
    off_spec = BotSpec.model_validate(off.spec)
    disabled = off_spec.capability("events")
    assert isinstance(disabled, BookingCapability) and disabled.enabled is False
    assert disabled.model_dump(exclude={"enabled"}) == events.model_dump(exclude={"enabled"})  # config kept
    superseded_ids = {s["scenario"]["id"] for s in off.superseded or []}
    assert any(i.startswith("derived:events:") for i in superseded_ids)
    assert not any(s["id"].startswith("derived:events:") for s in off.scenarios or [])

    # enabling again flips the flag back on, without adding another capability
    res = await client.post(f"/bots/{bot_id}/capabilities/events/enable", json={})
    assert res.status_code == 200, res.text
    again = BotSpec.model_validate((await active(session_factory, bot_id)).spec)
    assert [c.key for c in again.capabilities].count("events") == 1
    assert again.capability("events").enabled  # type: ignore[union-attr]


async def test_module_dependencies(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    res = await client.post(f"/bots/{bot_id}/capabilities/staff_reporting/enable?dry_run=true")
    assert res.status_code == 200, res.text
    assert res.json()["plan"]["will_enable"] == ["staff", "spreadsheet_intelligence", "staff_reporting"]
    assert await modules(session_factory, bot_id) == {}

    res = await client.post(f"/bots/{bot_id}/capabilities/scheduled_reports/enable", json={})
    assert res.status_code == 200, res.text
    assert res.json()["applied"] is True and res.json()["revision_id"] is None
    rows = await modules(session_factory, bot_id)
    assert rows["scheduled_reports"].enabled
    assert await revision_count(session_factory, bot_id) == 1  # modules never make revisions

    # disabling reporting cascades to its dependents
    res = await client.post(f"/bots/{bot_id}/capabilities/reporting/disable", json={})
    assert res.status_code == 200, res.text
    assert res.json()["plan"]["will_disable"] == ["scheduled_reports", "reporting"]
    rows = await modules(session_factory, bot_id)
    assert not rows["reporting"].enabled and not rows["scheduled_reports"].enabled

    res = await client.post(f"/bots/{bot_id}/capabilities/scheduled_reports/enable", json={})
    assert res.json()["plan"]["will_enable"] == ["reporting", "scheduled_reports"]
    rows = await modules(session_factory, bot_id)
    assert rows["reporting"].enabled and rows["scheduled_reports"].enabled


async def test_payments_unavailable(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot()
    for body in ({}, {"dry_run": True}):
        res = await client.post(f"/bots/{bot_id}/capabilities/payments/enable", json=body)
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "capability_unavailable"


async def test_orders_needs_agent(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    res = await client.post(f"/bots/{bot_id}/capabilities/inventory/enable", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["applied"] is False and body["plan"]["needs_agent"] is True
    assert body["plan"]["will_enable"] == ["catalog", "orders", "inventory"]
    assert body["plan"]["handoff_prompt"]
    assert await modules(session_factory, bot_id) == {}  # nothing partially applied
    assert await revision_count(session_factory, bot_id) == 1


async def test_no_active_revision(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot(active=False)
    res = await client.post(f"/bots/{bot_id}/capabilities/events/enable", json={})
    assert res.status_code == 200
    assert res.json()["plan"]["needs_agent"] is True and res.json()["applied"] is False
    res = await client.patch(
        f"/bots/{bot_id}/capabilities/booking/config", json={"config": {"audience": "staff"}}
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "no_active_revision"


async def test_module_config(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    url = f"/bots/{bot_id}/capabilities/inventory/config"
    res = await client.patch(url, json={"config": {"low_stock_threshold": 3}})
    assert res.status_code == 200, res.text
    row = (await modules(session_factory, bot_id))["inventory"]
    assert row.config == {"low_stock_threshold": 3} and row.enabled is False

    res = await client.patch(url, json={"config": {"colour": "red"}})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_config"
    res = await client.patch(url, json={"config": {"low_stock_threshold": "many"}})
    assert res.status_code == 422


async def test_spec_config_audience_supersedes(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    assert (await client.post(f"/bots/{bot_id}/capabilities/events/enable", json={})).status_code == 200
    url = f"/bots/{bot_id}/capabilities/events/config"
    res = await client.patch(url, json={"config": {"audience": "staff", "reminder_hours_before": 48}})
    assert res.status_code == 200, res.text
    rev = await active(session_factory, bot_id)
    cap = BotSpec.model_validate(rev.spec).capability("events")
    assert isinstance(cap, BookingCapability)
    assert cap.audience == "staff" and cap.reminder_hours_before == 48
    assert any(s["reason"] for s in rev.superseded or [])

    res = await client.patch(url, json={"config": {"reminder_hours_before": 0}})
    assert res.status_code == 422
    res = await client.patch(f"/bots/{bot_id}/capabilities/info/config", json={"config": {"title": "x"}})
    assert res.status_code == 422


async def test_failing_carried_scenario_blocks_activation(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    broken = {
        "id": "acc:info_broken",
        "title": "سناریوی خراب",
        "source": "acceptance",
        "capability_keys": ["info"],
        "steps": [{"do": "open", "actor": "ali", "capability": "info", "contains": "متنی که وجود ندارد"}],
    }
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        revision = await session.get(Revision, bot.active_revision_id)
        assert revision is not None
        revision.scenarios = [broken]
        await session.commit()

    res = await client.post(f"/bots/{bot_id}/capabilities/events/enable", json={})
    assert res.status_code == 409, res.text
    error = res.json()["error"]
    assert error["code"] == "tests_failing" and error["details"]["failed_scenarios"] == ["acc:info_broken"]
    assert await revision_count(session_factory, bot_id) == 1

    # disabling the capability the broken scenario covers supersedes it, so that toggle goes through
    res = await client.post(f"/bots/{bot_id}/capabilities/info/disable", json={})
    assert res.status_code == 200, res.text
    rev = await active(session_factory, bot_id)
    assert [s["scenario"]["id"] for s in rev.superseded or []] == ["acc:info_broken"]


async def test_concurrent_toggles_serialize(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    results = await asyncio.gather(
        client.post(f"/bots/{bot_id}/capabilities/events/enable", json={}),
        client.post(f"/bots/{bot_id}/capabilities/support/enable", json={}),
    )
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    assert sorted(r.json()["revision_number"] for r in results) == [2, 3]
    spec = BotSpec.model_validate((await active(session_factory, bot_id)).spec)
    assert spec.capability("events") is not None and spec.capability("support") is not None


async def test_disable_last_capabilities_is_structured_error(
    client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot()
    assert (await client.post(f"/bots/{bot_id}/capabilities/info/disable", json={})).status_code == 200
    res = await client.post(f"/bots/{bot_id}/capabilities/booking/disable", json={})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "invalid_spec"
