"""Ownership with the REAL dependencies: nothing in ``dependency_overrides``. Needs TEST_DATABASE_URL.

Tokens are HS256-signed with a locally generated secret configured through the environment, exactly
as a deployment with ``SUPABASE_JWT_SECRET`` would verify them; sessions come from the real
``get_session`` against the test database.
"""

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import BOT_NOT_FOUND, REVISION_NOT_FOUND, RUN_NOT_FOUND, get_owned_revision, get_owned_run
from app.config import get_settings
from app.db import session as db_session
from app.db.models import AgentRun, Bot, Revision
from app.main import create_app
from app.security.auth import reset_verifier
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory, make_client
from tests.unit.security.tokens import SUPABASE_URL, mint, new_secret

SECRET = new_secret()

WORKSHOP = {
    "title": "کارگاه عکاسی",
    "description": "مقدماتی",
    "teacher": "سارا",
    "starts_at": "2026-11-01T10:00:00+03:30",
    "price": "۱۲۰۰۰",
}

# Run and revision routes arrive with later packages; probe routes exercise the dependencies now.
probe = APIRouter()


@probe.get("/probe/runs/{run_id}")
async def probe_run(run: AgentRun = Depends(get_owned_run)) -> dict[str, str]:
    return {"id": str(run.id), "bot_id": str(run.bot_id)}


@probe.get("/probe/revisions/{revision_id}")
async def probe_revision(revision: Revision = Depends(get_owned_revision)) -> dict[str, str]:
    return {"id": str(revision.id), "bot_id": str(revision.bot_id)}


def auth(user_id: str, **claims: Any) -> dict[str, str]:
    token = mint(SECRET, "HS256", sub=user_id, email=f"{user_id[:8]}@example.com", **claims)
    return {"Authorization": f"Bearer {token}"}


def new_user() -> str:
    return str(uuid.uuid4())  # Supabase user ids are UUIDs


def error(pair: tuple[str, str]) -> dict[str, dict[str, str]]:
    return {"error": {"code": pair[0], "message": pair[1]}}


