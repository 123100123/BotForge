"""Fixtures for integration tests.

Database-backed tests need Postgres. Either set ``TEST_DATABASE_URL`` (e.g.
``postgresql://postgres@127.0.0.1:55432/postgres``), or install the optional ``dbtest`` group
(``uv sync --group dbtest``): when the variable is unset and ``pgserver`` is importable, a temporary
Postgres is started for the test session and removed afterwards. With neither, database tests are
skipped. The schema ``app`` is dropped and rebuilt once per session by running the real Alembic
migrations.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import CurrentUser, get_current_user
from app.config import get_settings, to_async_url
from app.db.models import Bot
from app.db.session import get_session
from app.integrations.telegram.client import FakeTelegramClient, get_telegram_provider
from app.main import create_app
from app.revisions.service import activate, create_draft
from tests.integration.helpers import BACKEND, REPO, SessionFactory, make_client, signed_in_client, user_id


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        async_url = to_async_url(url)
        assert async_url is not None
        yield async_url
        return
    try:
        import pgserver
    except ImportError:
        pytest.skip("TEST_DATABASE_URL is not set and pgserver is not installed; database tests are skipped")
    data_dir = tempfile.mkdtemp(prefix="botforge-pg-")
    server = pgserver.get_server(data_dir)
    try:
        async_url = to_async_url(server.get_uri())
        assert async_url is not None
        yield async_url
    finally:
        server.cleanup()
        shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def migrated_db(test_db_url: str) -> str:
    async def reset() -> None:
        engine = create_async_engine(test_db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS app CASCADE"))
        await engine.dispose()

    asyncio.run(reset())
    env = {**os.environ, "DATABASE_URL": test_db_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return test_db_url


@pytest_asyncio.fixture
async def session_factory(migrated_db: str) -> AsyncIterator[SessionFactory]:
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def golden_spec() -> dict[str, Any]:
    return json.loads((REPO / "examples" / "workshop.botspec.json").read_text(encoding="utf-8"))


MakeBot = Callable[..., Awaitable[tuple[uuid.UUID, uuid.UUID | None]]]


@pytest_asyncio.fixture
async def make_bot(session_factory: SessionFactory, golden_spec: dict[str, Any]) -> MakeBot:
    """Create a bot (optionally with an active golden-spec revision) owned by the test account
    ``<owner>@example.com`` (see ``helpers.ensure_user``). Returns (bot_id, revision_id)."""

    async def _make(
        owner: str = "alice", *, name: str = "ربات", active: bool = True
    ) -> tuple[uuid.UUID, uuid.UUID | None]:
        owner_id = await user_id(session_factory, owner)  # committed first, in its own transaction
        async with session_factory() as session:
            bot = Bot(owner_id=owner_id, name=name)
            session.add(bot)
            await session.flush()
            revision_id = None
            if active:
                revision = await create_draft(session, bot.id, spec=golden_spec)
                await activate(session, revision.id)
                revision_id = revision.id
            await session.commit()
            return bot.id, revision_id

    return _make


@pytest_asyncio.fixture
async def client(session_factory: SessionFactory) -> AsyncIterator[httpx.AsyncClient]:
    """The full app on the test database; requests are signed in as ``X-Test-User`` (default
    ``alice``) with real session cookies (see ``helpers.CookieAuth``)."""
    async with signed_in_client(create_app(), session_factory) as c:
        yield c


@pytest_asyncio.fixture
async def nodb_client() -> AsyncIterator[httpx.AsyncClient]:
    """App with no database at all, for request-shape tests: no database session, and, because
    authentication needs the database, a fixed caller in place of ``get_current_user`` (test-only)."""
    app = create_app()

    async def stand_in_user() -> CurrentUser:
        return CurrentUser(id=uuid.UUID(int=1), email="alice@example.com")

    async def no_session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_current_user] = stand_in_user
    app.dependency_overrides[get_session] = no_session
    async with make_client(app) as c:
        yield c


@pytest.fixture
def tg_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Settings the Telegram integration needs: an encryption key and an https public URL."""
    monkeypatch.setenv("TOKEN_ENC_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://bots.example.test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_tg() -> FakeTelegramClient:
    return FakeTelegramClient(bot_id=uuid.uuid4().int % 10**9 + 10**9, username="workshop_test_bot")


@pytest_asyncio.fixture
async def tg_client(
    session_factory: SessionFactory, fake_tg: FakeTelegramClient, tg_env: None
) -> AsyncIterator[httpx.AsyncClient]:
    """Full app with cookie sessions (as ``client``) and the fake Telegram client injected."""
    app = create_app()
    app.dependency_overrides[get_telegram_provider] = lambda: fake_tg.provider
    async with signed_in_client(app, session_factory) as c:
        yield c
