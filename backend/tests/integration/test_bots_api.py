"""Bots endpoints, with stand-in auth for two users. Needs TEST_DATABASE_URL."""

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db.models import AgentRun, Bot
from app.main import create_app, mark_interrupted_runs
from app.runtime.pg_store import PgStore
from tests.integration.conftest import MakeBot
from tests.integration.helpers import NOW, SessionFactory

ALICE = {"X-Test-User": "alice"}
BOB = {"X-Test-User": "bob"}

SECRET_FIELDS = {"tg_token_enc", "tg_webhook_secret", "tg_bot_id", "owner_id", "owner_actor_id"}


async def test_me(client: httpx.AsyncClient) -> None:
    response = await client.get("/me", headers=BOB)
    assert response.status_code == 200
    assert response.json() == {"id": "bob", "email": "bob@example.com"}


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
    async with session_factory() as session:
        bot = Bot(
            owner_id="carol",
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


async def test_startup_marks_running_agent_runs_interrupted(
    session_factory: SessionFactory, migrated_db: str, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.db import session as db_session

    async with session_factory() as session:
        bot = Bot(owner_id="dave", name="b")
        session.add(bot)
        await session.flush()
        statuses = ["running", "waiting_user", "done", "running"]
        runs = [AgentRun(bot_id=bot.id, kind="create", phase="build", status=s) for s in statuses]
        session.add_all(runs)
        await session.commit()
        run_ids = [r.id for r in runs]

    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            pass
    finally:
        await db_session.dispose_engine()
        get_settings.cache_clear()

    async with session_factory() as session:
        rows = (
            (await session.execute(select(AgentRun.status).where(AgentRun.id.in_(run_ids)))).scalars().all()
        )
    assert sorted(rows) == ["done", "interrupted", "interrupted", "waiting_user"]
    assert mark_interrupted_runs  # exported for the later runs package
