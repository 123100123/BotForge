"""Own authentication end to end: signup, login, logout, /me, cookie sessions, CSRF, rate limits.

Each ``browser`` is one httpx client with its own cookie jar that sends ``X-BotForge-CSRF: 1`` like
the frontend does; nothing in the auth path is replaced (only the database session is injected).
Needs a database.
"""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from fastapi import FastAPI
from sqlalchemy import func, select, update

from app.api.auth import INVALID_CREDENTIALS
from app.config import get_settings
from app.db.models import AuthSession, Bot, User
from app.main import create_app
from app.security import accounts, passwords
from app.security.accounts import create_user
from app.security.rate_limit import AUTH_ATTEMPTS_PER_ADDRESS, AUTH_WINDOW_SECONDS, LOGIN_ATTEMPTS_PER_EMAIL
from app.security.sessions import SESSION_COOKIE, create_session, resolve_session, token_digest
from tests.integration.helpers import SessionFactory, make_client, use_test_database

PASSWORD = "correct horse battery"
WEEK = 168 * 3600
MAX_AGE = timedelta(days=30)  # AUTH_SESSION_MAX_AGE_DAYS default

Configure = Callable[..., None]


def new_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def session_cookie(response: httpx.Response) -> dict[str, str] | None:
    """The response's ``Set-Cookie`` for the session: {"value": ..., "<attribute>": ...}."""
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        if name.strip() != SESSION_COOKIE:
            continue
        value, *attributes = rest.split(";")
        parsed = {"value": value.strip()}
        for attribute in attributes:
            key, _, val = attribute.strip().partition("=")
            parsed[key.lower()] = val
        return parsed
    return None


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch) -> Iterator[Configure]:
    def apply(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def app(session_factory: SessionFactory) -> FastAPI:
    app = create_app()
    use_test_database(app, session_factory)
    return app


@pytest_asyncio.fixture
async def browser(app: FastAPI) -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def make(*, address: str = "127.0.0.1", https: bool = True, csrf: bool = True) -> httpx.AsyncClient:
        client = make_client(
            app, base_url="https://botforge.test" if https else "http://botforge.test", client_address=address
        )
        if csrf:
            client.headers["X-BotForge-CSRF"] = "1"
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


async def _post(client: httpx.AsyncClient, path: str, email: str, password: str) -> httpx.Response:
    # Encoded here with ASCII escapes: httpx's own encoder cannot send a lone surrogate ("\ud800").
    body = json.dumps({"email": email, "password": password})
    return await client.post(path, content=body, headers={"Content-Type": "application/json"})


async def signup(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await _post(client, "/auth/signup", email, password)


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await _post(client, "/auth/login", email, password)


async def sessions_of(session_factory: SessionFactory, user_id: uuid.UUID | str) -> list[AuthSession]:
    stmt = select(AuthSession).where(AuthSession.user_id == uuid.UUID(str(user_id)))
    async with session_factory() as session:
        return list((await session.execute(stmt)).scalars())


async def backdate(session_factory: SessionFactory, token: str, **values: datetime) -> None:
    """Overwrite timestamps of the session of ``token`` (e.g. a row the uncapped renewal left)."""
    async with session_factory() as session:
        await session.execute(
            update(AuthSession).where(AuthSession.token_hash == token_digest(token)).values(**values)
        )
        await session.commit()


# --------------------------------------------------------------------------- signup, login, logout, /me


async def test_signup_creates_the_account_and_a_session(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    c = browser()
    tag = uuid.uuid4().hex[:10]
    response = await signup(c, f"  New.Owner+{tag}@Example.COM ")
    assert response.status_code == 201, response.text
    user = response.json()["user"]
    assert set(response.json()) == {"user"} and set(user) == {"id", "email"}
    assert user["email"] == f"new.owner+{tag}@example.com"  # stripped and lowercased
    uuid.UUID(user["id"])
    assert response.headers["cache-control"] == "no-store"
    assert session_cookie(response) is not None

    me = await c.get("/me")
    assert me.status_code == 200
    assert me.json() == user
    async with session_factory() as session:
        row = await session.get(User, uuid.UUID(user["id"]))
        assert row is not None and row.email == user["email"]
        assert row.password_hash.startswith("$argon2id$") and PASSWORD not in row.password_hash


async def test_the_database_stores_only_the_token_digest(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    c = browser()
    response = await signup(c, new_email())
    token = c.cookies[SESSION_COOKIE]
    assert len(token) >= 43  # secrets.token_urlsafe(32): 32 random bytes
    rows = await sessions_of(session_factory, response.json()["user"]["id"])
    assert len(rows) == 1
    assert rows[0].token_hash == hashlib.sha256(token.encode()).hexdigest() == token_digest(token)
    assert token not in (rows[0].token_hash, str(rows[0].id))
    raw = select(func.count()).select_from(AuthSession).where(AuthSession.token_hash == token)
    async with session_factory() as session:
        assert (await session.execute(raw)).scalar_one() == 0


async def test_login_always_starts_a_new_session(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    email = new_email()
    first = browser()
    user_id = (await signup(first, email)).json()["user"]["id"]
    signup_token = first.cookies[SESSION_COOKIE]

    again = await login(first, email.upper())  # emails are normalized at login too
    assert again.status_code == 200, again.text
    assert again.json() == {"user": {"id": user_id, "email": email}}
    assert again.headers["cache-control"] == "no-store"
    login_token = first.cookies[SESSION_COOKIE]
    assert login_token != signup_token

    second = browser()
    assert (await login(second, email)).status_code == 200
    assert second.cookies[SESSION_COOKIE] not in (signup_token, login_token)

    digests = {row.token_hash for row in await sessions_of(session_factory, user_id)}
    # The session the first browser replaced is gone; both current ones work.
    assert digests == {token_digest(login_token), token_digest(second.cookies[SESSION_COOKIE])}
    assert (await first.get("/me")).status_code == 200
    assert (await second.get("/me")).status_code == 200


async def test_logout_ends_the_session_and_is_idempotent(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    c = browser()
    user_id = (await signup(c, new_email())).json()["user"]["id"]
    token = c.cookies[SESSION_COOKIE]

    out = await c.post("/auth/logout")
    assert out.status_code == 204 and out.content == b""
    cleared = session_cookie(out)
    assert cleared is not None and cleared["max-age"] == "0" and cleared["value"] in ("", '""')
    assert SESSION_COOKIE not in c.cookies
    assert await sessions_of(session_factory, user_id) == []

    stale = browser()
    stale.cookies.set(SESSION_COOKIE, token, domain="botforge.test")
    me = await stale.get("/me")
    assert me.status_code == 401 and me.json()["error"]["code"] == "invalid_session"

    assert (await c.post("/auth/logout")).status_code == 204  # no cookie at all
    assert (await stale.post("/auth/logout")).status_code == 204  # a dead cookie
    assert (await c.get("/me")).json()["error"]["code"] == "auth_required"


async def test_duplicate_email_is_409(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    email = new_email()
    assert (await signup(browser(), email)).status_code == 201
    c = browser()
    duplicate = await signup(c, f"  {email.upper()} ", "another password 123")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "email_taken"
    assert session_cookie(duplicate) is None
    async with session_factory() as session:
        count = await session.execute(select(func.count()).select_from(User).where(User.email == email))
        assert count.scalar_one() == 1


@pytest.mark.parametrize(("length", "status"), [(9, 422), (10, 201), (256, 201), (257, 422), (0, 422)])
async def test_password_length_rules(
    browser: Callable[..., httpx.AsyncClient], length: int, status: int
) -> None:
    response = await signup(browser(), new_email(), "p" * length)
    assert response.status_code == status, response.text
    if status == 422:
        assert response.json()["error"]["code"] == "weak_password"
        assert session_cookie(response) is None


@pytest.mark.parametrize(
    "email",
    [
        "",
        "   ",
        "no-at-sign",
        "a@",
        "@example.com",
        "two@at@example.com",
        "a b@example.com",
        "a@exa mple.com",
        "a@example..com",
        "a@-example.com",
        "a@example-.com",
        "x" * 65 + "@example.com",
        "a@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 63 + "." + "e" * 60 + ".com",
        "Kelvin@example.com",  # KELVIN SIGN: would lowercase to an ASCII "k"
        "ali@مثال.com",
        "line\n@example.com",
    ],
)
async def test_invalid_emails_are_422(browser: Callable[..., httpx.AsyncClient], email: str) -> None:
    response = await signup(browser(), email)
    assert response.status_code == 422, (email, response.text)
    assert response.json()["error"]["code"] == "invalid_email"


async def test_signup_can_be_disabled(
    browser: Callable[..., httpx.AsyncClient], configure: Configure, session_factory: SessionFactory
) -> None:
    configure(AUTH_ALLOW_SIGNUP="false")
    email = new_email()
    refused = await signup(browser(), email)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "signup_disabled"
    assert session_cookie(refused) is None
    async with session_factory() as session:
        assert (await session.execute(select(User).where(User.email == email))).first() is None
        await create_user(session, email, PASSWORD)  # what scripts/create_user.py does
        await session.commit()
    assert (await login(browser(), email)).status_code == 200  # existing accounts still log in


async def test_wrong_password_and_unknown_email_get_the_same_answer(
    browser: Callable[..., httpx.AsyncClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    email = new_email()
    assert (await signup(browser(), email)).status_code == 201

    verified_against: list[bool] = []  # True: a stored hash; False: the dummy (no such account)
    real_verify = passwords.verify_password_sync

    def spy(stored_hash: str | None, password: str) -> bool:
        verified_against.append(stored_hash is not None)
        return real_verify(stored_hash, password)

    monkeypatch.setattr(passwords, "verify_password_sync", spy)
    c = browser()
    answers = [
        await login(c, email, "wrong password!!"),
        await login(c, new_email()),
        await login(c, "not an email"),
        await login(c, email, ""),
    ]
    assert verified_against == [True, False, False, True]  # every failure costs one verification
    for answer in answers:
        assert answer.status_code == 401
        assert answer.json() == {"error": {"code": INVALID_CREDENTIALS[0], "message": INVALID_CREDENTIALS[1]}}
        assert session_cookie(answer) is None
    assert SESSION_COOKIE not in c.cookies


async def test_login_rehashes_a_password_hashed_with_old_parameters(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    email = new_email()
    old_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    async with session_factory() as session:
        session.add(User(email=email, password_hash=old_hash))
        await session.commit()
    assert (await login(browser(), email)).status_code == 200
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.password_hash != old_hash and not passwords.needs_rehash(user.password_hash)
    assert (await login(browser(), email)).status_code == 200  # the new hash verifies


async def test_unusual_passwords_and_placeholder_accounts_never_break_login(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    email = new_email()
    odd = "\ud800" * 5 + "رمز عبور"  # a lone surrogate is valid JSON (an escape) but not UTF-8
    assert (await signup(browser(), email, odd)).status_code == 201
    assert (await login(browser(), email, odd)).status_code == 200
    assert (await login(browser(), email, "\ud800" * 5)).status_code == 401
    assert (await login(browser(), "\ud800@example.com")).status_code == 401

    placeholder = f"legacy-{uuid.uuid4()}@botforge.invalid"  # as migration 0003 creates them
    async with session_factory() as session:
        session.add(User(email=placeholder, password_hash="!legacy-owner-without-password"))
        await session.commit()
    refused = await login(browser(), placeholder, "!legacy-owner-without-password")
    assert refused.status_code == 401 and refused.json()["error"]["code"] == "invalid_credentials"


async def test_no_transaction_is_open_while_passwords_are_hashed(
    session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hashing waits for a slot and takes ~50 ms; a pooled connection held meanwhile would let a burst
    of anonymous logins drain the pool every other request needs."""
    seen: list[tuple[str, bool]] = []
    async with session_factory() as session:
        real_hash, real_verify = accounts.hash_password, accounts.verify_password

        async def hash_spy(password: str) -> str:
            seen.append(("hash", session.in_transaction()))
            return await real_hash(password)

        async def verify_spy(stored_hash: str | None, password: str) -> bool:
            seen.append(("verify", session.in_transaction()))
            return await real_verify(stored_hash, password)

        monkeypatch.setattr(accounts, "hash_password", hash_spy)
        monkeypatch.setattr(accounts, "verify_password", verify_spy)
        email, outdated = new_email(), new_email()
        await accounts.create_user(session, email, PASSWORD)
        old_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
        session.add(User(email=outdated, password_hash=old_hash))
        await session.commit()
        assert await accounts.authenticate(session, email, PASSWORD) is not None
        assert await accounts.authenticate(session, email, "wrong password!!") is None
        assert await accounts.authenticate(session, new_email(), PASSWORD) is None
        assert await accounts.authenticate(session, outdated, PASSWORD) is not None  # verify, then rehash
        await session.commit()
        await accounts.reset_password(session, email, "new password 123")
        await session.commit()
    assert [kind for kind, _ in seen] == ["hash", "verify", "verify", "verify", "verify", "hash", "hash"]
    assert not any(held for _, held in seen), seen


# --------------------------------------------------------------------------- rate limits


async def test_login_is_rate_limited_per_email(browser: Callable[..., httpx.AsyncClient]) -> None:
    email = new_email()
    assert (await signup(browser(address="198.51.100.1"), email)).status_code == 201
    attacker = browser(address="198.51.100.2")
    for _ in range(LOGIN_ATTEMPTS_PER_EMAIL):
        assert (await login(attacker, email, "wrong password!!")).status_code == 401
    limited = await login(attacker, email)  # even the right password
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert 0 < int(limited.headers["retry-after"]) <= AUTH_WINDOW_SECONDS
    assert SESSION_COOKIE not in attacker.cookies

    elsewhere = browser(address="203.0.113.9")
    assert (await login(elsewhere, email)).status_code == 429  # the limit follows the email
    assert (await login(elsewhere, new_email())).status_code == 401  # other emails are unaffected


async def test_login_and_signup_are_rate_limited_per_address(
    browser: Callable[..., httpx.AsyncClient],
) -> None:
    spraying = browser(address="192.0.2.77")
    for _ in range(AUTH_ATTEMPTS_PER_ADDRESS):
        assert (await login(spraying, new_email())).status_code == 401
    limited = await login(spraying, new_email())
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
    assert (await signup(spraying, new_email())).status_code == 429  # one budget for both
    assert (await signup(browser(address="192.0.2.78"), new_email())).status_code == 201

    # IPv6 callers share their /64.
    first = browser(address="2001:db8:1:2::1")
    for _ in range(AUTH_ATTEMPTS_PER_ADDRESS):
        assert (await login(first, new_email())).status_code == 401
    neighbour = browser(address="2001:db8:1:2:ffff::9")
    assert (await login(neighbour, new_email())).status_code == 429
    assert (await login(browser(address="2001:db8:1:3::1"), new_email())).status_code == 401


# --------------------------------------------------------------------------- sessions


async def test_an_expired_session_is_rejected_and_deleted(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    async with session_factory() as session:
        user = await create_user(session, new_email(), PASSWORD)
        token = await create_session(session, user.id, now=datetime.now(UTC) - timedelta(hours=169))
        await session.commit()
    c = browser()
    c.cookies.set(SESSION_COOKIE, token, domain="botforge.test")
    response = await c.get("/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"
    assert await sessions_of(session_factory, user.id) == []  # purged when presented


async def test_sessions_slide_at_most_once_an_hour(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    started = datetime.now(UTC) - timedelta(hours=2)
    async with session_factory() as session:
        user = await create_user(session, new_email(), PASSWORD)
        token = await create_session(session, user.id, now=started)
        bot = Bot(owner_id=user.id, name="b")
        session.add(bot)
        await session.commit()
    c = browser()
    c.cookies.set(SESSION_COOKIE, token, domain="botforge.test")

    renewed = await c.get("/me")
    assert renewed.status_code == 200
    cookie = session_cookie(renewed)
    assert cookie is not None and cookie["value"] == token and cookie["max-age"] == str(WEEK)
    (row,) = await sessions_of(session_factory, user.id)
    assert row.last_seen_at > started + timedelta(hours=1)
    assert abs((row.expires_at - row.last_seen_at) - timedelta(hours=168)) < timedelta(seconds=1)

    quiet = await c.get("/me")  # renewed less than an hour ago: no write, no cookie
    assert quiet.status_code == 200 and session_cookie(quiet) is None
    (unchanged,) = await sessions_of(session_factory, user.id)
    assert unchanged.expires_at == row.expires_at

    # The renewed cookie also reaches responses that endpoints build themselves (204 here).
    async with session_factory() as session:
        await session.execute(
            AuthSession.__table__.update()
            .where(AuthSession.token_hash == token_digest(token))
            .values(last_seen_at=started)
        )
        await session.commit()
    deleted = await c.delete(f"/bots/{bot.id}")
    assert deleted.status_code == 204
    assert (session_cookie(deleted) or {}).get("value") == token


async def test_session_ttl_and_cookie_flags_follow_the_settings(
    browser: Callable[..., httpx.AsyncClient], configure: Configure, session_factory: SessionFactory
) -> None:
    secure = session_cookie(await signup(browser(), new_email()))
    assert secure is not None
    assert {"httponly", "secure", "path", "samesite", "max-age"} <= set(secure)
    assert secure["path"] == "/" and secure["samesite"].lower() == "lax" and secure["max-age"] == str(WEEK)
    assert "domain" not in secure

    configure(AUTH_COOKIE_SECURE="false", AUTH_SESSION_TTL_HOURS="2")
    plain = browser(https=False)  # plain-http local development
    response = await signup(plain, new_email())
    cookie = session_cookie(response)
    assert cookie is not None and "secure" not in cookie and "httponly" in cookie
    assert cookie["max-age"] == "7200"
    assert (await plain.get("/me")).status_code == 200  # the jar sends it over http
    (row,) = await sessions_of(session_factory, response.json()["user"]["id"])
    assert abs((row.expires_at - row.created_at) - timedelta(hours=2)) < timedelta(seconds=1)
    cleared = session_cookie(await plain.post("/auth/logout"))
    assert cleared is not None and "secure" not in cleared


async def test_a_session_at_its_maximum_age_is_rejected_even_if_recently_used(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    """30 days after login a session ends however active it is, even when its stored expiry still lies
    ahead (a row the uncapped renewal wrote, or one written under a larger AUTH_SESSION_MAX_AGE_DAYS)."""
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await create_user(session, new_email(), PASSWORD)
        token = await create_session(session, user.id, now=now - MAX_AGE)
        await session.commit()
    await backdate(
        session_factory, token, last_seen_at=now - timedelta(minutes=5), expires_at=now + timedelta(days=7)
    )
    c = browser()
    c.cookies.set(SESSION_COOKIE, token, domain="botforge.test")
    response = await c.get("/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"
    assert session_cookie(response) is None
    assert await sessions_of(session_factory, user.id) == []  # deleted when presented


async def test_the_maximum_age_is_exact(session_factory: SessionFactory) -> None:
    """One microsecond before created_at + 30 days the session works; at that instant it is gone."""
    created = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    bound = created + MAX_AGE
    async with session_factory() as session:
        user = await create_user(session, new_email(), PASSWORD)
        token = await create_session(session, user.id, now=created)
        await session.commit()
    recently = bound - timedelta(minutes=5)
    await backdate(session_factory, token, last_seen_at=recently, expires_at=bound + timedelta(days=7))
    async with session_factory() as session:
        before = await resolve_session(session, token, now=bound - timedelta(microseconds=1))
        assert before.user is not None and before.user.id == user.id
        assert not before.wrote and before.refresh_max_age is None  # used 5 minutes ago: no renewal due
        at = await resolve_session(session, token, now=bound)
        assert at.user is None and at.wrote and at.refresh_max_age is None
        await session.commit()
    assert await sessions_of(session_factory, user.id) == []


async def test_renewal_never_extends_a_session_past_its_maximum_age(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    """Twelve hours short of 30 days, renewal moves the expiry to created_at + 30 days instead of a week
    ahead, and the re-sent cookie lasts only what is left. The row starts as the uncapped renewal left it
    (renewed two hours ago, expiring 166 hours from now), so the cap also pulls such an expiry in."""
    now = datetime.now(UTC)
    left = timedelta(hours=12)
    async with session_factory() as session:
        user = await create_user(session, new_email(), PASSWORD)
        token = await create_session(session, user.id, now=now - (MAX_AGE - left))
        await session.commit()
    await backdate(
        session_factory, token, last_seen_at=now - timedelta(hours=2), expires_at=now + timedelta(hours=166)
    )
    c = browser()
    c.cookies.set(SESSION_COOKIE, token, domain="botforge.test")
    renewed = await c.get("/me")
    assert renewed.status_code == 200
    (row,) = await sessions_of(session_factory, user.id)
    assert row.last_seen_at > now - timedelta(hours=1)  # renewed by this request
    assert row.expires_at == row.created_at + MAX_AGE == now + left
    cookie = session_cookie(renewed)
    assert cookie is not None and cookie["value"] == token
    # What was left when the server renewed it (at most the 12 hours), not the 168-hour TTL.
    assert left.total_seconds() - 60 < int(cookie["max-age"]) <= left.total_seconds()

    # Renewals that are due later keep the capped expiry and shorten the cookie accordingly.
    await backdate(session_factory, token, last_seen_at=now - timedelta(hours=2))
    again = await c.get("/me")
    (row,) = await sessions_of(session_factory, user.id)
    assert again.status_code == 200 and row.expires_at == now + left
    again_cookie = session_cookie(again)
    assert again_cookie is not None and int(again_cookie["max-age"]) <= left.total_seconds()


async def test_a_new_session_and_its_cookie_end_within_the_maximum_age(
    browser: Callable[..., httpx.AsyncClient], configure: Configure, session_factory: SessionFactory
) -> None:
    configure(AUTH_SESSION_MAX_AGE_DAYS="1")  # shorter than the 168-hour TTL
    email = new_email()
    signed_up = await signup(browser(), email)
    logged_in = await login(browser(), email)
    for response in (signed_up, logged_in):
        assert response.status_code in (200, 201), response.text
        cookie = session_cookie(response)
        assert cookie is not None and cookie["max-age"] == str(24 * 3600)
    rows = await sessions_of(session_factory, signed_up.json()["user"]["id"])
    assert len(rows) == 2
    assert all(row.expires_at - row.created_at == timedelta(days=1) for row in rows)


async def test_login_purges_sessions_past_the_maximum_age(
    browser: Callable[..., httpx.AsyncClient], session_factory: SessionFactory
) -> None:
    email = new_email()
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = await create_user(session, email, PASSWORD)
        too_old = await create_session(session, user.id, now=now - MAX_AGE - timedelta(days=1))
        live = await create_session(session, user.id, now=now - timedelta(days=1))
        await session.commit()
    await backdate(session_factory, too_old, expires_at=now + timedelta(days=3))
    c = browser()
    assert (await login(c, email)).status_code == 200
    digests = {row.token_hash for row in await sessions_of(session_factory, user.id)}
    assert digests == {token_digest(live), token_digest(c.cookies[SESSION_COOKIE])}


# --------------------------------------------------------------------------- CSRF and ownership


async def test_csrf_header_and_origin_rules(
    browser: Callable[..., httpx.AsyncClient], configure: Configure, session_factory: SessionFactory
) -> None:
    configure(
        PUBLIC_BASE_URL="https://BotForge.example.com/api",
        FRONTEND_ORIGIN="http://localhost:3000, https://preview.example.com/",
    )
    c = browser(csrf=False)
    email = new_email()
    no_header = await signup(c, email)  # login CSRF: signup and login need the header too
    assert no_header.status_code == 403 and no_header.json()["error"]["code"] == "csrf_failed"
    assert (await login(c, email)).status_code == 403
    async with session_factory() as session:
        assert (await session.execute(select(User).where(User.email == email))).first() is None
    created = await c.post(
        "/auth/signup", json={"email": email, "password": PASSWORD}, headers={"X-BotForge-CSRF": "1"}
    )
    assert created.status_code == 201

    refused = {
        "no header": {},
        "wrong value": {"X-BotForge-CSRF": "0"},
        "foreign origin": {"X-BotForge-CSRF": "1", "Origin": "https://evil.example.com"},
        "null origin": {"X-BotForge-CSRF": "1", "Origin": "null"},
        "lookalike origin": {"X-BotForge-CSRF": "1", "Origin": "https://botforge.example.com.evil.test"},
        "other port": {"X-BotForge-CSRF": "1", "Origin": "https://botforge.example.com:8443"},
        "other scheme": {"X-BotForge-CSRF": "1", "Origin": "http://botforge.example.com"},
    }
    for label, headers in refused.items():
        response = await c.post("/bots", json={"name": label}, headers=headers)
        assert response.status_code == 403, label
        assert response.json()["error"]["code"] == "csrf_failed"
    assert (await c.post("/auth/logout")).status_code == 403
    assert (await c.get("/bots")).json() == []  # nothing was created

    allowed = {
        "same origin": {"X-BotForge-CSRF": "1", "Origin": "https://botforge.example.com"},
        "frontend origin": {"X-BotForge-CSRF": "1", "Origin": "http://localhost:3000"},
        "second frontend origin": {"X-BotForge-CSRF": "1", "Origin": "https://preview.example.com"},
        "no origin": {"X-BotForge-CSRF": "1"},
    }
    for label, headers in allowed.items():
        response = await c.post("/bots", json={"name": label}, headers=headers)
        assert response.status_code == 201, (label, response.text)

    # Reads need no header, whatever the Origin.
    listed = await c.get("/bots", headers={"Origin": "https://evil.example.com"})
    assert listed.status_code == 200 and len(listed.json()) == 4
    # The Telegram webhook is not cookie-authenticated and not subject to the CSRF check.
    webhook = await browser(csrf=False).post(f"/tg/{uuid.uuid4()}", json={})
    assert webhook.status_code == 404 and webhook.json()["error"]["code"] == "bot_not_found"


async def test_a_cookie_for_another_user_cannot_reach_a_foreign_bot(
    browser: Callable[..., httpx.AsyncClient],
) -> None:
    alice, bob = browser(), browser()
    assert (await signup(alice, new_email())).status_code == 201
    assert (await signup(bob, new_email())).status_code == 201
    bot_id = (await alice.post("/bots", json={"name": "ربات آلیس"})).json()["id"]

    for method, body in (("GET", None), ("PATCH", {"name": "هک"}), ("DELETE", None)):
        foreign = await bob.request(method, f"/bots/{bot_id}", json=body)
        missing = await bob.request(method, f"/bots/{uuid.uuid4()}", json=body)
        assert foreign.status_code == missing.status_code == 404, method
        assert foreign.json() == missing.json()
        assert foreign.json()["error"]["code"] == "bot_not_found"
    assert (await bob.get("/bots")).json() == []
    mine = await alice.get(f"/bots/{bot_id}")
    assert mine.status_code == 200 and mine.json()["name"] == "ربات آلیس"
