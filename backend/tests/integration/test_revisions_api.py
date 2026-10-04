"""Revision list / detail / diff / rollback / on-demand test runs. Needs a database."""

import copy
import json
import uuid
from typing import Any

import httpx
from sqlalchemy import select

from app.db.models import Bot, Revision
from app.revisions.service import activate, create_draft
from tests.integration.conftest import MakeBot
from tests.integration.helpers import REPO, SessionFactory
from tests.integration.tg_helpers import ALICE, CAP

BOB = {"X-Test-User": "bob"}
CHANGE = "ظرفیت هر کارگاه را ۱۲ نفر کن."


def golden_scenarios() -> list[dict[str, Any]]:
    return json.loads((REPO / "examples" / "workshop.scenarios.json").read_text(encoding="utf-8"))


def with_capacity(spec: dict[str, Any], capacity: int) -> dict[str, Any]:
    changed = copy.deepcopy(spec)
    for cap in changed["capabilities"]:
        if cap["key"] == CAP:
            cap["capacity"]["value"] = capacity
    return changed


async def add_revision(
    session_factory: SessionFactory, bot_id: uuid.UUID, spec: dict[str, Any], *, activate_it: bool, **kw: Any
) -> uuid.UUID:
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        revision = await create_draft(session, bot_id, spec=spec, parent_id=bot.active_revision_id, **kw)
        if activate_it:
            await activate(session, revision.id)
        await session.commit()
        return revision.id


async def status_of(
    session_factory: SessionFactory, bot_id: uuid.UUID
) -> tuple[uuid.UUID | None, dict[int, str]]:
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        rows = (await session.execute(select(Revision).where(Revision.bot_id == bot_id))).scalars().all()
        assert bot is not None
        return bot.active_revision_id, {r.number: r.status for r in rows}


PASSING = {"total": 9, "passed": 9, "failed": 0, "results": [], "duration_ms": 3}


