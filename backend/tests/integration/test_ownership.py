"""Ownership with the REAL dependencies: nothing in ``dependency_overrides``. Needs a database.

Requests carry real login sessions: ``auth_sessions`` rows made by the app's own ``create_session``,
sent as the ``bf_session`` cookie with the CSRF header (``helpers.CookieAuth``; ``X-Test-User`` names
the account). The app uses its own ``get_session`` against the test database.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select

from app.api.deps import BOT_NOT_FOUND, REVISION_NOT_FOUND, RUN_NOT_FOUND, get_owned_revision, get_owned_run
from app.config import get_settings
from app.db import session as db_session
from app.db.models import AgentRun, AuthSession, Bot, Revision, User
from app.main import create_app
from app.security.sessions import SESSION_COOKIE, create_session, new_token
from tests.integration.conftest import MakeBot
from tests.integration.helpers import ANONYMOUS, CookieAuth, SessionFactory, email_for, make_client, user_id

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


def auth(name: str) -> dict[str, str]:
    return {"X-Test-User": name}


def new_user() -> str:
    return f"owner-{uuid.uuid4().hex[:12]}"  # a fresh account name


def error(pair: tuple[str, str]) -> dict[str, dict[str, str]]:
    return {"error": {"code": pair[0], "message": pair[1]}}


def with_cookie(token: str) -> dict[str, str]:
    """A request that bypasses CookieAuth and presents ``token`` itself (with the CSRF header)."""
    return {"X-Test-User": ANONYMOUS, "Cookie": f"{SESSION_COOKIE}={token}", "X-BotForge-CSRF": "1"}


@pytest_asyncio.fixture
async def real_client(
    migrated_db: str, session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """The production app: real cookie sessions, real ownership checks, real database sessions."""
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    app = create_app()
    app.include_router(probe)
    assert not app.dependency_overrides
    try:
        async with make_client(app, auth=CookieAuth(session_factory)) as client:
            yield client
    finally:
        await db_session.dispose_engine()
        get_settings.cache_clear()


async def test_owner_has_full_access_to_their_bot(
    real_client: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    alice = new_user()
    me = await real_client.get("/me", headers=auth(alice))
    assert me.json() == {"id": str(await user_id(session_factory, alice)), "email": email_for(alice)}

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


async def test_requests_without_a_valid_session_are_401_and_change_nothing(
    real_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    alice = new_user()
    bot_id, _ = await make_bot(alice, name="الف")
    alice_id = await user_id(session_factory, alice)
    async with session_factory() as session:
        expired = await create_session(session, alice_id, now=datetime.now(UTC) - timedelta(days=30))
        logged_out = await create_session(session, alice_id)
        await session.commit()
    assert (await real_client.post("/auth/logout", headers=with_cookie(logged_out))).status_code == 204

    probe_name = f"probe-{uuid.uuid4()}"
    attempts = {
        "missing": {"X-Test-User": ANONYMOUS, "X-BotForge-CSRF": "1"},
        "garbage": with_cookie("garbage"),
        "unknown": with_cookie(new_token()),
        "expired": with_cookie(expired),
        "logged out": with_cookie(logged_out),
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
        expected = "auth_required" if label == "missing" else "invalid_session"
        for method, path, body in routes:
            response = await real_client.request(method, path, json=body, headers=headers)
            assert response.status_code == 401, (label, method, path, response.text)
            assert response.json()["error"]["code"] == expected
            assert "set-cookie" not in response.headers

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
        anonymous = await real_client.get(path, headers=auth(ANONYMOUS))
        assert anonymous.status_code == 401


async def test_deleting_an_account_deletes_its_bots_and_sessions(
    real_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    alice = new_user()
    bot_id, _ = await make_bot(alice)
    assert (await real_client.get("/me", headers=auth(alice))).status_code == 200  # makes a session
    alice_id = await user_id(session_factory, alice)
    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == alice_id))
        await session.commit()
    async with session_factory() as session:
        assert await session.get(Bot, bot_id) is None
        left = select(func.count()).select_from(AuthSession).where(AuthSession.user_id == alice_id)
        assert (await session.execute(left)).scalar_one() == 0
