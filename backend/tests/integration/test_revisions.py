"""Revisions service: drafts, activation rules, rollback, sample data. Needs TEST_DATABASE_URL."""

import asyncio
import copy
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Bot, RecordRow, Revision
from app.revisions.service import (
    BotNotFound,
    InvalidRevisionState,
    InvalidSampleData,
    RevisionNotFound,
    StaleBase,
    TestsFailing,
    activate,
    create_draft,
    load_sample_data,
)
from app.runtime.pg_store import PgStore
from tests.integration.helpers import NOW, SessionFactory, user_id

PASSING = {
    "total": 1,
    "passed": 1,
    "failed": 0,
    "results": [{"scenario_id": "a", "passed": True}],
    "duration_ms": 1,
}
FAILING = {
    "total": 1,
    "passed": 0,
    "failed": 1,
    "results": [{"scenario_id": "a", "passed": False}],
    "duration_ms": 1,
}


async def new_bot(session_factory: SessionFactory, **fields: Any) -> uuid.UUID:
    owner_id = await user_id(session_factory, "alice")
    async with session_factory() as session:
        bot = Bot(owner_id=owner_id, name="b", **fields)
        session.add(bot)
        await session.commit()
        return bot.id


async def state(
    session_factory: SessionFactory, bot_id: uuid.UUID
) -> tuple[uuid.UUID | None, dict[int, str]]:
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        rows = (await session.execute(select(Revision).where(Revision.bot_id == bot_id))).scalars().all()
        assert bot is not None
        return bot.active_revision_id, {r.number: r.status for r in rows}


async def draft(
    session_factory: SessionFactory, bot_id: uuid.UUID, spec: dict[str, Any], **kw: Any
) -> uuid.UUID:
    async with session_factory() as session:
        revision = await create_draft(session, bot_id, spec=spec, **kw)
        await session.commit()
        return revision.id


async def do_activate(session_factory: SessionFactory, revision_id: uuid.UUID, **kw: Any) -> Revision:
    async with session_factory() as session:
        revision = await activate(session, revision_id, **kw)
        await session.commit()
        return revision


