"""Bots endpoints, signed in with real session cookies as two users. Needs TEST_DATABASE_URL."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

import app.main as app_main
from app.agent.repository import SqlAgentRepository
from app.config import get_settings
from app.db.models import AgentEvent, AgentRun, Bot
from app.main import STALE_RUN_AFTER, create_app, mark_interrupted_runs
from app.runtime.pg_store import PgStore
from tests.integration.conftest import MakeBot
from tests.integration.helpers import NOW, SessionFactory, user_id

ALICE = {"X-Test-User": "alice"}
BOB = {"X-Test-User": "bob"}

SECRET_FIELDS = {"tg_token_enc", "tg_webhook_secret", "tg_bot_id", "owner_id", "owner_actor_id"}


async def test_me(client: httpx.AsyncClient, session_factory: SessionFactory) -> None:
    response = await client.get("/me", headers=BOB)
    assert response.status_code == 200
    assert response.json() == {"id": str(await user_id(session_factory, "bob")), "email": "bob@example.com"}


async def test_create_bot(client: httpx.AsyncClient) -> None:
    response = await client.post("/bots", json={"name": "  آموزشگاه من  "}, headers=ALICE)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "آموزشگاه من"
    assert body["status"] == "draft"
    assert body["active_revision_id"] is None and body["active_revision_number"] is None
    assert body["tg_username"] is None
    assert body["owner_link_code"] and len(body["owner_link_code"]) >= 8
    assert not SECRET_FIELDS & set(body)

    other = (await client.post("/bots", json={"name": "دیگر"}, headers=ALICE)).json()
    assert other["owner_link_code"] != body["owner_link_code"]


async def test_create_bot_validation(client: httpx.AsyncClient) -> None:
    for payload in ({}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}):
        response = await client.post("/bots", json=payload, headers=ALICE)
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "validation_error"


async def test_list_and_ownership_isolation(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    alice_bot, alice_rev = await make_bot("alice-iso", name="الف")
    bob_bot, _ = await make_bot("bob-iso", name="ب", active=False)
    a = {"X-Test-User": "alice-iso"}
    b = {"X-Test-User": "bob-iso"}

    alice_list = (await client.get("/bots", headers=a)).json()
    bob_list = (await client.get("/bots", headers=b)).json()
    assert [x["id"] for x in alice_list] == [str(alice_bot)]
    assert [x["id"] for x in bob_list] == [str(bob_bot)]
    assert alice_list[0]["active_revision_id"] == str(alice_rev)
    assert alice_list[0]["active_revision_number"] == 1
    assert not any(SECRET_FIELDS & set(item) for item in alice_list)

    assert (await client.get(f"/bots/{alice_bot}", headers=a)).status_code == 200
    for method, kwargs in (
        ("GET", {}),
        ("PATCH", {"json": {"name": "هک"}}),
        ("DELETE", {}),
    ):
        response = await client.request(method, f"/bots/{alice_bot}", headers=b, **kwargs)
        assert response.status_code == 404, method
        assert response.json()["error"]["code"] == "bot_not_found"
    assert (await client.get(f"/bots/{alice_bot}/data", headers=b)).status_code == 404
    # still intact for the owner
    assert (await client.get(f"/bots/{alice_bot}", headers=a)).json()["name"] == "الف"


async def test_read_rename_delete(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, rev_id = await make_bot("alice")
    async with session_factory() as session:  # a record and a session that must go with the bot
        store = PgStore(session, bot_id, "live")
        await store.create_record("workshop", {"title": "x"}, now=NOW)
        await store.set_session("ali", {"s": 1})
        await session.commit()

    read = await client.get(f"/bots/{bot_id}", headers=ALICE)
    assert read.status_code == 200
    assert read.json()["active_revision_id"] == str(rev_id)
    assert read.json()["active_revision_number"] == 1

    renamed = await client.patch(f"/bots/{bot_id}", json={"name": "نام تازه"}, headers=ALICE)
    assert renamed.status_code == 200 and renamed.json()["name"] == "نام تازه"
    assert (await client.get(f"/bots/{bot_id}", headers=ALICE)).json()["name"] == "نام تازه"
    assert (await client.patch(f"/bots/{bot_id}", json={"name": ""}, headers=ALICE)).status_code == 422

    deleted = await client.delete(f"/bots/{bot_id}", headers=ALICE)
    assert deleted.status_code == 204
    assert (await client.get(f"/bots/{bot_id}", headers=ALICE)).status_code == 404
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        assert await store.count_records("workshop") == 0
        assert await store.get_session("ali") is None


async def test_responses_never_contain_secret_values(
    client: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    carol = await user_id(session_factory, "carol")
    async with session_factory() as session:
        bot = Bot(
            owner_id=carol,
            name="با توکن",
            tg_token_enc="ENCRYPTED-TOKEN-VALUE",
            tg_webhook_secret="WEBHOOK-SECRET-VALUE",
            tg_username="my_bot",
            owner_actor_id="999",
        )
        session.add(bot)
        await session.commit()
        bot_id = bot.id
    headers = {"X-Test-User": "carol"}
    for response in (
        await client.get("/bots", headers=headers),
        await client.get(f"/bots/{bot_id}", headers=headers),
        await client.patch(f"/bots/{bot_id}", json={"name": "جدید"}, headers=headers),
    ):
        assert "ENCRYPTED-TOKEN-VALUE" not in response.text
        assert "WEBHOOK-SECRET-VALUE" not in response.text
    assert (await client.get(f"/bots/{bot_id}", headers=headers)).json()["tg_username"] == "my_bot"


async def _add_runs(session_factory: SessionFactory, runs: list[tuple[str, timedelta]]) -> list[uuid.UUID]:
    """Runs of one bot as (status, age of the last heartbeat)."""
    dave = await user_id(session_factory, "dave")
    now = datetime.now(UTC)
    async with session_factory() as session:
        bot = Bot(owner_id=dave, name="b")
        session.add(bot)
        await session.flush()
        rows = [
            AgentRun(bot_id=bot.id, kind="create", phase="build", status=s, updated_at=now - age)
            for s, age in runs
        ]
        session.add_all(rows)
        await session.commit()
        return [r.id for r in rows]


async def _statuses(session_factory: SessionFactory, run_ids: list[uuid.UUID]) -> list[str]:
    async with session_factory() as session:
        status = {
            r.id: r.status
            for r in (await session.execute(select(AgentRun).where(AgentRun.id.in_(run_ids)))).scalars()
        }
    return [status[i] for i in run_ids]


@asynccontextmanager
async def _app_running(migrated_db: str, monkeypatch) -> AsyncIterator[None]:  # type: ignore[no-untyped-def]
    from app.db import session as db_session

    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            yield
    finally:
        await db_session.dispose_engine()
        get_settings.cache_clear()


STALE = STALE_RUN_AFTER + timedelta(minutes=5)


async def test_startup_interrupts_running_runs_without_a_heartbeat(
    session_factory: SessionFactory, migrated_db: str, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    run_ids = await _add_runs(
        session_factory, [("running", STALE), ("waiting_user", STALE), ("done", STALE), ("running", STALE)]
    )
    async with _app_running(migrated_db, monkeypatch):
        pass
    assert await _statuses(session_factory, run_ids) == ["interrupted", "waiting_user", "done", "interrupted"]
    async with session_factory() as session:
        events = (
            (
                await session.execute(
                    select(AgentEvent).where(AgentEvent.run_id == run_ids[0]).order_by(AgentEvent.id)
                )
            )
            .scalars()
            .all()
        )
    assert [(e.type, e.payload) for e in events] == [
        ("run_interrupted", {"reason": "server_restart"}),
        ("run_status", {"status": "interrupted", "phase": "build"}),
    ]


async def test_startup_leaves_a_running_run_with_a_fresh_heartbeat_alone(
    session_factory: SessionFactory, migrated_db: str, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Zero-downtime deploy: the new container starts while the old one still executes the run."""
    run_ids = await _add_runs(session_factory, [("running", timedelta(seconds=5)), ("running", STALE)])
    async with _app_running(migrated_db, monkeypatch):
        pass
    assert await _statuses(session_factory, run_ids) == ["running", "interrupted"]


