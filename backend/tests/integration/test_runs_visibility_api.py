"""Run visibility over the API: retry endpoint, terminal run_status on streams, startup sweep events."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent.context import get_agent_settings
from app.agent.llm import LLMError
from app.api import runs as runs_api
from app.db.models import AgentEvent, AgentRun
from app.main import create_app
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory, signed_in_client
from tests.integration.test_runs_api import ALICE, BOB, make_api
from tests.unit.agent.helpers import GOLDEN_PROMPT, triage_out, understand_out


@pytest.fixture(autouse=True)
def _fresh_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(runs_api, "run_creation_limiter", runs_api.RateLimiter())
    get_agent_settings.cache_clear()
    yield
    get_agent_settings.cache_clear()


@pytest_asyncio.fixture
async def app_client(session_factory: SessionFactory) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    app = create_app()
    async with signed_in_client(app, session_factory) as c:
        yield app, c


async def test_retry_creates_a_new_run_from_the_first_owner_message(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    bot_id, _ = await make_bot("alice", active=False)
    api.llm.structured_scripts["understand"] = [LLMError("api_error", "down"), understand_out()]
    failed = await api.start(bot_id)
    assert (await api.run(failed["id"]))["status"] == "failed"
    errors = [e["payload"] for e in await api.events(failed["id"]) if e["type"] == "error"]
    assert errors[0]["code"] == "LLM_UNAVAILABLE" and errors[0]["retryable"] and not errors[0]["applied"]

    response = await client.post(f"/runs/{failed['id']}/retry", headers=ALICE)
    assert response.status_code == 201, response.text
    new = response.json()
    assert set(new) == set(failed) and new["id"] != failed["id"]
    assert new["bot_id"] == failed["bot_id"] and new["kind"] == "create" and new["status"] == "running"
    await api.orch.wait_idle()
    assert (await api.run(new["id"]))["status"] == "waiting_approval"
    owner = [e for e in await api.orch.repo.list_events(new["id"]) if e.type == "owner_message"]
    assert owner[0].payload == {"text": GOLDEN_PROMPT}

    # The old run cannot be retried again while the new one is active.
    again = await client.post(f"/runs/{failed['id']}/retry", headers=ALICE)
    assert again.status_code == 409 and again.json()["error"]["code"] == "run_in_progress"


async def test_retry_refuses_running_and_done_runs_and_other_owners(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    bot_id, _ = await make_bot("alice", active=False)
    created = await api.start(bot_id)  # waiting_approval
    refused = await client.post(f"/runs/{created['id']}/retry", headers=ALICE)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "run_not_retryable"
    for status in ("running", "done"):
        async with session_factory() as session:
            row = await session.get(AgentRun, uuid.UUID(created["id"]))
            assert row is not None
            row.status = status
            await session.commit()
        response = await client.post(f"/runs/{created['id']}/retry", headers=ALICE)
        assert response.status_code == 409 and response.json()["error"]["code"] == "run_not_retryable"
    foreign = await client.post(f"/runs/{created['id']}/retry", headers=BOB)
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "run_not_found"
    async with session_factory() as session:
        count = await session.execute(
            select(func.count()).select_from(AgentRun).where(AgentRun.bot_id == bot_id)
        )
        assert count.scalar_one() == 1  # nothing was created


async def test_retry_of_an_interrupted_modify_run_stays_a_modify_run(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app, structured={"triage": [triage_out("question")] * 2})
    bot_id, _ = await make_bot("alice", active=True)
    first = await api.start(bot_id, "ساعت کاری شما چیست؟")
    async with session_factory() as session:
        row = await session.get(AgentRun, uuid.UUID(first["id"]))
        assert row is not None
        row.status = "interrupted"
        await session.commit()
    response = await client.post(f"/runs/{first['id']}/retry", headers=ALICE)
    assert response.status_code == 201 and response.json()["kind"] == "modify"
    await api.orch.wait_idle()
    owner = [e for e in await api.orch.repo.list_events(response.json()["id"]) if e.type == "owner_message"]
    assert owner[0].payload == {"text": "ساعت کاری شما چیست؟"}


async def test_retry_obeys_the_daily_cap_and_rate_limit(
    app_client: tuple[Any, httpx.AsyncClient],
    make_bot: MakeBot,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, client = app_client
    api = make_api(session_factory, client, app)
    owner = f"retry-{uuid.uuid4()}"
    headers = {"X-Test-User": owner}
    bot_id, _ = await make_bot(owner, active=False)
    api.llm.structured_scripts["understand"] = [LLMError("api_error", "down")]
    failed = await api.start(bot_id, headers=headers)
    monkeypatch.setenv("AGENT_DAILY_RUN_CAP", "1")
    get_agent_settings.cache_clear()
    capped = await client.post(f"/runs/{failed['id']}/retry", headers=headers)
    assert capped.status_code == 429 and capped.json()["error"]["code"] == "daily_run_cap"
    monkeypatch.setenv("AGENT_DAILY_RUN_CAP", "100")
    monkeypatch.setenv("AGENT_RUNS_PER_MINUTE", "0")
    get_agent_settings.cache_clear()
    limited = await client.post(f"/runs/{failed['id']}/retry", headers=headers)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"


async def test_stream_of_a_run_that_ends_always_carries_the_terminal_run_status(
    app_client: tuple[Any, httpx.AsyncClient], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    """Regression: the terminal status used to be committed before its run_status event, so a stream
    opened while the run was live could close without it."""
    app, client = app_client
    api = make_api(session_factory, client, app)
    for round_no in range(3):
        bot_id, _ = await make_bot("alice", active=False)
        api.llm.structured_scripts["understand"] = [LLMError("api_error", "down")]
        created = await client.post(f"/bots/{bot_id}/runs", json={"message": GOLDEN_PROMPT}, headers=ALICE)
        assert created.status_code == 201, round_no
        run_id = created.json()["id"]
        watching = asyncio.create_task(api.events(run_id))
        await api.orch.wait_idle()
        events = await asyncio.wait_for(watching, timeout=10)
        assert events[-1]["type"] == "run_status" and events[-1]["payload"]["status"] == "failed"
        assert events == [e.model_dump(mode="json") for e in await api.orch.repo.list_events(run_id)]

    rejected_bot, _ = await make_bot("alice", active=False)
    api.llm.structured_scripts["understand"] = [understand_out()]
    created_run = await api.start(rejected_bot)
    watching = asyncio.create_task(api.events(created_run["id"]))
    await asyncio.sleep(0.1)
    assert (await client.post(f"/runs/{created_run['id']}/reject", headers=ALICE)).status_code == 200
    events = await asyncio.wait_for(watching, timeout=10)
    assert [e["type"] for e in events][-2:] == ["agent_message", "run_status"]
    assert events[-1]["payload"]["status"] == "rejected"


async def test_startup_sweep_emits_run_interrupted_then_run_status(
    make_bot: MakeBot, session_factory: SessionFactory, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main
    from app.config import get_settings
    from app.db import session as db_session

    bot_id, _ = await make_bot("alice", active=False)
    async with session_factory() as session:
        running = AgentRun(bot_id=bot_id, kind="create", phase="build", status="running")
        waiting = AgentRun(bot_id=bot_id, kind="create", phase="clarify", status="waiting_user")
        session.add_all([running, waiting])
        await session.commit()
        running_id, waiting_id = running.id, waiting.id

    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    try:
        assert await main.mark_interrupted_runs() >= 1  # other tests may leave running rows
    finally:
        await db_session.dispose_engine()
        get_settings.cache_clear()

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(AgentEvent.run_id, AgentEvent.type, AgentEvent.payload)
                .where(AgentEvent.run_id.in_([running_id, waiting_id]))
                .order_by(AgentEvent.id)
            )
        ).all()
        status = (await session.get(AgentRun, running_id)).status  # type: ignore[union-attr]
    assert status == "interrupted"
    assert [(r.type, r.payload) for r in rows] == [
        ("run_interrupted", {"reason": "server_restart"}),
        ("run_status", {"status": "interrupted", "phase": "build"}),
    ]
    assert all(r.run_id == running_id for r in rows)