async def history(
    session_factory: SessionFactory, make_bot: MakeBot, golden_spec: dict[str, Any]
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Bot with revision 1 (superseded) and revision 2 (active, capacity 12)."""
    bot_id, first = await make_bot("alice", active=False)
    assert first is None
    first = await add_revision(
        session_factory,
        bot_id,
        golden_spec,
        activate_it=True,
        scenarios=golden_scenarios(),
        test_report=PASSING,
        change_request="نسخهٔ اول",
    )
    second = await add_revision(
        session_factory,
        bot_id,
        with_capacity(golden_spec, 12),
        activate_it=True,
        change_request=CHANGE,
        test_report={**PASSING, "total": 10, "passed": 10},
    )
    return bot_id, first, second


async def test_list_is_newest_first_with_test_counts(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, _first, second = await history(session_factory, make_bot, golden_spec)
    response = await tg_client.get(f"/bots/{bot_id}/revisions", headers=ALICE)
    assert response.status_code == 200
    rows = response.json()
    assert [r["number"] for r in rows] == [2, 1]
    assert set(rows[0]) == {"id", "number", "status", "change_request", "created_at", "activated_at", "tests"}
    assert (
        rows[0]["id"] == str(second) and rows[0]["status"] == "active" and rows[0]["change_request"] == CHANGE
    )
    assert rows[1]["status"] == "superseded" and rows[1]["activated_at"] is not None
    assert rows[1]["tests"] == {"total": 9, "passed": 9, "failed": 0}
    assert rows[0]["tests"] == {"total": 10, "passed": 10, "failed": 0}


async def test_list_tests_is_null_without_a_report_and_is_scoped_to_the_bot(
    tg_client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    mine, _ = await make_bot("alice")
    await make_bot("alice")  # another bot's revision must not show up
    rows = (await tg_client.get(f"/bots/{mine}/revisions", headers=ALICE)).json()
    assert len(rows) == 1 and rows[0]["tests"] is None
    empty, _ = await make_bot("alice", active=False)
    assert (await tg_client.get(f"/bots/{empty}/revisions", headers=ALICE)).json() == []


async def test_detail_of_a_first_revision_has_an_empty_diff(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, golden_spec: dict[str, Any]
) -> None:
    bot_id, revision_id = await make_bot("alice")
    response = await tg_client.get(f"/revisions/{revision_id}", headers=ALICE)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "bot_id",
        "number",
        "status",
        "parent_id",
        "change_request",
        "created_at",
        "activated_at",
        "spec",
        "requirements",
        "scenarios",
        "superseded",
        "test_report",
        "diff",
    }
    assert body["bot_id"] == str(bot_id) and body["number"] == 1 and body["parent_id"] is None
    assert body["diff"] == [] and body["spec"] == golden_spec


async def test_detail_diff_against_the_parent(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    _, first, second = await history(session_factory, make_bot, golden_spec)
    body = (await tg_client.get(f"/revisions/{second}", headers=ALICE)).json()
    assert body["parent_id"] == str(first) and body["change_request"] == CHANGE
    [change] = body["diff"]
    assert change["path"] == ["capabilities", CAP, "capacity", "value"]
    assert (change["kind"], change["old"], change["new"]) == ("changed", 10, 12)
    assert "۱۰" in change["label_fa"] and "۱۲" in change["label_fa"]
    assert set(change) == {"path", "kind", "old", "new", "label_fa"}

    first_body = (await tg_client.get(f"/revisions/{first}", headers=ALICE)).json()
    assert first_body["diff"] == [] and len(first_body["scenarios"]) == 9


async def test_rollback_reactivates_the_old_revision_without_creating_a_new_one(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, first, _second = await history(session_factory, make_bot, golden_spec)
    response = await tg_client.post(f"/revisions/{first}/activate", headers=ALICE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(first) and body["number"] == 1 and body["status"] == "active"
    assert body["tests"] == {"total": 9, "passed": 9, "failed": 0}
    active_id, statuses = await status_of(session_factory, bot_id)
    assert active_id == first and statuses == {1: "active", 2: "superseded"}

    # the simulator now serves the rolled-back spec
    sim = await tg_client.post(
        f"/bots/{bot_id}/simulator/events",
        json={"revision_id": None, "persona": "ali", "kind": "start"},
        headers=ALICE,
    )
    assert sim.status_code == 200


async def test_rollback_rules(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, first, second = await history(session_factory, make_bot, golden_spec)
    # the active revision cannot be "rolled back to"
    active = await tg_client.post(f"/revisions/{second}/activate", headers=ALICE)
    assert active.status_code == 409 and active.json()["error"]["code"] == "invalid_revision_state"
    # neither can a draft (drafts are approved through the agent run)
    draft = await add_revision(session_factory, bot_id, golden_spec, activate_it=False)
    refused = await tg_client.post(f"/revisions/{draft}/activate", headers=ALICE)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "invalid_revision_state"
    # a superseded revision whose tests fail is blocked
    async with session_factory() as session:
        row = await session.get(Revision, first)
        assert row is not None
        row.test_report = {"total": 1, "passed": 0, "failed": 1, "results": [], "duration_ms": 1}
        await session.commit()
    blocked = await tg_client.post(f"/revisions/{first}/activate", headers=ALICE)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "tests_failing"
    assert blocked.json()["error"]["message"]
    active_id, statuses = await status_of(session_factory, bot_id)
    assert active_id == second and statuses == {1: "superseded", 2: "active", 3: "draft"}


async def test_tests_run_reruns_the_stored_scenarios_and_stores_the_report(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    revision_id = await add_revision(
        session_factory, bot_id, golden_spec, activate_it=False, scenarios=golden_scenarios()
    )
    response = await tg_client.post(f"/revisions/{revision_id}/tests/run", headers=ALICE)
    assert response.status_code == 200, response.text
    report = response.json()
    assert (report["total"], report["passed"], report["failed"]) == (9, 9, 0)
    assert {r["scenario_id"] for r in report["results"]} >= {"golden_basic_book", "golden_promotion_notifies"}
    assert all(s["narrative"] for r in report["results"] for s in r["steps"])
    stored = (await tg_client.get(f"/revisions/{revision_id}", headers=ALICE)).json()["test_report"]
    assert stored["total"] == 9 and stored["passed"] == 9
    listed = (await tg_client.get(f"/bots/{bot_id}/revisions", headers=ALICE)).json()
    assert listed[0]["tests"] == {"total": 9, "passed": 9, "failed": 0}


async def test_tests_run_reports_failures_against_the_revisions_own_spec(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    broken = copy.deepcopy(golden_spec)
    for cap in broken["capabilities"]:
        if cap["key"] == CAP:
            cap["waitlist"]["enabled"] = False  # the waitlist scenarios must now fail
    revision_id = await add_revision(
        session_factory, bot_id, broken, activate_it=False, scenarios=golden_scenarios(), test_report=PASSING
    )
    report = (await tg_client.post(f"/revisions/{revision_id}/tests/run", headers=ALICE)).json()
    assert report["failed"] > 0 and report["passed"] + report["failed"] == 9
    assert (await tg_client.get(f"/revisions/{revision_id}", headers=ALICE)).json()["test_report"][
        "failed"
    ] > 0


async def test_another_owners_revisions_are_404(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, first, _ = await history(session_factory, make_bot, golden_spec)
    assert (await tg_client.get(f"/bots/{bot_id}/revisions", headers=BOB)).status_code == 404
    assert (await tg_client.get(f"/revisions/{first}", headers=BOB)).status_code == 404
    assert (await tg_client.post(f"/revisions/{first}/activate", headers=BOB)).status_code == 404
    assert (await tg_client.post(f"/revisions/{first}/tests/run", headers=BOB)).status_code == 404
    assert (await tg_client.get(f"/revisions/{uuid.uuid4()}", headers=ALICE)).status_code == 404
