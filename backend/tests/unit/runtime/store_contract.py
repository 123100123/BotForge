"""Reusable Store-protocol contract suite (WP1). Not collected by pytest on its own.

Every case is ``async def case(make_store) -> None`` where ``make_store`` is an async factory
returning a fresh, empty store bound to its own ``(bot_id, env)``. Apply it like::

    from tests.unit.runtime.store_contract import CONTRACT_CASES

    @pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c.__name__)
    async def test_store_contract(case):
        await case(my_async_factory)

Rules covered (runtime/store.py docstring plus the WP0 notes): increasing positive ids unique per
store and shared across collections; filters (status_in, actor_id, item_id) and their combination;
order_by "id"/"-id" and limit; count_records; get_record by collection; timestamps from ``now``;
shallow data merge and status replacement on update; KeyError for a missing record; delete
(idempotent); sessions per actor with delete via None; upsert_user idempotent; owner_actor_id
stable; isolation between two stores.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from app.runtime.contracts import Actor
from app.runtime.store import Store

StoreFactory = Callable[[], Awaitable[Store]]

T0 = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)


def _same_instant(a: datetime, b: datetime) -> bool:
    return a.astimezone(UTC) == b.astimezone(UTC)


async def case_create_and_get(make_store: StoreFactory) -> None:
    s = await make_store()
    rec = await s.create_record(
        "workshop", {"title": "پایتون", "price": 100}, status="open", actor_id="ali", item_id=None, now=T0
    )
    assert rec.id > 0
    assert rec.collection == "workshop"
    assert rec.data == {"title": "پایتون", "price": 100}
    assert rec.status == "open" and rec.actor_id == "ali" and rec.item_id is None
    assert _same_instant(rec.created_at, T0) and _same_instant(rec.updated_at, T0)
    got = await s.get_record("workshop", rec.id)
    assert got is not None and got.id == rec.id and got.data == rec.data
    assert got.status == "open" and got.actor_id == "ali"
    assert _same_instant(got.created_at, T0)


async def case_get_missing_or_other_collection(make_store: StoreFactory) -> None:
    s = await make_store()
    rec = await s.create_record("workshop", {"title": "a"}, now=T0)
    assert await s.get_record("workshop", rec.id + 1000) is None
    assert await s.get_record("book_workshop", rec.id) is None


async def case_ids_increase_across_collections(make_store: StoreFactory) -> None:
    s = await make_store()
    ids = []
    for i, coll in enumerate(["workshop", "book_workshop", "workshop", "repair"]):
        ids.append((await s.create_record(coll, {"n": i}, now=T0)).id)
    assert all(i > 0 for i in ids)
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


async def case_list_filters(make_store: StoreFactory) -> None:
    s = await make_store()
    w1 = await s.create_record("workshop", {"t": 1}, now=T0)
    w2 = await s.create_record("workshop", {"t": 2}, now=T0)
    b1 = await s.create_record("bk", {}, status="confirmed", actor_id="ali", item_id=w1.id, now=T0)
    b2 = await s.create_record("bk", {}, status="waitlisted", actor_id="sara", item_id=w1.id, now=T0)
    b3 = await s.create_record("bk", {}, status="cancelled", actor_id="ali", item_id=w2.id, now=T0)
    b4 = await s.create_record("bk", {}, status="confirmed", actor_id="sara", item_id=w2.id, now=T0)

    def ids(rows: list) -> list[int]:
        return [r.id for r in rows]

    assert ids(await s.list_records("workshop")) == [w1.id, w2.id]
    assert ids(await s.list_records("bk")) == [b1.id, b2.id, b3.id, b4.id]
    assert ids(await s.list_records("bk", status_in=["confirmed"])) == [b1.id, b4.id]
    assert ids(await s.list_records("bk", status_in=["confirmed", "waitlisted"])) == [b1.id, b2.id, b4.id]
    assert ids(await s.list_records("bk", status_in=[])) == []
    assert ids(await s.list_records("bk", actor_id="ali")) == [b1.id, b3.id]
    assert ids(await s.list_records("bk", item_id=w2.id)) == [b3.id, b4.id]
    assert ids(
        await s.list_records("bk", status_in=["confirmed", "waitlisted"], actor_id="sara", item_id=w1.id)
    ) == [b2.id]
    assert await s.list_records("nothing_here") == []


async def case_list_order_and_limit(make_store: StoreFactory) -> None:
    s = await make_store()
    made = [(await s.create_record("c", {"i": i}, status="w", now=T0)).id for i in range(5)]
    assert [r.id for r in await s.list_records("c")] == made
    assert [r.id for r in await s.list_records("c", order_by="id")] == made
    assert [r.id for r in await s.list_records("c", order_by="-id")] == list(reversed(made))
    assert [r.id for r in await s.list_records("c", limit=2)] == made[:2]
    assert [r.id for r in await s.list_records("c", order_by="-id", limit=2)] == [made[4], made[3]]
    assert [r.id for r in await s.list_records("c", status_in=["w"], order_by="id", limit=1)] == made[:1]


async def case_count(make_store: StoreFactory) -> None:
    s = await make_store()
    await s.create_record("bk", {}, status="confirmed", actor_id="ali", item_id=1, now=T0)
    await s.create_record("bk", {}, status="confirmed", actor_id="sara", item_id=1, now=T0)
    await s.create_record("bk", {}, status="waitlisted", actor_id="ali", item_id=2, now=T0)
    await s.create_record("other", {}, status="confirmed", now=T0)
    assert await s.count_records("bk") == 3
    assert await s.count_records("bk", status_in=["confirmed"]) == 2
    assert await s.count_records("bk", status_in=["confirmed"], item_id=1) == 2
    assert await s.count_records("bk", actor_id="ali") == 2
    assert await s.count_records("bk", actor_id="ali", item_id=2, status_in=["waitlisted"]) == 1
    assert await s.count_records("bk", status_in=[]) == 0
    assert await s.count_records("missing") == 0


async def case_update_merges_and_sets_status(make_store: StoreFactory) -> None:
    s = await make_store()
    rec = await s.create_record("bk", {"a": 1, "b": {"x": 1}}, status="confirmed", actor_id="ali", now=T0)
    up = await s.update_record("bk", rec.id, data={"b": {"y": 2}, "c": 3}, now=T1)
    assert up.data == {"a": 1, "b": {"y": 2}, "c": 3}  # shallow: "b" replaced, not deep-merged
    assert up.status == "confirmed"  # status untouched when not given
    assert _same_instant(up.created_at, T0) and _same_instant(up.updated_at, T1)
    assert up.actor_id == "ali"
    up2 = await s.update_record("bk", rec.id, status="cancelled", now=T1 + timedelta(minutes=5))
    assert up2.status == "cancelled" and up2.data == up.data
    got = await s.get_record("bk", rec.id)
    assert got is not None and got.status == "cancelled" and got.data == {"a": 1, "b": {"y": 2}, "c": 3}
    assert _same_instant(got.updated_at, T1 + timedelta(minutes=5))


async def case_update_missing_raises_key_error(make_store: StoreFactory) -> None:
    s = await make_store()
    rec = await s.create_record("bk", {}, now=T0)
    for coll, rid in (("bk", rec.id + 1000), ("other", rec.id)):
        try:
            await s.update_record(coll, rid, status="x", now=T1)
        except KeyError:
            pass
        else:  # pragma: no cover - failure path
            raise AssertionError(f"update_record({coll!r}, {rid}) must raise KeyError")


async def case_returned_records_are_detached(make_store: StoreFactory) -> None:
    s = await make_store()
    rec = await s.create_record("c", {"list": [1]}, now=T0)
    rec.data["list"].append(2)
    rec.data["new"] = True
    got = await s.get_record("c", rec.id)
    assert got is not None and got.data == {"list": [1]}


async def case_delete(make_store: StoreFactory) -> None:
    s = await make_store()
    a = await s.create_record("c", {}, now=T0)
    b = await s.create_record("c", {}, now=T0)
    await s.delete_record("other", a.id)  # wrong collection: nothing happens
    assert await s.get_record("c", a.id) is not None
    await s.delete_record("c", a.id)
    assert await s.get_record("c", a.id) is None
    assert [r.id for r in await s.list_records("c")] == [b.id]
    await s.delete_record("c", a.id)  # idempotent
    c = await s.create_record("c", {}, now=T0)
    assert c.id > b.id  # ids are never reused


async def case_sessions(make_store: StoreFactory) -> None:
    s = await make_store()
    assert await s.get_session("ali") is None
    state = {"capability": "book_workshop", "step": "form", "vars": {"answers": {"n": 1}, "data": {}}}
    await s.set_session("ali", state)
    assert await s.get_session("ali") == state
    assert await s.get_session("sara") is None
    await s.set_session("ali", {"capability": "x", "step": "s", "vars": {}})
    assert await s.get_session("ali") == {"capability": "x", "step": "s", "vars": {}}
    await s.set_session("ali", None)
    assert await s.get_session("ali") is None
    await s.set_session("ali", None)  # deleting a missing session is fine


async def case_upsert_user(make_store: StoreFactory) -> None:
    s = await make_store()
    await s.upsert_user(Actor(id="ali", display_name="علی"))
    await s.upsert_user(Actor(id="ali", display_name="علی رضایی"))
    await s.upsert_user(Actor(id="owner", display_name="مدیر", is_owner=True))


async def case_owner_actor_id_stable(make_store: StoreFactory) -> None:
    s = await make_store()
    first = await s.owner_actor_id()
    assert first is None or isinstance(first, str)
    assert await s.owner_actor_id() == first


async def case_stores_are_isolated(make_store: StoreFactory) -> None:
    a = await make_store()
    b = await make_store()
    rec = await a.create_record("c", {"v": 1}, now=T0)
    await a.set_session("ali", {"capability": "c", "step": "s", "vars": {}})
    assert await b.list_records("c") == []
    assert await b.count_records("c") == 0
    assert await b.get_session("ali") is None
    assert (await b.get_record("c", rec.id)) is None


CONTRACT_CASES: list[Callable[[StoreFactory], Awaitable[None]]] = [
    case_create_and_get,
    case_get_missing_or_other_collection,
    case_ids_increase_across_collections,
    case_list_filters,
    case_list_order_and_limit,
    case_count,
    case_update_merges_and_sets_status,
    case_update_missing_raises_key_error,
    case_returned_records_are_detached,
    case_delete,
    case_sessions,
    case_upsert_user,
    case_owner_actor_id_stable,
    case_stores_are_isolated,
]
