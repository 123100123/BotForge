"""AUTH_PROVIDER=supabase end to end on the test database: Supabase access tokens (HS256, signed with a
test secret) in ``Authorization: Bearer``, nothing in the auth path replaced (only the database session
is injected). Covers the routes the web app uses (``/me``, bots, capabilities, the raw-body upload, an
agent run and its event stream), ownership isolation on every owned route, refused tokens, ignored
cookies, the disabled own-login routes, and the ``users`` row kept for each token subject
(``app.security.accounts.ensure_external_user``), including its races. Needs a database.

The same paths without a database (header parsing, status codes, the route-wide guard):
tests/unit/security/test_supabase_current_user.py.
"""

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select

from app.agent.events import EventBus
from app.agent.llm import FakeLLM
from app.agent.orchestrator import Orchestrator
from app.agent.repository import SqlAgentRepository
from app.api import runs as runs_api
from app.api import uploads as uploads_api
from app.api.auth import LOCAL_AUTH_DISABLED
from app.config import get_settings
from app.db.models import AgentRun, AuthSession, Bot, UploadedFileRow, User
from app.main import create_app
from app.revisions.service import create_draft
from app.security import supabase_auth
from app.security.accounts import LEGACY_PASSWORD_HASH, create_user, ensure_external_user, placeholder_email
from app.security.sessions import SESSION_COOKIE, create_session
from tests.integration.helpers import SessionFactory, make_client, use_test_database
from tests.unit.agent.helpers import happy_scripts
from tests.unit.security.tokens import OMIT, SUPABASE_URL, mint, new_secret
from tests.unit.spreadsheets.workbooks import make_xlsx

SECRET = new_secret()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PASSWORD = "correct horse battery"


class Owner:
    """A Supabase user: a random user id (the token's ``sub``) and an email."""

    def __init__(self, email: str | None = None, *, user_id: uuid.UUID | None = None) -> None:
        self.id = user_id or uuid.uuid4()
        self.email = email if email is not None else f"owner-{self.id.hex[:12]}@example.com"

    def token(self, **overrides: Any) -> str:
        claims: dict[str, Any] = {"sub": str(self.id), "email": self.email, **overrides}
        return mint(SECRET, "HS256", **claims)

    def headers(self, **overrides: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(**overrides)}"}


def error(pair: tuple[str, str]) -> dict[str, dict[str, str]]:
    return {"error": {"code": pair[0], "message": pair[1]}}


@pytest.fixture
def supabase_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_JWKS_URL", "")
    get_settings.cache_clear()
    supabase_auth.reset_verifier()
    yield
    get_settings.cache_clear()
    supabase_auth.reset_verifier()


@pytest_asyncio.fixture
async def app(supabase_mode: None, session_factory: SessionFactory) -> FastAPI:
    app = create_app()
    use_test_database(app, session_factory)
    return app


