import pytest

from app.runtime.memory_store import MemoryStore
from tests.unit.runtime.harness import T0
from tests.unit.runtime.store_contract import CONTRACT_CASES


async def _factory() -> MemoryStore:
    return MemoryStore()


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c.__name__)
async def test_store_contract(case) -> None:
    await case(_factory)


async def test_owner_actor_id_bound_at_construction() -> None:
    assert await MemoryStore().owner_actor_id() == "owner"
    assert await MemoryStore(owner_actor_id="12345").owner_actor_id() == "12345"
    assert await MemoryStore(owner_actor_id=None).owner_actor_id() is None


async def test_ids_start_at_one() -> None:
    s = MemoryStore()
    assert (await s.create_record("a", {}, now=T0)).id == 1
    assert (await s.create_record("b", {}, now=T0)).id == 2


async def test_rejects_unknown_order_and_non_json_data() -> None:
    s = MemoryStore()
    with pytest.raises(ValueError):
        await s.list_records("a", order_by="created_at")
    with pytest.raises(TypeError):
        await s.create_record("a", {"when": T0}, now=T0)
    with pytest.raises(TypeError):
        await s.set_session("ali", {"capability": "x", "step": "s", "vars": {"when": T0}})


async def test_upsert_user_keeps_latest() -> None:
    from app.runtime.contracts import Actor

    s = MemoryStore()
    await s.upsert_user(Actor(id="ali", display_name="a"))
    await s.upsert_user(Actor(id="ali", display_name="علی"))
    assert s.users["ali"].display_name == "علی"
