"""Gate B groundwork: the golden and derived scenarios run on PgStore through the real runtime.

The same scenarios pass on MemoryStore in ``tests/golden/test_gate_a.py``; running them again with
``store_factory`` proves the two stores behave identically for the production workflows. Each
scenario gets a fresh bot (so records never leak between scenarios); nothing is committed.
Needs a database.
"""

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec
from app.db.models import Bot
from app.runtime.pg_store import PgStore
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario, ScenarioResult, TestReport
from tests.integration.helpers import REPO, SessionFactory, user_id

EXAMPLES = REPO / "examples"


@pytest.fixture
def spec() -> BotSpec:
    return BotSpec.model_validate(
        json.loads((EXAMPLES / "workshop.botspec.json").read_text(encoding="utf-8"))
    )


@pytest.fixture
def golden() -> list[Scenario]:
    raw = json.loads((EXAMPLES / "workshop.scenarios.json").read_text(encoding="utf-8"))
    return [Scenario.model_validate(s) for s in raw]


@pytest_asyncio.fixture
async def session(session_factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    owner_id = await user_id(session_factory, "alice")
    async with session_factory() as s:
        s.info["owner_id"] = owner_id
        yield s
        await s.rollback()


def pg_store_factory(session: AsyncSession) -> Callable[[], Awaitable[PgStore]]:
    async def make() -> PgStore:
        bot = Bot(owner_id=session.info["owner_id"], name="scenario")
        session.add(bot)
        await session.flush()
        return PgStore(session, bot.id, "sandbox", owner_actor_id="owner")

    return make


def failures(report: TestReport) -> dict[str, list[str]]:
    return {
        r.scenario_id: [s.message or "" for s in r.steps if not s.passed]
        for r in report.results
        if not r.passed
    }


def transcript(result: ScenarioResult) -> list[tuple[str, str, str, list[str]]]:
    """Transcript with record ids masked in what actors send (ids differ between the two stores)."""
    return [
        (e.actor, e.direction, re.sub(r"\d+", "#", e.text) if e.direction == "in" else e.text, e.buttons)
        for e in result.transcript
    ]


async def test_the_nine_golden_scenarios_pass_on_pgstore(
    spec: BotSpec, golden: list[Scenario], session: AsyncSession
) -> None:
    report = await run_scenarios(spec, golden, store_factory=pg_store_factory(session))
    assert failures(report) == {}
    assert (report.total, report.passed, report.failed) == (9, 9, 0)


async def test_derived_scenarios_pass_on_pgstore(spec: BotSpec, session: AsyncSession) -> None:
    derived = derive_scenarios(spec)
    assert derived
    report = await run_scenarios(spec, derived, store_factory=pg_store_factory(session))
    assert failures(report) == {}
    assert report.passed == report.total == len(derived)


async def test_both_stores_give_the_same_transcripts(
    spec: BotSpec, golden: list[Scenario], session: AsyncSession
) -> None:
    on_memory = await run_scenarios(spec, golden)
    on_pg = await run_scenarios(spec, golden, store_factory=pg_store_factory(session))
    assert [r.scenario_id for r in on_memory.results] == [r.scenario_id for r in on_pg.results]
    for memory, pg in zip(on_memory.results, on_pg.results, strict=True):
        assert transcript(memory) == transcript(pg), memory.scenario_id
        assert [s.narrative for s in memory.steps] == [s.narrative for s in pg.steps]


async def test_a_failing_scenario_is_still_reported_on_pgstore(
    spec: BotSpec, golden: list[Scenario], session: AsyncSession
) -> None:
    """The store factory does not weaken the runner: a broken spec fails the same scenarios."""
    broken = spec.model_copy(deep=True)
    for cap in broken.capabilities:
        if cap.type == "booking":
            cap.waitlist.enabled = False
    on_memory = await run_scenarios(broken, golden)
    on_pg = await run_scenarios(broken, golden, store_factory=pg_store_factory(session))
    assert on_memory.failed > 0
    assert {r.scenario_id for r in on_memory.results if not r.passed} == {
        r.scenario_id for r in on_pg.results if not r.passed
    }
