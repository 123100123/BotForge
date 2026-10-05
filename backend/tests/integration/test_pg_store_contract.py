"""The shared Store contract suite, run against PgStore (roadmap: both stores behave the same).

The same ``CONTRACT_CASES`` run against ``MemoryStore`` in ``tests/unit/runtime/test_memory_store.py``.
Needs a database.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot
from app.runtime.pg_store import PgStore
from tests.integration.helpers import NOW, SessionFactory, user_id
from tests.unit.runtime.store_contract import CONTRACT_CASES


@pytest_asyncio.fixture
async def make_store(session_factory: SessionFactory) -> AsyncIterator[Callable[[], Awaitable[PgStore]]]:
    """Factory of fresh stores, each bound to its own new bot and its own (never committed) session."""
    sessions: list[AsyncSession] = []
    owner_id = await user_id(session_factory, "alice")  # committed: the store sessions never commit

    async def _make() -> PgStore:
        session = session_factory()
        sessions.append(session)
        bot = Bot(owner_id=owner_id, name="contract")
        session.add(bot)
        await session.flush()
        return PgStore(session, bot.id, "live", owner_actor_id="owner")

    yield _make
    for session in sessions:
        await session.rollback()
        await session.close()


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c.__name__)
async def test_pg_store_contract(case: Any, make_store: Callable[[], Awaitable[PgStore]]) -> None:
    await case(make_store)


async def test_live_and_sandbox_of_one_bot_are_isolated(session_factory: SessionFactory) -> None:
    owner_id = await user_id(session_factory, "alice")
    async with session_factory() as session:
        bot = Bot(owner_id=owner_id, name="envs")
        session.add(bot)
        await session.flush()
        live = PgStore(session, bot.id, "live", "900")
        sandbox = PgStore(session, bot.id, "sandbox", "owner")
        record = await live.create_record("c", {"v": 1}, now=NOW)
        await live.set_session("ali", {"capability": "c", "step": "s", "vars": {}})
        assert await sandbox.list_records("c") == [] and await sandbox.count_records("c") == 0
        assert await sandbox.get_record("c", record.id) is None
        assert await sandbox.get_session("ali") is None
        assert (await live.owner_actor_id(), await sandbox.owner_actor_id()) == ("900", "owner")
        await session.rollback()
