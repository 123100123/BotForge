"""Shared test helpers: test accounts, cookie-session clients, an ASGI client factory.

Endpoint tests go through the REAL authentication: ``CookieAuth`` turns the test-only request header
``X-Test-User: <name>`` (default ``alice``) into a real session for the account ``<name>@example.com``
(created on first use, see ``ensure_user``): the session row is created by the app's own
``create_session``, and the request carries its ``bf_session`` cookie and the CSRF header. Only the
database session is injected (``use_test_database``), because the app's engine reads DATABASE_URL.
Bots made for an owner name (``make_bot("bob")``) belong to that same account.

``X-Test-User: anonymous`` sends no cookie and no CSRF header.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.session import get_session
from app.security.csrf import CSRF_HEADER
from app.security.sessions import SESSION_COOKIE, create_session

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

SessionFactory = async_sessionmaker[AsyncSession]

TEST_USER_HEADER = "X-Test-User"
ANONYMOUS = "anonymous"
# Test accounts made by ensure_user have no usable password (not an argon2 hash): they only ever
# authenticate through sessions created directly.
NO_PASSWORD = "!test-account-without-password"


def email_for(name: str) -> str:
    return f"{name}@example.com"


async def ensure_user(session: AsyncSession, name: str) -> uuid.UUID:
    """The id of the test account ``<name>@example.com``, created if missing (the caller commits)."""
    email = email_for(name)
    await session.execute(
        pg_insert(User)
        .values(id=uuid.uuid4(), email=email, password_hash=NO_PASSWORD)
        .on_conflict_do_nothing(index_elements=[User.email])
    )
    return (await session.execute(select(User.id).where(User.email == email))).scalar_one()


async def user_id(session_factory: SessionFactory, name: str) -> uuid.UUID:
    async with session_factory() as session:
        uid = await ensure_user(session, name)
        await session.commit()
        return uid


class CookieAuth:
    """An httpx request hook that signs requests in as ``X-Test-User`` with a real session."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self.session_factory = session_factory
        self.tokens: dict[str, str] = {}

    async def token(self, name: str) -> str:
        if name not in self.tokens:
            async with self.session_factory() as session:
                uid = await ensure_user(session, name)
                self.tokens[name] = await create_session(session, uid)
                await session.commit()
        return self.tokens[name]

    async def __call__(self, request: httpx.Request) -> None:
        name = request.headers.pop(TEST_USER_HEADER, None) or "alice"
        if name == ANONYMOUS:
            return
        request.headers["Cookie"] = f"{SESSION_COOKIE}={await self.token(name)}"
        request.headers.setdefault(CSRF_HEADER, "1")


def use_test_database(app: FastAPI, session_factory: SessionFactory) -> None:
    """Serve the app's request sessions from ``session_factory`` (the test database)."""

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = test_session


def make_client(
    app: FastAPI,
    *,
    auth: CookieAuth | None = None,
    base_url: str = "http://test",
    client_address: str = "127.0.0.1",
) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(client_address, 50000))
    hooks = {"request": [auth]} if auth is not None else {}
    return httpx.AsyncClient(transport=transport, base_url=base_url, event_hooks=hooks)


def signed_in_client(app: FastAPI, session_factory: SessionFactory) -> httpx.AsyncClient:
    """The full app on the test database, with requests signed in through ``CookieAuth``."""
    use_test_database(app, session_factory)
    return make_client(app, auth=CookieAuth(session_factory))
