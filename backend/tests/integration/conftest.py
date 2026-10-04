"""Fixtures for integration tests.

Database-backed tests need ``TEST_DATABASE_URL`` (a Postgres URL, e.g.
``postgresql://postgres@127.0.0.1:55432/postgres``); without it they are skipped. The schema ``app``
is dropped and rebuilt once per session by running the real Alembic migration.
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import to_async_url
from app.db.models import Bot
from app.main import create_app
from app.revisions.service import activate, create_draft
from tests.integration.helpers import BACKEND, REPO, SessionFactory, install_test_auth, make_client


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; database-backed tests are skipped")
    async_url = to_async_url(url)
    assert async_url is not None
    return async_url


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
    """Create a bot (optionally with an active golden-spec revision). Returns (bot_id, revision_id)."""

    async def _make(
        owner_id: str = "alice", *, name: str = "ربات", active: bool = True
    ) -> tuple[uuid.UUID, uuid.UUID | None]:
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
    app = create_app()
    install_test_auth(app, session_factory)
    async with make_client(app) as c:
        yield c


@pytest_asyncio.fixture
async def nodb_client() -> AsyncIterator[httpx.AsyncClient]:
    """App with stand-in auth and no database session at all."""
    app = create_app()
    install_test_auth(app, None)
    async with make_client(app) as c:
        yield c
