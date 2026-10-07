"""scripts/load_spec.py: the revision is active and carries sample data loaded into the sandbox."""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.db.models import Bot, Revision
from app.runtime.pg_store import PgStore
from tests.integration.helpers import BACKEND, REPO, SessionFactory

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
SPEC_PATH = REPO / "examples" / "workshop.botspec.json"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("load_spec_script", BACKEND / "scripts" / "load_spec.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load_spec = _load_script()


def test_default_sample_data_comes_from_the_scenarios_file_beside_the_spec() -> None:
    path = load_spec.default_sample_data_path(SPEC_PATH)
    assert path == REPO / "examples" / "workshop.scenarios.json"
    assert load_spec.default_sample_data_path(REPO / "examples" / "repair.botspec.json") is None

    seeds = load_spec.read_sample_data(path)
    # every scenario seeds the same workshop: it is kept once
    assert len(seeds) == 1 and seeds[0].collection == "workshop" and seeds[0].ref == "s1"


def test_sample_data_file_may_be_a_plain_list_of_seed_records(tmp_path: Path) -> None:
    record = {"ref": "x", "collection": "workshop", "values": [{"key": "title", "value": "الف"}]}
    other = {"ref": "x", "collection": "workshop", "values": [{"key": "title", "value": "ب"}]}
    path = tmp_path / "sample.json"
    path.write_text(json.dumps([record, record, other], ensure_ascii=False), encoding="utf-8")
    seeds = load_spec.read_sample_data(path)
    assert [s.ref for s in seeds] == ["s1", "s2"]

    path.write_text(json.dumps([{"collection": "workshop"}]), encoding="utf-8")
    with pytest.raises(load_spec.LoadError):
        load_spec.read_sample_data(path)


async def _load(session_factory: SessionFactory, data: dict[str, Any], seeds: list[Any], **kw: Any) -> Any:
    async with session_factory() as session:
        result = await load_spec.load_into(
            session,
            data,
            owner_id=kw.pop("owner_id", "alice"),
            bot_id=kw.pop("bot_id", None),
            name=None,
            change_request="loaded from test",
            sample_data=seeds,
            now=NOW,
        )
        await session.commit()
        return result


async def test_loaded_revision_stores_sample_data_and_fills_only_the_sandbox(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    seeds = load_spec.read_sample_data(load_spec.default_sample_data_path(SPEC_PATH))
    result = await _load(session_factory, golden_spec, seeds)
    assert result.sample_records == 1

    async with session_factory() as session:
        bot = await session.get(Bot, result.bot_id)
        revision = await session.get(Revision, result.revision_id)
        assert bot is not None and revision is not None
        assert bot.active_revision_id == revision.id and revision.status == "active"
        assert [s["collection"] for s in revision.sample_data or []] == ["workshop"]
        sandbox = await PgStore(session, bot.id, "sandbox").list_records("workshop")
        assert len(sandbox) == 1 and sandbox[0].data["title"] == "کارگاه عکاسی"
        assert datetime.fromisoformat(sandbox[0].data["starts_at"]) > NOW  # "+48h" resolved
        assert await PgStore(session, bot.id, "live").count_records("workshop") == 0

    # loading a new revision onto the same bot replaces the sandbox data, it does not add to it
    again = await _load(session_factory, golden_spec, seeds, bot_id=result.bot_id)
    assert again.number == 2
    async with session_factory() as session:
        assert await PgStore(session, result.bot_id, "sandbox").count_records("workshop") == 1


async def test_sample_data_that_does_not_fit_the_spec_is_refused(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    bad = load_spec.SeedRecord.model_validate(
        {"ref": "s1", "collection": "no_such_resource", "values": [{"key": "title", "value": "x"}]}
    )
    with pytest.raises(load_spec.LoadError, match="sample data"):
        await _load(session_factory, golden_spec, [bad])


async def test_another_owners_bot_is_refused(
    session_factory: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    first = await _load(session_factory, golden_spec, [])
    with pytest.raises(load_spec.LoadError, match="bot not found"):
        await _load(session_factory, golden_spec, [], bot_id=first.bot_id, owner_id="bob")