@pytest_asyncio.fixture
async def real_client(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """The production app: real JWT verification, real ownership checks, real sessions."""
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_JWKS_URL", "")
    get_settings.cache_clear()
    reset_verifier()
    app = create_app()
    app.include_router(probe)
    assert not app.dependency_overrides
    try:
        async with make_client(app) as client:
            yield client
    finally:
        await db_session.dispose_engine()
        get_settings.cache_clear()
        reset_verifier()


async def test_owner_has_full_access_to_their_bot(real_client: httpx.AsyncClient) -> None:
    alice = new_user()
    me = await real_client.get("/me", headers=auth(alice))
    assert me.json() == {"id": alice, "email": f"{alice[:8]}@example.com"}

    created = await real_client.post("/bots", json={"name": "ربات من"}, headers=auth(alice))
    assert created.status_code == 201, created.text
    bot_id = created.json()["id"]
    assert [b["id"] for b in (await real_client.get("/bots", headers=auth(alice))).json()] == [bot_id]
    assert (await real_client.get(f"/bots/{bot_id}", headers=auth(alice))).status_code == 200
    renamed = await real_client.patch(f"/bots/{bot_id}", json={"name": "نام تازه"}, headers=auth(alice))
    assert renamed.status_code == 200 and renamed.json()["name"] == "نام تازه"
    assert (await real_client.delete(f"/bots/{bot_id}", headers=auth(alice))).status_code == 204
    gone = await real_client.get(f"/bots/{bot_id}", headers=auth(alice))
    assert gone.status_code == 404 and gone.json() == error(BOT_NOT_FOUND)


async def test_other_owners_get_404_on_every_bot_route(
    real_client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    alice, bob = new_user(), new_user()
    bot_id, _ = await make_bot(alice, name="ربات آلیس")
    created = await real_client.post(
        f"/bots/{bot_id}/data/workshop", json={"data": WORKSHOP}, headers=auth(alice)
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    await make_bot(bob, name="ربات باب")  # Bob owns a bot too: having one grants nothing on others

    missing = uuid.uuid4()
    routes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/bots/{bot}", None),
        ("PATCH", "/bots/{bot}", {"name": "هک"}),
        ("DELETE", "/bots/{bot}", None),
        ("GET", "/bots/{bot}/data", None),
        ("GET", "/bots/{bot}/data/workshop", None),
        ("GET", "/bots/{bot}/data/book_workshop", None),
        ("POST", "/bots/{bot}/data/workshop", {"data": WORKSHOP}),
        ("PATCH", "/bots/{bot}/data/workshop/{record}", {"data": {"title": "هک"}}),
        ("DELETE", "/bots/{bot}/data/workshop/{record}", None),
    ]
    for method, template, body in routes:
        foreign = await real_client.request(
            method, template.format(bot=bot_id, record=record_id), json=body, headers=auth(bob)
        )
        absent = await real_client.request(
            method, template.format(bot=missing, record=record_id), json=body, headers=auth(bob)
        )
        assert foreign.status_code == 404, (method, template, foreign.text)
        # Same body as a bot that does not exist: existence is not revealed.
        assert foreign.json() == absent.json() == error(BOT_NOT_FOUND)

    bob_bots = (await real_client.get("/bots", headers=auth(bob))).json()
    assert [b["name"] for b in bob_bots] == ["ربات باب"]

    mine = await real_client.get(f"/bots/{bot_id}", headers=auth(alice))
    assert mine.status_code == 200 and mine.json()["name"] == "ربات آلیس"
    records = (await real_client.get(f"/bots/{bot_id}/data/workshop", headers=auth(alice))).json()
    assert records["total"] == 1
    assert records["items"][0]["data"]["title"] == WORKSHOP["title"]


async def test_requests_without_a_valid_token_are_401_and_change_nothing(
    real_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    alice = new_user()
    bot_id, _ = await make_bot(alice, name="الف")
    probe_name = f"probe-{uuid.uuid4()}"
    now = int(time.time())
    attempts = {
        "missing": {},
        "garbage": {"Authorization": "Bearer garbage"},
        "expired": auth(alice, exp=now - 3600),
        "foreign secret": {"Authorization": f"Bearer {mint(new_secret(), 'HS256', sub=alice)}"},
        "foreign issuer": auth(alice, iss="https://other-project.supabase.co/auth/v1"),
        "foreign audience": auth(alice, aud="anon"),
    }
    routes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/me", None),
        ("GET", "/bots", None),
        ("POST", "/bots", {"name": probe_name}),
        ("GET", f"/bots/{bot_id}", None),
        ("PATCH", f"/bots/{bot_id}", {"name": "هک"}),
        ("DELETE", f"/bots/{bot_id}", None),
        ("GET", f"/bots/{bot_id}/data", None),
        ("POST", f"/bots/{bot_id}/data/workshop", {"data": WORKSHOP}),
    ]
    for label, headers in attempts.items():
        expected = "auth_required" if label == "missing" else "invalid_token"
        for method, path, body in routes:
            response = await real_client.request(method, path, json=body, headers=headers)
            assert response.status_code == 401, (label, method, path, response.text)
            assert response.json()["error"]["code"] == expected

    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None and bot.name == "الف"
        probes = await session.execute(select(func.count()).select_from(Bot).where(Bot.name == probe_name))
        assert probes.scalar_one() == 0
    records = (await real_client.get(f"/bots/{bot_id}/data/workshop", headers=auth(alice))).json()
    assert records["total"] == 0


async def test_a_foreign_active_revision_is_never_served(
    real_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    alice, mallory = new_user(), new_user()
    alice_bot, _ = await make_bot(alice, active=False)
    _, mallory_revision = await make_bot(mallory)
    async with session_factory() as session:  # break the invariant directly in the database
        bot = await session.get(Bot, alice_bot)
        assert bot is not None
        bot.active_revision_id = mallory_revision
        await session.commit()

    data = await real_client.get(f"/bots/{alice_bot}/data", headers=auth(alice))
    assert data.status_code == 409 and data.json()["error"]["code"] == "no_active_revision"
    assert (await real_client.get(f"/bots/{alice_bot}", headers=auth(alice))).json()[
        "active_revision_number"
    ] is None
    listed = (await real_client.get("/bots", headers=auth(alice))).json()
    assert [b["active_revision_number"] for b in listed] == [None]


async def test_owned_run_and_revision_dependencies(
    real_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    alice, bob = new_user(), new_user()
    bot_id, revision_id = await make_bot(alice)
    assert revision_id is not None
    async with session_factory() as session:
        run = AgentRun(bot_id=bot_id, kind="create", phase="understand")
        session.add(run)
        await session.commit()
        run_id = run.id

    cases = [
        (f"/probe/runs/{run_id}", run_id, RUN_NOT_FOUND),
        (f"/probe/revisions/{revision_id}", revision_id, REVISION_NOT_FOUND),
    ]
    for path, own_id, not_found in cases:
        mine = await real_client.get(path, headers=auth(alice))
        assert mine.status_code == 200, mine.text
        assert mine.json() == {"id": str(own_id), "bot_id": str(bot_id)}
        foreign = await real_client.get(path, headers=auth(bob))
        absent = await real_client.get(path.replace(str(own_id), str(uuid.uuid4())), headers=auth(bob))
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json() == error(not_found)
        anonymous = await real_client.get(path)
        assert anonymous.status_code == 401
