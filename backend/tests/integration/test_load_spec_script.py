"""scripts/load_spec.py: loads a spec as the active revision and, with --sample-data, fills the sandbox."""

import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import select

from app.db.models import Bot, RecordRow, Revision
from tests.integration.helpers import BACKEND, REPO, SessionFactory

SPEC = REPO / "examples" / "workshop.botspec.json"
SAMPLE = BACKEND / "scripts" / "workshop.sample_data.json"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("load_spec_script", BACKEND / "scripts" / "load_spec.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


@pytest.fixture(autouse=True)
def use_test_database(monkeypatch: pytest.MonkeyPatch, session_factory: SessionFactory) -> None:
    async def no_dispose() -> None:
        return None

    monkeypatch.setattr(script, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(script, "dispose_engine", no_dispose)


async def _records(session_factory: SessionFactory, bot_id: uuid.UUID, env: str) -> list[RecordRow]:
    async with session_factory() as session:
        rows = await session.execute(
            select(RecordRow).where(RecordRow.bot_id == bot_id, RecordRow.env == env)
        )
        return list(rows.scalars())


async def _only_bot(session_factory: SessionFactory, owner: str) -> Bot:
    async with session_factory() as session:
        return (await session.execute(select(Bot).where(Bot.owner_id == owner))).scalar_one()


async def test_sample_data_is_stored_and_loaded_into_the_sandbox_only(
    session_factory: SessionFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await script.load_spec(SPEC, "load-spec-sample", None, None, SAMPLE)
    assert code == 0
    assert "3 sample records loaded" in capsys.readouterr().out

    bot = await _only_bot(session_factory, "load-spec-sample")
    sandbox = await _records(session_factory, bot.id, "sandbox")
    assert {r.collection for r in sandbox} == {"workshop"} and len(sandbox) == 3
    assert {r.data["title"] for r in sandbox} >= {"کارگاه عکاسی"}
    assert all(r.data["starts_at"] > "2026" for r in sandbox)  # relative "+48h" resolved to a datetime
    assert await _records(session_factory, bot.id, "live") == []  # never copied to live

    async with session_factory() as session:
        revision = await session.get(Revision, bot.active_revision_id)
        assert revision is not None and revision.status == "active"
        assert [s["ref"] for s in revision.sample_data or []] == ["w1", "w2", "w3"]


async def test_without_sample_data_the_script_behaves_as_before(session_factory: SessionFactory) -> None:
    assert await script.load_spec(SPEC, "load-spec-plain", None, None) == 0
    bot = await _only_bot(session_factory, "load-spec-plain")
    assert bot.active_revision_id is not None
    assert await _records(session_factory, bot.id, "sandbox") == []
    async with session_factory() as session:
        revision = await session.get(Revision, bot.active_revision_id)
        assert revision is not None and revision.sample_data is None


async def test_invalid_sample_data_loads_nothing(
    session_factory: SessionFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed = {"ref": "x", "collection": "nope", "values": [{"key": "title", "value": "x"}]}
    unknown_resource = tmp_path / "unknown.json"
    unknown_resource.write_text(json.dumps([seed]), encoding="utf-8")
    not_a_list = tmp_path / "bad.json"
    not_a_list.write_text('{"ref": "x"}', encoding="utf-8")

    assert await script.load_spec(SPEC, "load-spec-bad", None, None, unknown_resource) == 1
    assert await script.load_spec(SPEC, "load-spec-bad", None, None, not_a_list) == 1
    err = capsys.readouterr().err
    assert "invalid sample data" in err and "not a list of SeedRecord" in err
    async with session_factory() as session:
        bots = (await session.execute(select(Bot).where(Bot.owner_id == "load-spec-bad"))).scalars().all()
    assert bots == []  # the failed run left no bot behind