async def test_create_draft_numbers_per_bot(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_a = await new_bot(session_factory)
    bot_b = await new_bot(session_factory)
    async with session_factory() as session:
        r1 = await create_draft(session, bot_a, spec=golden_spec)
        r2 = await create_draft(
            session,
            bot_a,
            spec=golden_spec,
            requirements={"business_summary": "x"},
            patch=[{"op": "set", "path": ["bot", "name"], "value": "n"}],
            change_request="تغییر",
            scenarios=[{"id": "s"}],
            superseded=[{"id": "t", "reason": "r"}],
            test_report=PASSING,
            sample_data=[],
            parent_id=r1.id,
        )
        other = await create_draft(session, bot_b, spec=golden_spec)
        await session.commit()
    assert (r1.number, r2.number, other.number) == (1, 2, 1)
    assert r1.status == "draft" and r1.parent_id is None and r2.parent_id == r1.id
    async with session_factory() as session:
        stored = await session.get(Revision, r2.id)
        assert stored is not None
        assert stored.change_request == "تغییر"
        assert stored.test_report == PASSING
        assert stored.patch == [{"op": "set", "path": ["bot", "name"], "value": "n"}]
        assert stored.spec == golden_spec


async def test_create_draft_accepts_pydantic_models(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    from app.botspec.models import BotSpec

    bot_id = await new_bot(session_factory)
    async with session_factory() as session:
        revision = await create_draft(session, bot_id, spec=BotSpec.model_validate(golden_spec))
        await session.commit()
    assert revision.spec == BotSpec.model_validate(golden_spec).model_dump(mode="json")


async def test_create_draft_unknown_bot(session_factory: SessionFactory, golden_spec: dict[str, Any]) -> None:
    async with session_factory() as session:
        with pytest.raises(BotNotFound) as exc:
            await create_draft(session, uuid.uuid4(), spec=golden_spec)
    assert exc.value.code == "bot_not_found"


async def test_first_revision_activates_with_no_parent(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_id = await new_bot(session_factory)
    rev = await draft(session_factory, bot_id, golden_spec)
    activated = await do_activate(session_factory, rev)
    assert activated.status == "active" and activated.activated_at is not None
    active, statuses = await state(session_factory, bot_id)
    assert active == rev and statuses == {1: "active"}
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None and bot.status == "draft"  # no Telegram token connected yet


async def test_bot_with_token_goes_live_on_activation(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_id = await new_bot(session_factory, tg_token_enc="enc")
    await do_activate(session_factory, await draft(session_factory, bot_id, golden_spec))
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None and bot.status == "live"


FORM = {"capability": "book_workshop", "step": "form", "vars": {"field": "x", "answers": {}, "data": {}}}


async def live_sessions(session_factory: SessionFactory, bot_id: uuid.UUID, *actors: str) -> dict[str, Any]:
    async with session_factory() as session:
        store = PgStore(session, bot_id, "live")
        return {a: await store.get_session(a) for a in actors}


async def test_second_revision_supersedes_first_and_keeps_sessions_it_can_continue(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    """Activation deletes only the live sessions the new spec cannot continue: a form of a removed,
    disabled or retyped capability. A form of a capability that is still enabled survives (a
    capability toggle elsewhere must not break it), and so does an idle session."""
    bot_id = await new_bot(session_factory)
    r1 = await draft(session_factory, bot_id, golden_spec)
    await do_activate(session_factory, r1)
    async with session_factory() as session:
        live = PgStore(session, bot_id, "live")
        await live.set_session("ali", FORM)
        await live.set_session("sara", {**FORM, "capability": "gone"})
        await live.set_session("reza", {"s": 1})
        await live.set_session("mina", {**FORM, "capability": "info"})
        await PgStore(session, bot_id, "sandbox").set_session("ali", {"s": 2})
        await session.commit()

    without_info = {
        **golden_spec,
        "capabilities": [c for c in golden_spec["capabilities"] if c["key"] != "info"],
    }
    without_info["menu"] = [m for m in golden_spec["menu"] if m["capability"] != "info"]
    r2 = await draft(session_factory, bot_id, without_info, parent_id=r1)
    await do_activate(session_factory, r2)

    active, statuses = await state(session_factory, bot_id)
    assert active == r2 and statuses == {1: "superseded", 2: "active"}
    assert await live_sessions(session_factory, bot_id, "ali", "sara", "reza", "mina") == {
        "ali": FORM,  # still enabled: survives
        "sara": None,  # unknown capability
        "reza": {"s": 1},  # idle
        "mina": None,  # removed in r2
    }
    async with session_factory() as session:
        assert await PgStore(session, bot_id, "sandbox").get_session("ali") == {"s": 2}

    disabled = copy.deepcopy(without_info)
    next(c for c in disabled["capabilities"] if c["key"] == "book_workshop")["enabled"] = False
    r3 = await draft(session_factory, bot_id, disabled, parent_id=r2)
    await do_activate(session_factory, r3)
    assert await live_sessions(session_factory, bot_id, "ali", "reza") == {"ali": None, "reza": {"s": 1}}


async def test_activation_drops_sessions_of_a_retyped_capability(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_id = await new_bot(session_factory)
    r1 = await draft(session_factory, bot_id, golden_spec)
    await do_activate(session_factory, r1)
    async with session_factory() as session:
        await PgStore(session, bot_id, "live").set_session("ali", {**FORM, "capability": "info"})
        await session.commit()
    retyped = copy.deepcopy(golden_spec)
    info = next(c for c in retyped["capabilities"] if c["key"] == "info")
    retyped["capabilities"].remove(info)
    retyped["capabilities"].append(
        {
            "type": "catalog",
            "key": "info",
            "title": "فهرست",
            "resource": "workshop",
            "detail_fields": ["title"],
        }
    )
    r2 = await draft(session_factory, bot_id, retyped, parent_id=r1)
    await do_activate(session_factory, r2)
    assert await live_sessions(session_factory, bot_id, "ali") == {"ali": None}


async def test_stale_base_is_refused(session_factory: SessionFactory, golden_spec: dict[str, Any]) -> None:
    bot_id = await new_bot(session_factory)
    r1 = await draft(session_factory, bot_id, golden_spec)
    await do_activate(session_factory, r1)
    stale_no_parent = await draft(session_factory, bot_id, golden_spec, parent_id=None)
    r2 = await draft(session_factory, bot_id, golden_spec, parent_id=r1)
    stale_old_parent = await draft(session_factory, bot_id, golden_spec, parent_id=r1)
    await do_activate(session_factory, r2)

    for stale in (stale_no_parent, stale_old_parent):
        with pytest.raises(StaleBase) as exc:
            await do_activate(session_factory, stale)
        assert exc.value.code == "stale_base"
        assert exc.value.message  # Persian text for the owner
    active, statuses = await state(session_factory, bot_id)
    assert active == r2 and statuses == {1: "superseded", 2: "draft", 3: "active", 4: "draft"}


async def test_failing_tests_block_activation(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_id = await new_bot(session_factory)
    bad = await draft(session_factory, bot_id, golden_spec, test_report=FAILING)
    with pytest.raises(TestsFailing) as exc:
        await do_activate(session_factory, bad)
    assert exc.value.code == "tests_failing"
    assert await state(session_factory, bot_id) == (None, {1: "draft"})

    only_in_results = {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "results": [{"scenario_id": "a", "passed": False}],
    }
    sneaky = await draft(session_factory, bot_id, golden_spec, test_report=only_in_results)
    with pytest.raises(TestsFailing):
        await do_activate(session_factory, sneaky)

    good = await draft(session_factory, bot_id, golden_spec, test_report=PASSING)
    await do_activate(session_factory, good)
    assert (await state(session_factory, bot_id))[0] == good


async def test_rollback(session_factory: SessionFactory, golden_spec: dict[str, Any]) -> None:
    bot_id = await new_bot(session_factory)
    r1 = await draft(session_factory, bot_id, golden_spec)
    await do_activate(session_factory, r1)
    r2 = await draft(session_factory, bot_id, golden_spec, parent_id=r1)
    await do_activate(session_factory, r2)
    # a draft based on r2, written before the rollback
    r3 = await draft(session_factory, bot_id, golden_spec, parent_id=r2)

    # rolling back needs rollback=True; a plain activation of a superseded revision is refused
    with pytest.raises(InvalidRevisionState):
        await do_activate(session_factory, r1)
    async with session_factory() as session:
        await PgStore(session, bot_id, "live").set_session("ali", {**FORM, "capability": "gone"})
        await PgStore(session, bot_id, "live").set_session("sara", FORM)
        await session.commit()

    rolled = await do_activate(session_factory, r1, rollback=True)
    assert rolled.status == "active"
    active, statuses = await state(session_factory, bot_id)
    assert active == r1 and statuses == {1: "active", 2: "superseded", 3: "draft"}  # no new revision
    assert await live_sessions(session_factory, bot_id, "ali", "sara") == {"ali": None, "sara": FORM}

    with pytest.raises(StaleBase):  # r3 was based on r2, which is no longer active
        await do_activate(session_factory, r3)

    with pytest.raises(InvalidRevisionState):  # rollback of a draft / of the active revision
        await do_activate(session_factory, r3, rollback=True)
    with pytest.raises(InvalidRevisionState):
        await do_activate(session_factory, r1, rollback=True)

    await do_activate(session_factory, r2, rollback=True)  # roll forward again
    assert await state(session_factory, bot_id) == (r2, {1: "superseded", 2: "active", 3: "draft"})


async def test_activate_unknown_revision(session_factory: SessionFactory) -> None:
    with pytest.raises(RevisionNotFound) as exc:
        await do_activate(session_factory, uuid.uuid4())
    assert exc.value.code == "revision_not_found"


async def test_concurrent_activations_of_siblings_allow_exactly_one(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_id = await new_bot(session_factory)
    r1 = await draft(session_factory, bot_id, golden_spec)
    await do_activate(session_factory, r1)
    a = await draft(session_factory, bot_id, golden_spec, parent_id=r1)
    b = await draft(session_factory, bot_id, golden_spec, parent_id=r1)

    results = await asyncio.gather(
        do_activate(session_factory, a), do_activate(session_factory, b), return_exceptions=True
    )
    assert sum(isinstance(r, Revision) for r in results) == 1
    assert sum(isinstance(r, StaleBase) for r in results) == 1
    active, statuses = await state(session_factory, bot_id)
    assert active in (a, b)
    assert sorted(statuses.values()) == ["active", "draft", "superseded"]


SAMPLE = [
    {
        "ref": "w1",
        "collection": "workshop",
        "values": [
            {"key": "title", "value": "کارگاه عکاسی"},
            {"key": "description", "value": "مقدماتی"},
            {"key": "teacher", "value": "سارا"},
            {"key": "starts_at", "value": "+48h"},
            {"key": "price", "value": "۱۲۰۰۰۰"},
        ],
    },
    {
        "ref": "w2",
        "collection": "workshop",
        "values": [
            {"key": "title", "value": "کارگاه سفال"},
            {"key": "description", "value": "ویژه"},
            {"key": "teacher", "value": "علی"},
            {"key": "starts_at", "value": "-1h"},
        ],
    },
]


async def test_load_sample_data(session_factory: SessionFactory, golden_spec: dict[str, Any]) -> None:
    bot_id = await new_bot(session_factory)
    other_bot = await new_bot(session_factory)
    rev_id = await draft(session_factory, bot_id, golden_spec, sample_data=SAMPLE)
    async with session_factory() as session:
        sandbox = PgStore(session, bot_id, "sandbox")
        live = PgStore(session, bot_id, "live")
        stale = await sandbox.create_record("workshop", {"title": "قدیمی"}, now=NOW)
        await sandbox.set_session("ali", {"s": 1})
        await live.create_record("workshop", {"title": "زنده"}, now=NOW)
        await live.set_session("ali", {"s": 2})
        await PgStore(session, other_bot, "sandbox").create_record("workshop", {"title": "دیگری"}, now=NOW)
        await session.commit()

    async with session_factory() as session:
        revision = await session.get(Revision, rev_id)
        assert revision is not None
        created = await load_sample_data(session, bot_id, revision, NOW)
        await session.commit()
    assert len(created) == 2

    async with session_factory() as session:
        sandbox = PgStore(session, bot_id, "sandbox")
        records = await sandbox.list_records("workshop")
        assert [r.data["title"] for r in records] == ["کارگاه عکاسی", "کارگاه سفال"]
        assert stale.id not in [r.id for r in records]
        assert records[0].data["starts_at"] == "2026-10-07T12:00:00+00:00"  # now + 48h
        assert records[1].data["starts_at"] == "2026-10-05T11:00:00+00:00"  # now - 1h
        assert records[0].data["price"] == 120000 and records[1].data["price"] is None
        assert records[0].created_at == NOW
        assert await sandbox.get_session("ali") is None
        live = PgStore(session, bot_id, "live")  # live data and sessions are never touched
        assert [r.data["title"] for r in await live.list_records("workshop")] == ["زنده"]
        assert await live.get_session("ali") == {"s": 2}
        other = PgStore(session, other_bot, "sandbox")
        assert await other.count_records("workshop") == 1

    # loading again replaces, not appends
    async with session_factory() as session:
        revision = await session.get(Revision, rev_id)
        assert revision is not None
        await load_sample_data(session, bot_id, revision, NOW)
        await session.commit()
    async with session_factory() as session:
        assert await PgStore(session, bot_id, "sandbox").count_records("workshop") == 2


async def test_load_sample_data_rejects_invalid_values_without_touching_the_sandbox(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bot_id = await new_bot(session_factory)
    bad = [{"ref": "w", "collection": "workshop", "values": [{"key": "title", "value": "فقط عنوان"}]}]
    unknown = [{"ref": "w", "collection": "nope", "values": []}]
    async with session_factory() as session:
        await PgStore(session, bot_id, "sandbox").create_record("workshop", {"title": "قبلی"}, now=NOW)
        await session.commit()
    for sample in (bad, unknown):
        rev_id = await draft(session_factory, bot_id, golden_spec, sample_data=sample)
        async with session_factory() as session:
            revision = await session.get(Revision, rev_id)
            assert revision is not None
            with pytest.raises(InvalidSampleData) as exc:
                await load_sample_data(session, bot_id, revision, NOW)
            assert exc.value.code == "invalid_sample_data"
            await session.rollback()
    async with session_factory() as session:
        count = len(
            (await session.execute(select(RecordRow).where(RecordRow.bot_id == bot_id))).scalars().all()
        )
        assert count == 1
