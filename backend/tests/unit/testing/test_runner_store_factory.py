"""The optional ``store_factory`` of the scenario runner (sync or async; default unchanged)."""

import json
from pathlib import Path

from app.botspec.models import BotSpec
from app.runtime.memory_store import MemoryStore
from app.runtime.store import Store
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario

EXAMPLES = Path(__file__).resolve().parents[4] / "examples"


def load() -> tuple[BotSpec, list[Scenario]]:
    spec = BotSpec.model_validate(
        json.loads((EXAMPLES / "workshop.botspec.json").read_text(encoding="utf-8"))
    )
    raw = json.loads((EXAMPLES / "workshop.scenarios.json").read_text(encoding="utf-8"))
    return spec, [Scenario.model_validate(s) for s in raw[:3]]


async def test_sync_factory_is_called_once_per_scenario() -> None:
    spec, scenarios = load()
    made: list[Store] = []

    def factory() -> Store:
        made.append(MemoryStore(owner_actor_id="owner"))
        return made[-1]

    report = await run_scenarios(spec, scenarios, store_factory=factory)
    assert report.passed == report.total == 3
    assert len(made) == 3 and len({id(s) for s in made}) == 3


async def test_async_factory_and_default_agree() -> None:
    spec, scenarios = load()

    async def factory() -> Store:
        return MemoryStore(owner_actor_id="owner")

    with_factory = await run_scenarios(spec, scenarios, store_factory=factory)
    default = await run_scenarios(spec, scenarios)
    assert [r.model_dump() for r in with_factory.results] == [r.model_dump() for r in default.results]


async def test_a_failing_factory_fails_the_scenario_instead_of_raising() -> None:
    spec, scenarios = load()

    def factory() -> Store:
        raise RuntimeError("no database")

    report = await run_scenarios(spec, scenarios, store_factory=factory)
    assert report.failed == 3 and report.passed == 0
    assert "no database" in (report.results[0].steps[0].message or "")
