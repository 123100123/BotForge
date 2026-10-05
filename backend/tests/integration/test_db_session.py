"""The production engine keeps bound values out of exception text (error handlers log that text)."""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db.models import Bot
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.security.crypto import generate_webhook_secret
from tests.integration.helpers import ensure_user


@pytest_asyncio.fixture
async def production_engine(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Run the test against ``app.db.session``'s own engine, then drop it again."""
    await dispose_engine()
    yield
    await dispose_engine()
    get_settings.cache_clear()


async def test_the_engine_is_built_with_hidden_parameters(
    production_engine: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user@db.example.test/app")  # never connected
    get_settings.cache_clear()
    assert get_engine().sync_engine.hide_parameters is True


async def test_a_database_error_does_not_carry_the_webhook_secret(
    production_engine: None, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    get_settings.cache_clear()
    secret = generate_webhook_secret()
    tg_bot_id = uuid.uuid4().int % 10**9 + 10**9
    async with get_sessionmaker()() as session:
        owners = [await ensure_user(session, "a"), await ensure_user(session, "b")]
        await session.commit()
    async with get_sessionmaker()() as session:
        session.add_all(
            [
                Bot(owner_id=owners[0], name="a", tg_bot_id=tg_bot_id, tg_webhook_secret=secret),
                Bot(owner_id=owners[1], name="b", tg_bot_id=tg_bot_id, tg_webhook_secret=secret),
            ]
        )
        with pytest.raises(IntegrityError) as info:
            await session.flush()
        await session.rollback()
    text = str(info.value)
    assert "tg_bot_id" in text  # still a useful error
    assert secret not in text
