"""scripts/seed_demo.py: demo workshops, the full workshop with a waitlist, idempotency, reset."""

import importlib.util
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update

from app.db.models import Bot, BotUser, SessionRow
from app.revisions.service import activate, create_draft
from app.runtime.pg_store import Env, PgStore
from tests.integration.conftest import MakeBot
from tests.integration.helpers import BACKEND, SessionFactory

PERSIAN = re.compile(r"[؀-ۿ]")


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_demo", BACKEND / "scripts" / "seed_demo.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed_demo = _load_script()


async def _run_seed(session_factory: SessionFactory, bot_id: uuid.UUID, now: datetime | None = None) -> Any:
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        result = await seed_demo.seed(session, bot, now)
        await session.commit()
        return result


async def _run_reset(session_factory: SessionFactory, bot_id: uuid.UUID) -> int:
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        removed = await seed_demo.reset(session, bot)
        await session.commit()
        return removed


async def _counts(session_factory: SessionFactory, bot_id: uuid.UUID, env: Env = "live") -> dict[str, int]:
    async with session_factory() as session:
        store = PgStore(session, bot_id, env)
        return {
            "workshop": await store.count_records("workshop"),
            "book_workshop": await store.count_records("book_workshop"),
            "waitlisted": await store.count_records("book_workshop", status_in=["waitlisted"]),
        }


async def test_seed_creates_workshops_full_workshop_and_persian_customers(
    make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    now = datetime.now(UTC)
    result = await _run_seed(session_factory, bot_id, now)
    assert result.seeded
    assert len(result.workshop_ids) >= 4

    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        workshops = await store.list_records("workshop")
        assert len(workshops) == len(result.workshop_ids)
        starts = [datetime.fromisoformat(w.data["starts_at"]) for w in workshops]
        assert all(s > now for s in starts), "every workshop is upcoming"
        assert any(s <= now + timedelta(hours=1) for s in starts), "one starts within the hour"
        for w in workshops:
            assert PERSIAN.search(w.data["title"]) and PERSIAN.search(w.data["teacher"])

        full = [
            w
            for w in workshops
            if await store.count_records("book_workshop", item_id=w.id, status_in=["confirmed"]) == 10
        ]
        assert len(full) == 1
        waiting = await store.list_records("book_workshop", item_id=full[0].id, status_in=["waitlisted"])
        assert len(waiting) >= 1

        # distinct demo actors with Persian display names, in the live environment only
        users = (
            await session.execute(
                select(BotUser).where(BotUser.bot_id == bot_id, BotUser.env == "live")
            )
        ).scalars().all()
        assert len({u.actor_id for u in users}) == len(users) >= 10
        assert all(PERSIAN.search(u.display_name) for u in users)
    assert (await _counts(session_factory, bot_id, "sandbox")) == {
        "workshop": 0,
        "book_workshop": 0,
        "waitlisted": 0,
    }


async def test_seed_is_idempotent(make_bot: MakeBot, session_factory: SessionFactory) -> None:
    bot_id, _ = await make_bot()
    first = await _run_seed(session_factory, bot_id)
    before = await _counts(session_factory, bot_id)
    second = await _run_seed(session_factory, bot_id)
    assert first.seeded and not second.seeded
    assert await _counts(session_factory, bot_id) == before


async def test_reset_removes_only_what_the_seed_created(
    make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    other_id, _ = await make_bot("bob")
    await _run_seed(session_factory, other_id)
    other_before = await _counts(session_factory, other_id)

    # an owner-made workshop that must survive the reset
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        await store.create_record(
            "workshop",
            {
                "title": "کارگاه من",
                "description": "x",
                "teacher": "من",
                "starts_at": "2030-01-01T10:00:00+00:00",
            },
            now=datetime.now(UTC),
        )
        await session.commit()

    await _run_seed(session_factory, bot_id)
    assert await _run_reset(session_factory, bot_id) >= 4
    assert await _counts(session_factory, bot_id) == {"workshop": 1, "book_workshop": 0, "waitlisted": 0}
    async with session_factory() as session:
        left = (
            await session.execute(select(func.count()).select_from(BotUser).where(BotUser.bot_id == bot_id))
        ).scalar_one()
        assert left == 0
    assert await _counts(session_factory, other_id) == other_before

    assert await _run_reset(session_factory, bot_id) == 0  # nothing left to remove
    again = await _run_seed(session_factory, bot_id)  # and it can be seeded again
    assert again.seeded


async def _activate_new_revision(
    session_factory: SessionFactory, bot_id: uuid.UUID, spec: dict[str, Any]
) -> None:
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        revision = await create_draft(session, bot_id, spec=spec, parent_id=bot.active_revision_id)
        await activate(session, revision.id)
        await session.commit()


async def test_seed_survives_an_activation_and_reset_still_removes_it(
    make_bot: MakeBot, session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_id, _ = await make_bot()
    first = await _run_seed(session_factory, bot_id)
    before = await _counts(session_factory, bot_id)

    await _activate_new_revision(session_factory, bot_id, golden_spec)  # clears every live session

    assert not (await _run_seed(session_factory, bot_id)).seeded  # still known: nothing doubled
    assert await _counts(session_factory, bot_id) == before
    assert await _run_reset(session_factory, bot_id) == len(first.workshop_ids)
    assert await _counts(session_factory, bot_id) == {"workshop": 0, "book_workshop": 0, "waitlisted": 0}
    async with session_factory() as session:
        markers = (
            await session.execute(
                select(func.count()).select_from(SessionRow).where(SessionRow.bot_id == bot_id)
            )
        ).scalar_one()
        assert markers == 0


async def test_reset_honours_a_marker_left_in_live_by_an_older_seed(
    make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot()
    first = await _run_seed(session_factory, bot_id)
    async with session_factory() as session:
        await session.execute(
            update(SessionRow)
            .where(SessionRow.bot_id == bot_id, SessionRow.actor_id == seed_demo.MARKER_ACTOR)
            .values(env="live")
        )
        await session.commit()
    assert not (await _run_seed(session_factory, bot_id)).seeded
    assert await _run_reset(session_factory, bot_id) == len(first.workshop_ids)
    assert await _counts(session_factory, bot_id) == {"workshop": 0, "book_workshop": 0, "waitlisted": 0}
    async with session_factory() as session:
        left = (
            await session.execute(
                select(func.count()).select_from(SessionRow).where(SessionRow.bot_id == bot_id)
            )
        ).scalar_one()
        assert left == 0


async def test_seed_needs_an_active_revision(make_bot: MakeBot, session_factory: SessionFactory) -> None:
    bot_id, _ = await make_bot(active=False)
    with pytest.raises(seed_demo.SeedError):
        await _run_seed(session_factory, bot_id)


async def test_seeded_data_shows_up_in_the_data_api(
    make_bot: MakeBot, session_factory: SessionFactory, client: httpx.AsyncClient
) -> None:
    bot_id, _ = await make_bot()
    await _run_seed(session_factory, bot_id)
    page = (await client.get(f"/bots/{bot_id}/data/book_workshop?limit=200")).json()
    assert page["total"] >= 13
    assert all(row["actor_name"] and row["item_title"] for row in page["items"])
    statuses = {row["status"] for row in page["items"]}
    assert {"confirmed", "waitlisted"} <= statuses
