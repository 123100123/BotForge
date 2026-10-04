"""PgStore against the Store protocol rules (runtime/store.py docstring). Needs TEST_DATABASE_URL."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Bot
from app.runtime.contracts import Actor
from app.runtime.pg_store import PgStore, advisory_key, advisory_lock
from app.runtime.store import Record
from tests.integration.conftest import MakeBot
from tests.integration.helpers import NOW, SessionFactory


@pytest.fixture
async def bot_id(make_bot: MakeBot) -> uuid.UUID:
    return (await make_bot(active=False))[0]


async def test_create_and_get(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        rec = await store.create_record(
            "workshop", {"title": "الف"}, status="x", actor_id="u1", item_id=7, now=NOW
        )
        assert isinstance(rec, Record)
        assert rec.id > 0
        assert (rec.collection, rec.data, rec.status, rec.actor_id, rec.item_id) == (
            "workshop",
            {"title": "الف"},
            "x",
            "u1",
            7,
        )
        assert rec.created_at == NOW and rec.updated_at == NOW
        assert await store.get_record("workshop", rec.id) == rec
        assert await store.get_record("workshop", rec.id + 999) is None
        assert await store.get_record("other_collection", rec.id) is None


async def test_ids_increase_and_order_by(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        ids = [(await store.create_record("c", {"n": i}, now=NOW)).id for i in range(4)]
        assert ids == sorted(ids) and len(set(ids)) == 4
        assert [r.id for r in await store.list_records("c")] == ids
        assert [r.id for r in await store.list_records("c", order_by="id")] == ids
        assert [r.id for r in await store.list_records("c", order_by="-id")] == ids[::-1]
        assert [r.id for r in await store.list_records("c", limit=2)] == ids[:2]
        assert [r.id for r in await store.list_records("c", order_by="-id", limit=1)] == ids[-1:]
        with pytest.raises(ValueError):
            await store.list_records("c", order_by="created_at")


async def test_filters_and_count(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        a = await store.create_record("b", {}, status="confirmed", actor_id="ali", item_id=1, now=NOW)
        b = await store.create_record("b", {}, status="waitlisted", actor_id="sara", item_id=1, now=NOW)
        c = await store.create_record("b", {}, status="confirmed", actor_id="ali", item_id=2, now=NOW)
        d = await store.create_record("b", {}, status=None, actor_id=None, item_id=None, now=NOW)

        async def ids(**kw: object) -> list[int]:
            return [r.id for r in await store.list_records("b", **kw)]  # type: ignore[arg-type]

        assert await ids(status_in=["confirmed"]) == [a.id, c.id]
        assert await ids(status_in=["confirmed", "waitlisted"], item_id=1) == [a.id, b.id]
        assert await ids(actor_id="ali") == [a.id, c.id]
        assert await ids(actor_id="ali", item_id=2, status_in=["confirmed"]) == [c.id]
        assert await ids(status_in=[]) == []
        assert await store.count_records("b") == 4
        assert await store.count_records("b", status_in=["confirmed"]) == 2
        assert await store.count_records("b", item_id=1, status_in=["waitlisted"]) == 1
        assert await store.count_records("b", actor_id="nobody") == 0
        assert d.id in await ids()


async def test_update_merges_shallowly_and_uses_now(
    session_factory: SessionFactory, bot_id: uuid.UUID
) -> None:
    later = NOW + timedelta(hours=3)
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        rec = await store.create_record("c", {"a": 1, "b": {"x": 1}}, status="s1", now=NOW)
        upd = await store.update_record("c", rec.id, data={"b": {"y": 2}, "c": 3}, now=later)
        assert upd.data == {"a": 1, "b": {"y": 2}, "c": 3}  # shallow: nested dict replaced
        assert upd.status == "s1"  # untouched when not given
        assert upd.created_at == NOW and upd.updated_at == later
        upd = await store.update_record("c", rec.id, status="s2", now=later)
        assert upd.status == "s2" and upd.data == {"a": 1, "b": {"y": 2}, "c": 3}
        await session.commit()
    async with session_factory() as session:  # persisted, not just cached
        got = await PgStore(session, bot_id, "live").get_record("c", rec.id)
        assert got is not None and got.data["c"] == 3 and got.status == "s2" and got.updated_at == later


async def test_update_missing_raises_keyerror(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        with pytest.raises(KeyError):
            await store.update_record("c", 123456, data={"a": 1}, now=NOW)
        rec = await store.create_record("c", {}, now=NOW)
        with pytest.raises(KeyError):
            await store.update_record("other", rec.id, data={"a": 1}, now=NOW)


async def test_delete(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        rec = await store.create_record("c", {}, now=NOW)
        await store.delete_record("c", rec.id)
        assert await store.get_record("c", rec.id) is None
        assert await store.count_records("c") == 0
        await store.delete_record("c", rec.id)  # deleting twice is harmless


async def test_sessions(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        assert await store.get_session("ali") is None
        await store.set_session("ali", {"capability": "book", "step": 1, "vars": {"a": "b"}})
        assert await store.get_session("ali") == {"capability": "book", "step": 1, "vars": {"a": "b"}}
        await store.set_session("ali", {"capability": "book", "step": 2, "vars": {}})
        assert (await store.get_session("ali") or {})["step"] == 2
        assert await store.get_session("sara") is None
        await store.set_session("ali", None)
        assert await store.get_session("ali") is None
        await store.set_session("ali", None)  # deleting a missing session is harmless


async def test_upsert_user_and_owner(session_factory: SessionFactory, bot_id: uuid.UUID) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live", "12345")
        await store.upsert_user(Actor(id="12345", display_name="Ali"))
        await store.upsert_user(Actor(id="12345", display_name="Ali R"))  # idempotent
        assert await store.owner_actor_id() == "12345"
        assert await PgStore(session, bot_id, "live").owner_actor_id() is None
        assert await PgStore(session, bot_id, "sandbox", "owner").owner_actor_id() == "owner"


async def test_isolation_between_bots_and_envs(session_factory: SessionFactory, make_bot: MakeBot) -> None:
    bot_a, _ = await make_bot("alice", active=False)
    bot_b, _ = await make_bot("bob", active=False)
    async with session_factory() as session:
        a_live = PgStore(session, bot_a, "live")
        a_sandbox = PgStore(session, bot_a, "sandbox")
        b_live = PgStore(session, bot_b, "live")
        rec = await a_live.create_record("c", {"v": 1}, actor_id="ali", now=NOW)
        await a_live.set_session("ali", {"s": 1})

        for other in (a_sandbox, b_live):
            assert await other.get_record("c", rec.id) is None
            assert await other.list_records("c") == []
            assert await other.count_records("c") == 0
            assert await other.get_session("ali") is None
            with pytest.raises(KeyError):
                await other.update_record("c", rec.id, data={"v": 2}, now=NOW)
            await other.delete_record("c", rec.id)  # must not delete another store's record
        assert (await a_live.get_record("c", rec.id)) is not None
        assert (await a_live.get_record("c", rec.id)).data == {"v": 1}  # type: ignore[union-attr]
        assert await a_live.get_session("ali") == {"s": 1}


async def test_advisory_lock_is_stable_and_blocks_other_transactions(
    session_factory: SessionFactory, bot_id: uuid.UUID
) -> None:
    assert advisory_key(bot_id) == advisory_key(str(bot_id))
    assert advisory_key(bot_id) != advisory_key(uuid.uuid4())
    assert -(2**63) <= advisory_key(bot_id) < 2**63

    order: list[str] = []
    entered = asyncio.Event()

    async def first() -> None:
        async with session_factory() as s1:
            await advisory_lock(s1, bot_id)
            order.append("first-locked")
            entered.set()
            await asyncio.sleep(0.4)
            order.append("first-releasing")
            await s1.commit()

    async def second() -> None:
        await entered.wait()
        async with session_factory() as s2:
            await advisory_lock(s2, bot_id)
            order.append("second-locked")
            await s2.commit()

    await asyncio.gather(first(), second())
    assert order == ["first-locked", "first-releasing", "second-locked"]


async def test_bot_delete_cascades_records_and_sessions(
    session_factory: SessionFactory, bot_id: uuid.UUID
) -> None:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        await store.create_record("c", {}, now=datetime.now(UTC))
        await store.set_session("ali", {"s": 1})
        await session.commit()
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        await session.delete(bot)
        await session.commit()
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        assert await store.count_records("c") == 0
        assert await store.get_session("ali") is None