async def test_a_run_that_goes_stale_after_startup_is_swept(
    session_factory: SessionFactory, migrated_db: str, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """The old container stops after the new one started: its abandoned run is found while the new
    process keeps running, not only at its next start."""
    monkeypatch.setattr(app_main, "SWEEP_SECONDS", 0.05)
    async with _app_running(migrated_db, monkeypatch):
        (run_id,) = await _add_runs(session_factory, [("running", STALE)])
        for _ in range(100):
            if await _statuses(session_factory, [run_id]) == ["interrupted"]:
                break
            await asyncio.sleep(0.05)
        assert await _statuses(session_factory, [run_id]) == ["interrupted"]


async def test_a_heartbeat_keeps_a_running_run_from_being_swept(session_factory: SessionFactory) -> None:
    repo = SqlAgentRepository(session_factory)
    beating, silent, paused = await _add_runs(
        session_factory, [("running", STALE), ("running", STALE), ("waiting_user", STALE)]
    )
    await repo.touch_run(str(beating))
    await repo.touch_run(str(paused))  # only running runs beat; a paused run stays as it was
    async with session_factory() as session:
        paused_row = await session.get(AgentRun, paused)
        assert paused_row is not None and paused_row.updated_at < datetime.now(UTC) - STALE_RUN_AFTER

    envelopes = await repo.interrupt_stale_runs(STALE_RUN_AFTER)
    assert [(e.run_id, e.type) for e in envelopes] == [
        (str(silent), "run_interrupted"),
        (str(silent), "run_status"),
    ]
    assert await _statuses(session_factory, [beating, silent, paused]) == [
        "running",
        "interrupted",
        "waiting_user",
    ]
    assert mark_interrupted_runs  # the startup and periodic sweep entry point