@pytest_asyncio.fixture
async def api(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """The app in supabase mode; every request carries its own Authorization header (or none)."""
    async with make_client(app, base_url="https://api.botforge.test") as client:
        yield client


async def account(session_factory: SessionFactory, user_id: uuid.UUID) -> User | None:
    async with session_factory() as session:
        return await session.get(User, user_id)


async def create_bot(api: httpx.AsyncClient, owner: Owner, name: str = "ربات") -> str:
    response = await api.post("/bots", json={"name": name}, headers=owner.headers())
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --------------------------------------------------------------------------- the routes the web app uses


async def test_me_creates_the_account_on_first_sight_and_only_then(
    api: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    owner = Owner()
    assert await account(session_factory, owner.id) is None
    first = await api.get("/me", headers=owner.headers())
    assert first.status_code == 200, first.text
    assert first.json() == {"id": str(owner.id), "email": owner.email}
    assert "set-cookie" not in first.headers
    row = await account(session_factory, owner.id)
    assert row is not None and row.email == owner.email
    assert row.password_hash == LEGACY_PASSWORD_HASH  # never a usable password

    again = await api.get("/me", headers=owner.headers())
    assert again.status_code == 200 and again.json() == first.json()
    async with session_factory() as session:
        rows = await session.execute(select(func.count()).select_from(User).where(User.id == owner.id))
        assert rows.scalar_one() == 1
        sessions = await session.execute(
            select(func.count()).select_from(AuthSession).where(AuthSession.user_id == owner.id)
        )
        assert sessions.scalar_one() == 0  # no cookie session is ever made in this mode


async def test_bots_and_capabilities_with_a_bearer_token_and_no_csrf_header(api: httpx.AsyncClient) -> None:
    alice, bob = Owner(), Owner()
    bot_id = await create_bot(api, alice, "ربات آلیس")  # a POST without X-BotForge-CSRF
    listed = await api.get("/bots", headers=alice.headers())
    assert [b["id"] for b in listed.json()] == [bot_id]
    assert (await api.get(f"/bots/{bot_id}", headers=alice.headers())).json()["name"] == "ربات آلیس"
    capabilities = await api.get(f"/bots/{bot_id}/capabilities", headers=alice.headers())
    assert capabilities.status_code == 200 and capabilities.json()["categories"]
    renamed = await api.patch(f"/bots/{bot_id}", json={"name": "نام تازه"}, headers=alice.headers())
    assert renamed.status_code == 200 and renamed.json()["name"] == "نام تازه"

    assert (await api.get("/bots", headers=bob.headers())).json() == []
    missing = uuid.uuid4()
    for method, template, body in (
        ("GET", "/bots/{}", None),
        ("PATCH", "/bots/{}", {"name": "هک"}),
        ("DELETE", "/bots/{}", None),
        ("GET", "/bots/{}/capabilities", None),
    ):
        foreign = await api.request(method, template.format(bot_id), json=body, headers=bob.headers())
        absent = await api.request(method, template.format(missing), json=body, headers=bob.headers())
        assert foreign.status_code == absent.status_code == 404, (method, template)
        assert foreign.json() == absent.json()
        assert foreign.json()["error"]["code"] == "bot_not_found"

    assert (await api.delete(f"/bots/{bot_id}", headers=alice.headers())).status_code == 204
    assert (await api.get("/bots", headers=alice.headers())).json() == []


async def test_other_owners_get_404_on_every_owned_route(
    api: httpx.AsyncClient, app: FastAPI, session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    """Every route with a ``{bot_id}``, ``{run_id}`` or ``{revision_id}`` placeholder, taken from the
    OpenAPI schema (so a route added later is covered), answers another owner's ids exactly like ids
    that do not exist."""
    alice, bob = Owner(), Owner()
    bot_id = uuid.UUID(await create_bot(api, alice))
    await create_bot(api, bob)  # Bob owns a bot too: having one grants nothing on others
    async with session_factory() as session:
        revision = await create_draft(session, bot_id, spec=golden_spec)
        run = AgentRun(bot_id=bot_id, kind="create", phase="done", status="done")
        session.add(run)
        await session.commit()
        owned = {"bot_id": bot_id, "run_id": run.id, "revision_id": revision.id}
    codes = {"bot_id": "bot_not_found", "run_id": "run_not_found", "revision_id": "revision_not_found"}

    checked = 0
    for template, operations in app.openapi()["paths"].items():
        kind = next((name for name in ("bot_id", "run_id", "revision_id") if f"{{{name}}}" in template), None)
        if kind is None or template == "/tg/{bot_id}":  # the webhook: Telegram's secret header, no login
            continue

        def fill(ids: dict[str, uuid.UUID], template: str = template) -> str:
            return re.sub(r"\{([^}]+)\}", lambda m: str(ids.get(m[1], "1")), template)

        missing = {name: uuid.uuid4() for name in owned}
        for method in sorted(set(operations) & {"get", "post", "put", "patch", "delete"}):
            foreign = await api.request(method.upper(), fill(owned), headers=bob.headers())
            absent = await api.request(method.upper(), fill(missing), headers=bob.headers())
            assert foreign.status_code == 404, (method, template, foreign.text)
            assert foreign.json() == absent.json(), (method, template)
            assert foreign.json()["error"]["code"] == codes[kind], (method, template)
            checked += 1
    assert checked >= 40

    mine = await api.get(f"/bots/{bot_id}", headers=alice.headers())
    assert mine.status_code == 200  # untouched by all of the above
    assert (await api.get(f"/revisions/{owned['revision_id']}", headers=alice.headers())).status_code == 200
    assert (await api.get(f"/runs/{owned['run_id']}", headers=alice.headers())).status_code == 200


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(root))
    monkeypatch.delenv("UPLOAD_MAX_BYTES", raising=False)
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()
    assert uploads_api.IN_FLIGHT.count == 0


async def test_the_raw_body_upload_with_a_bearer_token(
    api: httpx.AsyncClient, upload_dir: Path, session_factory: SessionFactory
) -> None:
    alice, bob = Owner(), Owner()
    bot_id = await create_bot(api, alice)
    data = make_xlsx({"Sales": [["name", "amount"], ["c1", 10], ["c2", 20]]})

    def put(headers: dict[str, str]) -> Any:
        return api.put(
            f"/uploads/bots/{bot_id}",
            params={"filename": "sales.xlsx"},
            content=data,
            headers={"Content-Type": XLSX, **headers},
        )

    uploaded = await put(alice.headers())  # no CSRF header
    assert uploaded.status_code == 201, uploaded.text
    listed = await api.get(f"/bots/{bot_id}/uploads", headers=alice.headers())
    assert [u["id"] for u in listed.json()] == [uploaded.json()["id"]]
    async with session_factory() as session:
        row = await session.get(UploadedFileRow, uuid.UUID(uploaded.json()["id"]))
        assert row is not None and row.uploaded_by == str(alice.id)

    foreign = await put(bob.headers())
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "bot_not_found"
    anonymous = await put({})
    assert anonymous.status_code == 401 and anonymous.json()["error"]["code"] == "auth_required"
    expired = await put(alice.headers(exp=int(time.time()) - 3600))
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "invalid_token"
    upload_id = uploaded.json()["id"]
    assert (await api.get(f"/bots/{bot_id}/uploads/{upload_id}", headers=bob.headers())).status_code == 404


async def raw_put(app: FastAPI, path: str, headers: dict[str, str], total: int) -> tuple[int, int]:
    """PUT ``total`` bytes straight through ASGI (declared length). Returns (status, bytes pulled)."""
    remaining, pulled = total, 0
    status: list[int] = []

    async def receive() -> dict[str, Any]:
        nonlocal remaining, pulled
        if remaining <= 0:
            return {"type": "http.disconnect"}
        size = min(64 * 1024, remaining)
        remaining -= size
        pulled += size
        return {"type": "http.request", "body": b"x" * size, "more_body": remaining > 0}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])

    raw_headers = [(b"host", b"test"), (b"content-length", str(total).encode())]
    raw_headers += [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"filename=data.csv",
        "headers": raw_headers,
        "client": ("203.0.113.9", 4000),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    return status[0], pulled


async def test_a_refused_bearer_upload_never_gets_its_body_read(
    api: httpx.AsyncClient, app: FastAPI, upload_dir: Path
) -> None:
    alice, bob = Owner(), Owner()
    bot_id = await create_bot(api, alice)
    huge = 50 * 1024 * 1024
    for label, headers, expected in (
        ("anonymous", {}, 401),
        ("bad token", {"Authorization": "Bearer not.a.token"}, 401),
        ("expired", alice.headers(exp=int(time.time()) - 3600), 401),
        ("someone else's bot", bob.headers(), 404),
    ):
        assert await raw_put(app, f"/uploads/bots/{bot_id}", headers, huge) == (expected, 0), label


def make_orchestrator(app: FastAPI, session_factory: SessionFactory) -> Orchestrator:
    orchestrator = Orchestrator(
        SqlAgentRepository(session_factory), FakeLLM(**happy_scripts()), bus=EventBus()
    )
    app.dependency_overrides[runs_api.get_orchestrator] = lambda: orchestrator
    return orchestrator


def stream_events(response: httpx.Response) -> list[dict[str, Any]]:
    frames = [f for f in response.text.split("\n\n") if f.strip()]
    return [
        json.loads(
            dict(line.split(": ", 1) for line in frame.splitlines() if not line.startswith(":"))["data"]
        )
        for frame in frames
    ]


async def test_an_agent_run_and_its_event_stream_with_a_bearer_token(
    api: httpx.AsyncClient, app: FastAPI, session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_api, "run_creation_limiter", runs_api.RateLimiter())
    orchestrator = make_orchestrator(app, session_factory)
    alice, bob = Owner(), Owner()
    bot_id = await create_bot(api, alice)
    created = await api.post(
        f"/bots/{bot_id}/runs", json={"message": "یک ربات کارگاه"}, headers=alice.headers()
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    await orchestrator.wait_idle()
    assert (await api.get(f"/runs/{run_id}", headers=alice.headers())).json()["status"] == "waiting_approval"
    approved = await api.post(f"/runs/{run_id}/approve", headers=alice.headers())  # no CSRF header
    assert approved.status_code == 200 and approved.json()["status"] == "done", approved.text

    stream = await api.get(
        f"/runs/{run_id}/events", headers={**alice.headers(), "Accept": "text/event-stream"}
    )
    assert stream.status_code == 200 and stream.headers["content-type"].startswith("text/event-stream")
    events = stream_events(stream)
    assert events[0]["type"] == "owner_message"
    assert events[-1]["type"] == "run_status" and events[-1]["payload"]["status"] == "done"
    resumed = await api.get(
        f"/runs/{run_id}/events", headers={**alice.headers(), "Last-Event-ID": str(events[-2]["id"])}
    )
    assert [e["id"] for e in stream_events(resumed)] == [events[-1]["id"]]

    foreign = await api.get(f"/runs/{run_id}/events", headers=bob.headers())
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "run_not_found"
    anonymous = await api.get(f"/runs/{run_id}/events")
    assert anonymous.status_code == 401 and anonymous.json()["error"]["code"] == "auth_required"
    assert anonymous.headers["www-authenticate"] == "Bearer"


# --------------------------------------------------------------------------- refusals


async def test_refused_tokens_are_401_and_create_no_account(
    api: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    owner = Owner()
    now = int(time.time())
    cases = {
        "missing": ({}, "auth_required"),
        "expired": (owner.headers(exp=now - 3600), "invalid_token"),
        "wrong signature": (
            {"Authorization": f"Bearer {mint(new_secret(), 'HS256', sub=str(owner.id))}"},
            "invalid_token",
        ),
        "anonymous session": (owner.headers(is_anonymous=True), "invalid_token"),
        "other project": (owner.headers(iss="https://other.supabase.co/auth/v1"), "invalid_token"),
        "anon key audience": (owner.headers(aud="anon"), "invalid_token"),
    }
    for label, (headers, code) in cases.items():
        for method, path in (("GET", "/me"), ("GET", "/bots"), ("POST", "/bots")):
            response = await api.request(method, path, json={"name": label}, headers=headers)
            assert response.status_code == 401, (label, method, path, response.text)
            assert response.json()["error"]["code"] == code, label
            assert response.headers["www-authenticate"] == "Bearer"
    assert await account(session_factory, owner.id) is None
    async with session_factory() as session:
        probes = await session.execute(select(func.count()).select_from(Bot).where(Bot.name.in_(list(cases))))
        assert probes.scalar_one() == 0


async def test_a_session_cookie_counts_for_nothing(
    api: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    async with session_factory() as session:
        local = await create_user(session, f"local-{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        cookie_token = await create_session(session, local.id)
        await session.commit()
    cookie = {"Cookie": f"{SESSION_COOKIE}={cookie_token}", "X-BotForge-CSRF": "1"}
    for method, path in (("GET", "/me"), ("GET", "/bots"), ("POST", "/bots")):
        response = await api.request(method, path, json={"name": "x"}, headers=cookie)
        assert response.status_code == 401, (method, path)
        assert response.json()["error"]["code"] == "auth_required"
        assert "set-cookie" not in response.headers

    supabase_owner = Owner()  # a valid session cookie of another user next to a bearer token
    both = await api.get("/me", headers={**cookie, **supabase_owner.headers()})
    assert both.status_code == 200 and both.json()["id"] == str(supabase_owner.id)
    assert "set-cookie" not in both.headers


@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login", "/auth/logout"])
async def test_the_own_login_routes_are_404_and_do_nothing(
    api: httpx.AsyncClient, session_factory: SessionFactory, path: str
) -> None:
    email = f"local-{uuid.uuid4().hex[:8]}@example.com"
    async with session_factory() as session:
        existing = await create_user(session, email, PASSWORD)
        await session.commit()
    fresh = f"new-{uuid.uuid4().hex[:8]}@example.com"
    for body in ({"email": email, "password": PASSWORD}, {"email": fresh, "password": PASSWORD}):
        response = await api.post(path, json=body, headers={"X-BotForge-CSRF": "1"})
        assert response.status_code == 404 and response.json() == error(LOCAL_AUTH_DISABLED)
        assert "set-cookie" not in response.headers
    async with session_factory() as session:
        assert (await session.execute(select(User).where(User.email == fresh))).first() is None
        made = await session.execute(
            select(func.count()).select_from(AuthSession).where(AuthSession.user_id == existing.id)
        )
        assert made.scalar_one() == 0


async def test_an_external_account_can_never_use_the_own_login(
    api: httpx.AsyncClient, session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = Owner()
    assert (await api.get("/me", headers=owner.headers())).status_code == 200
    monkeypatch.setenv("AUTH_PROVIDER", "local")  # the same database under the own login
    get_settings.cache_clear()
    app = create_app()
    use_test_database(app, session_factory)
    async with make_client(app, base_url="https://botforge.test") as browser:
        for password in (LEGACY_PASSWORD_HASH, PASSWORD, ""):
            response = await browser.post(
                "/auth/login",
                json={"email": owner.email, "password": password},
                headers={"X-BotForge-CSRF": "1"},
            )
            assert response.status_code == 401 and response.json()["error"]["code"] == "invalid_credentials"


# --------------------------------------------------------------------------- the account row's email


async def test_a_placeholder_account_takes_the_token_email(
    api: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    owner = Owner()
    async with session_factory() as session:  # as migration 0003 adopts an existing bot's owner
        session.add(User(id=owner.id, email=placeholder_email(owner.id), password_hash=LEGACY_PASSWORD_HASH))
        await session.commit()
    me = await api.get("/me", headers=owner.headers())
    assert me.status_code == 200 and me.json() == {"id": str(owner.id), "email": owner.email}
    row = await account(session_factory, owner.id)
    assert row is not None and row.email == owner.email and row.password_hash == LEGACY_PASSWORD_HASH


async def test_an_email_another_account_has_gives_a_unique_placeholder(
    api: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    shared = f"shared-{uuid.uuid4().hex[:8]}@example.com"
    async with session_factory() as session:
        local = await create_user(session, shared, PASSWORD)  # an own-login account with that email
        await session.commit()
    owner = Owner(shared)
    me = await api.get("/me", headers=owner.headers())
    assert me.status_code == 200
    assert me.json() == {"id": str(owner.id), "email": placeholder_email(owner.id)}
    bot_id = await create_bot(api, owner)  # a working account of its own, the email notwithstanding
    async with session_factory() as session:
        untouched = await session.get(User, local.id)
        assert untouched is not None and untouched.email == shared
        owners = (await session.execute(select(Bot.owner_id).where(Bot.id == uuid.UUID(bot_id)))).scalars()
        assert list(owners) == [owner.id]

    async with session_factory() as session:  # the address becomes free: the placeholder takes it
        gone = await session.get(User, local.id)
        assert gone is not None
        gone.email = f"renamed-{uuid.uuid4().hex[:8]}@example.com"
        await session.commit()
    assert (await api.get("/me", headers=owner.headers())).json()["email"] == shared


@pytest.mark.parametrize("email", [OMIT, "", "not an email", "x@botforge.invalid", "Ünïcode@example.com"])
async def test_a_token_without_a_usable_email_gets_a_placeholder(
    api: httpx.AsyncClient, session_factory: SessionFactory, email: Any
) -> None:
    owner = Owner()
    me = await api.get("/me", headers=owner.headers(email=email))
    assert me.status_code == 200 and me.json()["email"] == placeholder_email(owner.id)
    assert (await create_bot(api, owner)) is not None


async def test_a_real_email_is_never_overwritten(
    api: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    owner = Owner()
    assert (await api.get("/me", headers=owner.headers())).json()["email"] == owner.email
    changed = await api.get("/me", headers=owner.headers(email="changed@example.com"))
    assert changed.json()["email"] == owner.email
    row = await account(session_factory, owner.id)
    assert row is not None and row.email == owner.email


async def test_email_case_is_normalized(api: httpx.AsyncClient) -> None:
    owner = Owner(f"Mixed.Case-{uuid.uuid4().hex[:8]}@Example.COM")
    me = await api.get("/me", headers=owner.headers())
    assert me.json()["email"] == owner.email.lower()


# --------------------------------------------------------------------------- races


async def test_concurrent_first_requests_create_one_account(
    api: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    owner = Owner()
    responses = await asyncio.gather(
        *(api.get("/me", headers=owner.headers()) for _ in range(4)),
        *(api.post("/bots", json={"name": f"b{i}"}, headers=owner.headers()) for i in range(4)),
    )
    assert [r.status_code for r in responses] == [200] * 4 + [201] * 4, [r.text for r in responses]
    async with session_factory() as session:
        users = await session.execute(select(func.count()).select_from(User).where(User.id == owner.id))
        bots = await session.execute(select(func.count()).select_from(Bot).where(Bot.owner_id == owner.id))
        assert users.scalar_one() == 1 and bots.scalar_one() == 4


async def blocked(task: asyncio.Task[Any]) -> bool:
    """Whether ``task`` is still waiting (on a row lock or a unique index) after a moment."""
    await asyncio.sleep(0.3)
    return not task.done()


async def test_the_insert_race_of_one_owner_is_settled_by_on_conflict(
    session_factory: SessionFactory,
) -> None:
    """Deterministic: the second first request waits on the first one's uncommitted row and then
    inserts nothing; it neither fails nor makes a second row."""
    owner = Owner()
    async with session_factory() as first, session_factory() as second:
        winner = await ensure_external_user(first, owner.id, owner.email)
        assert winner.wrote
        loser = asyncio.create_task(ensure_external_user(second, owner.id, owner.email))
        assert await blocked(loser)  # waiting for the first transaction
        await first.commit()
        result = await asyncio.wait_for(loser, timeout=10)
        await second.commit()
    assert (result.id, result.email, result.wrote) == (owner.id, owner.email, False)
    async with session_factory() as session:
        rows = await session.execute(select(func.count()).select_from(User).where(User.id == owner.id))
        assert rows.scalar_one() == 1


async def test_two_new_accounts_racing_for_one_email_end_with_one_placeholder(
    session_factory: SessionFactory,
) -> None:
    shared = f"race-{uuid.uuid4().hex[:8]}@example.com"
    one, two = Owner(shared), Owner(shared)
    async with session_factory() as first, session_factory() as second:
        assert (await ensure_external_user(first, one.id, shared)).email == shared
        racing = asyncio.create_task(ensure_external_user(second, two.id, shared))
        assert await blocked(racing)  # waiting on the unique email of the uncommitted row
        await first.commit()
        result = await asyncio.wait_for(racing, timeout=10)
        await second.commit()
    assert (result.id, result.email, result.wrote) == (two.id, placeholder_email(two.id), True)


async def test_the_placeholder_upgrade_race_updates_once(session_factory: SessionFactory) -> None:
    owner = Owner()
    async with session_factory() as session:
        session.add(User(id=owner.id, email=placeholder_email(owner.id), password_hash=LEGACY_PASSWORD_HASH))
        await session.commit()
    async with session_factory() as first, session_factory() as second:
        assert (await ensure_external_user(first, owner.id, owner.email)).wrote
        racing = asyncio.create_task(ensure_external_user(second, owner.id, owner.email))
        assert await blocked(racing)  # waiting on the row lock of the first update
        await first.commit()
        result = await asyncio.wait_for(racing, timeout=10)
        await second.commit()
    assert (result.email, result.wrote) == (owner.email, False)
