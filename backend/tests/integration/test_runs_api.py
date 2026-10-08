"""Agent runs API with FakeLLM injected and the SQL repository. Needs TEST_DATABASE_URL."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent.context import get_agent_settings
from app.agent.events import EventBus
from app.agent.llm import FakeLLM
from app.agent.orchestrator import Orchestrator
from app.agent.repository import SqlAgentRepository
from app.api import runs as runs_api
from app.db.models import AgentEvent, AgentRun, Bot, RecordRow, Revision
from app.main import create_app
from app.revisions.service import activate, create_draft
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory, signed_in_client
from tests.unit.agent.helpers import (
    DEADLINE_HOURS,
    GOLDEN_PROMPT,
    MOD_DEADLINE,
    blocking_question,
    change_out,
    deadline_requirement,
    deadline_scenarios,
    finish,
    golden_spec,
    happy_scripts,
    patch,
    set_spec,
    triage_out,
    understand_out,
)

ALICE = {"X-Test-User": "alice"}
BOB = {"X-Test-User": "bob"}


class Api:
    def __init__(self, client: httpx.AsyncClient, orch: Orchestrator, llm: FakeLLM) -> None:
        self.client = client
        self.orch = orch
        self.llm = llm

    async def start(self, bot_id: uuid.UUID, message: str = GOLDEN_PROMPT, headers: dict = ALICE) -> dict:
        response = await self.client.post(f"/bots/{bot_id}/runs", json={"message": message}, headers=headers)
        assert response.status_code == 201, response.text
        await self.orch.wait_idle()
        return response.json()

    async def run(self, run_id: str, headers: dict = ALICE) -> dict:
        response = await self.client.get(f"/runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    async def events(self, run_id: str, last_event_id: int | None = None) -> list[dict[str, Any]]:
        headers = dict(ALICE)
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        response = await self.client.get(f"/runs/{run_id}/events", headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = [f for f in response.text.split("\n\n") if f.strip()]
        out = []
        for frame in frames:
            lines = dict(line.split(": ", 1) for line in frame.splitlines() if not line.startswith(":"))
            envelope = json.loads(lines["data"])
            assert int(lines["id"]) == envelope["id"]
            out.append(envelope)
        return out


@pytest.fixture(autouse=True)
def _fresh_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs_api, "run_creation_limiter", runs_api.RateLimiter())
    get_agent_settings.cache_clear()
    yield
    get_agent_settings.cache_clear()


def make_api(session_factory: SessionFactory, client: httpx.AsyncClient, app: Any, **scripts: Any) -> Api:
    llm = FakeLLM(**happy_scripts(**scripts))
    orch = Orchestrator(SqlAgentRepository(session_factory), llm, bus=EventBus())
    app.dependency_overrides[runs_api.get_orchestrator] = lambda: orch
    return Api(client, orch, llm)


@pytest_asyncio.fixture
async def app_client(session_factory: SessionFactory) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    app = create_app()
    async with signed_in_client(app, session_factory) as c:
        yield app, c


async def test_create_run_to_activation_over_the_api(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    bot_id, _ = await make_bot("alice", active=False)
    created = await api.start(bot_id)
    assert created["status"] == "running" and created["kind"] == "create" and created["bot_id"] == str(bot_id)
    assert set(created) == {
        "id",
        "bot_id",
        "kind",
        "phase",
        "status",
        "base_revision_id",
        "result_revision_id",
        "created_at",
        "updated_at",
    }
    run = await api.run(created["id"])
    assert run["status"] == "waiting_approval" and run["phase"] == "await_approval"

    stored = [e.model_dump(mode="json") for e in await api.orch.repo.list_events(run["id"])]
    approval = next(e for e in stored if e["type"] == "approval_requested")
    assert approval["payload"]["can_approve"] is True
    revision_id = uuid.UUID(approval["payload"]["revision_id"])

    async with session_factory() as session:
        sandbox = await session.execute(
            select(func.count())
            .select_from(RecordRow)
            .where(RecordRow.bot_id == bot_id, RecordRow.env == "sandbox")
        )
        assert sandbox.scalar_one() == 2
        assert (await session.get(Revision, revision_id)).status == "draft"

    approved = await client.post(f"/runs/{run['id']}/approve", headers=ALICE)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "done" and approved.json()["result_revision_id"] == str(revision_id)
    bot = (await client.get(f"/bots/{bot_id}", headers=ALICE)).json()
    assert bot["active_revision_id"] == str(revision_id) and bot["active_revision_number"] == 1

    events = await api.events(run["id"])  # the run is done: replay, then the stream ends
    types = [e["type"] for e in events]
    assert (
        types[0] == "owner_message"
        and "test_report" in types
        and types[-2:] == ["phase_finished", "run_status"]
    )
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    assert events[: len(stored)] == stored
    assert set(events[0]) == {"id", "run_id", "ts", "type", "payload"}
    tail = await api.events(run["id"], last_event_id=stored[-1]["id"])
    assert [e["type"] for e in tail][:3] == ["run_status", "phase_started", "deployed"]
    assert all(e["id"] > stored[-1]["id"] for e in tail)

    listed = await client.get(f"/bots/{bot_id}/runs", headers=ALICE)
    assert [r["id"] for r in listed.json()] == [run["id"]]
    # A bot with an active revision now gets a MODIFY run (triage answers this question).
    api.llm.structured_scripts["triage"] = [triage_out("question", "ظرفیت هر کارگاه ۱۰ نفر است.")]
    again = await client.post(f"/bots/{bot_id}/runs", json={"message": "ظرفیت چند نفر است؟"}, headers=ALICE)
    assert again.status_code == 201 and again.json()["kind"] == "modify"
    assert again.json()["base_revision_id"] == str(revision_id)
    await api.orch.wait_idle()
    assert (await api.run(again.json()["id"]))["status"] == "done"


async def test_clarification_answer_one_active_run_and_reject(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(
        session_factory,
        client,
        app,
        structured={"understand": [understand_out(questions=[blocking_question()]), understand_out()]},
    )
    bot_id, _ = await make_bot("alice", active=False)
    created = await api.start(bot_id)
    assert (await api.run(created["id"]))["status"] == "waiting_user"
    second = await client.post(f"/bots/{bot_id}/runs", json={"message": "دوباره"}, headers=ALICE)
    assert second.status_code == 409 and second.json()["error"]["code"] == "run_in_progress"
    early = await client.post(f"/runs/{created['id']}/approve", headers=ALICE)
    assert early.status_code == 409 and early.json()["error"]["message"]

    answered = await client.post(f"/runs/{created['id']}/messages", json={"message": "بله"}, headers=ALICE)
    assert answered.status_code == 200 and answered.json()["status"] == "running"
    await api.orch.wait_idle()
    assert (await api.run(created["id"]))["status"] == "waiting_approval"

    rejected = await client.post(f"/runs/{created['id']}/reject", headers=ALICE)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    async with session_factory() as session:
        statuses = (await session.execute(select(Revision.status).where(Revision.bot_id == bot_id))).scalars()
        assert list(statuses) == ["rejected"]
    events = await api.events(created["id"])  # a terminal run's stream ends after the replay
    assert [e["type"] for e in events][-2:] == ["agent_message", "run_status"]
    assert events[-1]["payload"] == {"status": "rejected", "phase": "await_approval"}
    after_reject = await client.post(f"/bots/{bot_id}/runs", json={"message": "از نو"}, headers=ALICE)
    assert after_reject.status_code == 201


async def test_blocked_approval_and_failed_run_over_the_api(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    spec = golden_spec()
    spec["capabilities"][1]["waitlist"] = {"enabled": False, "auto_promote": True}
    api = make_api(
        session_factory,
        client,
        app,
        loops={"build": [[[set_spec(spec)], [finish()]]], "repair": [[[finish()]], [[finish()]]]},
    )
    bot_id, _ = await make_bot("alice", active=False)
    created = await api.start(bot_id)
    refused = await client.post(f"/runs/{created['id']}/approve", headers=ALICE)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "approval_blocked"
    assert (await api.run(created["id"]))["status"] == "waiting_approval"
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None and bot.active_revision_id is None

    other_bot, _ = await make_bot("alice", active=False)
    api.llm.structured_scripts["understand"] = [RuntimeError("boom")]
    failed = await api.start(other_bot)
    run = await api.run(failed["id"])
    assert run["status"] == "failed" and run["phase"] == "failed"
    assert [e["type"] for e in await api.events(failed["id"])][-2:] == ["error", "run_status"]


async def test_runs_are_owned(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    bot_id, _ = await make_bot("alice", active=False)
    created = await api.start(bot_id)
    for method, path in [
        ("GET", f"/runs/{created['id']}"),
        ("GET", f"/runs/{created['id']}/events"),
        ("POST", f"/runs/{created['id']}/approve"),
        ("POST", f"/runs/{created['id']}/reject"),
    ]:
        response = await client.request(method, path, headers=BOB)
        assert response.status_code == 404 and response.json()["error"]["code"] == "run_not_found"
    foreign = await client.post(f"/runs/{created['id']}/messages", json={"message": "x"}, headers=BOB)
    assert foreign.status_code == 404
    assert (await client.post(f"/bots/{bot_id}/runs", json={"message": "x"}, headers=BOB)).status_code == 404
    assert (await client.get(f"/bots/{bot_id}/runs", headers=BOB)).status_code == 404
    assert (await api.run(created["id"]))["status"] == "waiting_approval"  # untouched


async def test_daily_cap_and_rate_limit(
    app_client: tuple[Any, httpx.AsyncClient],
    make_bot: MakeBot,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    owner = f"capped-{uuid.uuid4()}"
    headers = {"X-Test-User": owner}
    monkeypatch.setenv("AGENT_DAILY_RUN_CAP", "1")
    get_agent_settings.cache_clear()
    first_bot, _ = await make_bot(owner, active=False)
    second_bot, _ = await make_bot(owner, active=False)
    await api.start(first_bot, headers=headers)
    capped = await client.post(f"/bots/{second_bot}/runs", json={"message": "x"}, headers=headers)
    assert capped.status_code == 429 and capped.json()["error"]["code"] == "daily_run_cap"

    monkeypatch.setenv("AGENT_DAILY_RUN_CAP", "100")
    monkeypatch.setenv("AGENT_RUNS_PER_MINUTE", "0")
    get_agent_settings.cache_clear()
    limited = await client.post(f"/bots/{second_bot}/runs", json={"message": "x"}, headers=headers)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
    empty = await client.post(f"/bots/{second_bot}/runs", json={"message": "   "}, headers=headers)
    assert empty.status_code == 422
    async with session_factory() as session:
        count = await session.execute(
            select(func.count()).select_from(AgentRun).where(AgentRun.bot_id == second_bot)
        )
        assert count.scalar_one() == 0
        events = await session.execute(select(func.count()).select_from(AgentEvent))
        assert events.scalar_one() > 0


# --------------------------------------------------------------------------- modify (WP7)


def modify_scripts(rid: str = "R1") -> dict[str, Any]:
    """Golden modification 2 on a bot whose active revision has no stored requirements (R1 is new)."""
    return {
        "structured": {
            "triage": [triage_out()],
            "understand": [change_out(added=[deadline_requirement("R5")])],
            "testgen": [{"scenarios": deadline_scenarios(rid)}],
        },
        "loops": {"build": [[[patch({"op": "set", "path": DEADLINE_HOURS, "value": 2})], [finish()]]]},
    }


async def _add_live_bookings(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        item = RecordRow(
            bot_id=bot_id,
            env="live",
            collection="workshop",
            data={"title": "x"},
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        await session.flush()
        for actor, status in (("a", "confirmed"), ("b", "confirmed"), ("c", "waitlisted")):
            session.add(
                RecordRow(
                    bot_id=bot_id,
                    env="live",
                    collection="book_workshop",
                    data={},
                    status=status,
                    actor_id=actor,
                    item_id=item.id,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(  # sandbox records never count
            RecordRow(
                bot_id=bot_id, env="sandbox", collection="workshop", data={}, created_at=now, updated_at=now
            )
        )
        await session.commit()


async def test_modify_run_over_the_api_activates_on_the_same_bot(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app, **modify_scripts())
    bot_id, base_id = await make_bot("alice", active=True)
    await _add_live_bookings(session_factory, bot_id)
    stats = await api.orch.repo.live_stats(str(bot_id))
    assert stats.record_counts == {"workshop": 1, "book_workshop": 3}
    assert stats.max_confirmed_per_item == {"book_workshop": 2}

    created = await api.start(bot_id, MOD_DEADLINE)
    assert created["kind"] == "modify" and created["base_revision_id"] == str(base_id)
    assert set(created) == {
        "id",
        "bot_id",
        "kind",
        "phase",
        "status",
        "base_revision_id",
        "result_revision_id",
        "created_at",
        "updated_at",
    }
    run = await api.run(created["id"])
    assert run["status"] == "waiting_approval" and run["phase"] == "await_approval"
    stored = [e.model_dump(mode="json") for e in await api.orch.repo.list_events(run["id"])]
    (diff,) = [e["payload"] for e in stored if e["type"] == "diff"]
    assert diff["changes"] == [
        {"label_fa": "مهلت لغو ثبت‌نام: بدون محدودیت ← تا ۲ ساعت قبل از شروع", "kind": "changed"}
    ]
    approval = next(e["payload"] for e in stored if e["type"] == "approval_requested")
    assert approval["can_approve"] is True
    draft_id = uuid.UUID(approval["revision_id"])
    async with session_factory() as session:
        draft = await session.get(Revision, draft_id)
        assert draft is not None and draft.status == "draft" and draft.parent_id == base_id
        assert draft.patch == [{"op": "set", "path": DEADLINE_HOURS, "value": 2, "before": None}]
        assert draft.superseded == [] and draft.change_request == f"Owner: {MOD_DEADLINE}"
        assert [r["id"] for r in draft.requirements["items"]] == ["R1"]
        bot = await session.get(Bot, bot_id)
        assert bot is not None and bot.active_revision_id == base_id  # live untouched until approval

    approved = await client.post(f"/runs/{run['id']}/approve", headers=ALICE)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "done" and approved.json()["result_revision_id"] == str(draft_id)
    bot_out = (await client.get(f"/bots/{bot_id}", headers=ALICE)).json()
    assert bot_out["active_revision_id"] == str(draft_id) and bot_out["active_revision_number"] == 2
    async with session_factory() as session:
        assert (await session.get(Revision, base_id)).status == "superseded"
        live = await session.execute(
            select(func.count())
            .select_from(RecordRow)
            .where(RecordRow.bot_id == bot_id, RecordRow.env == "live")
        )
        assert live.scalar_one() == 4  # the agent never touches live records


async def test_modify_stale_base_and_triage_over_the_api(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app, **modify_scripts())
    bot_id, base_id = await make_bot("alice", active=True)
    created = await api.start(bot_id, MOD_DEADLINE)
    assert (await api.run(created["id"]))["status"] == "waiting_approval"
    second = await client.post(f"/bots/{bot_id}/runs", json={"message": "دوباره"}, headers=ALICE)
    assert second.status_code == 409 and second.json()["error"]["code"] == "run_in_progress"

    # Another revision goes live meanwhile (e.g. a rollback elsewhere): the draft is stale.
    async with session_factory() as session:
        other = await create_draft(session, bot_id, spec=golden_spec(), parent_id=base_id)
        await activate(session, other.id)
        await session.commit()
    refused = await client.post(f"/runs/{created['id']}/approve", headers=ALICE)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "stale_base"
    assert (await api.run(created["id"]))["status"] == "failed"
    async with session_factory() as session:
        assert (await session.get(Bot, bot_id)).active_revision_id == other.id

    api.llm.structured_scripts["triage"] = [triage_out("data_request", "")]
    data = await api.start(bot_id, "یک کارگاه جمعه اضافه کن")
    assert (await api.run(data["id"]))["status"] == "done"
    events = await api.events(data["id"])
    assert "«داده‌ها»" in [e for e in events if e["type"] == "agent_message"][-1]["payload"]["text"]
    async with session_factory() as session:
        count = await session.execute(
            select(func.count()).select_from(Revision).where(Revision.bot_id == bot_id)
        )
        assert count.scalar_one() == 3  # base, the stale draft, the other revision: triage adds none


async def test_run_status_events_and_startup_interruption_over_the_api(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    bot_id, _ = await make_bot("alice", active=False)
    token = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ"
    created = await api.start(bot_id, f"{GOLDEN_PROMPT} {token}")
    # The run waits for approval; read the stored events directly (the stream of a paused run
    # replays them and ends, test_live_stream_ends_when_the_run_reaches_a_terminal_state).
    events = [e.model_dump(mode="json") for e in await api.orch.repo.list_events(created["id"])]
    statuses = [e["payload"] for e in events if e["type"] == "run_status"]
    assert statuses == [
        {"status": "running", "phase": "understand"},
        {"status": "waiting_approval", "phase": "await_approval"},
    ]
    async with session_factory() as session:
        stored = (
            await session.execute(
                select(AgentEvent.payload).where(AgentEvent.run_id == uuid.UUID(created["id"]))
            )
        ).scalars()
        assert token not in json.dumps(list(stored), ensure_ascii=False)
        run_row = await session.get(AgentRun, uuid.UUID(created["id"]))
        assert token not in json.dumps(run_row.state, ensure_ascii=False)
        # A restart marks the run interrupted outside the orchestrator (app.main.mark_interrupted_runs).
        run_row.status = "interrupted"
        await session.commit()
    events = await api.events(created["id"])  # the stream adds the missing run_status, then ends
    assert events[-1]["type"] == "run_status" and events[-1]["payload"]["status"] == "interrupted"
    again = await api.events(created["id"])
    assert [e["type"] for e in again].count("run_status") == 3  # not duplicated


async def test_live_stream_ends_when_the_run_reaches_a_terminal_state(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    bot_id, _ = await make_bot("alice", active=False)
    created = await api.start(bot_id)
    assert (await api.run(created["id"]))["status"] == "waiting_approval"
    # A run paused for the owner is not running: its stream replays and ends by itself instead of
    # holding the connection until the owner answers (the client reopens it after approving).
    paused = await asyncio.wait_for(api.events(created["id"]), timeout=10)
    assert paused[-1]["type"] == "run_status" and paused[-1]["payload"]["status"] == "waiting_approval"
    approved = await client.post(f"/runs/{created['id']}/approve", headers=ALICE)
    assert approved.status_code == 200 and approved.json()["status"] == "done"
    events = await asyncio.wait_for(api.events(created["id"]), timeout=10)
    assert events[: len(paused)] == paused
    assert "deployed" in [e["type"] for e in events]
    assert events[-1]["type"] == "run_status" and events[-1]["payload"]["status"] == "done"
    assert events == [e.model_dump(mode="json") for e in await api.orch.repo.list_events(created["id"])]
