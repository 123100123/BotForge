"""Gate A: the hand-written golden spec passes every golden scenario and every derived scenario,
through ``BotRuntime`` on ``MemoryStore``; negative controls prove the tests have teeth; the two
golden modifications behave as the roadmap says; the repair example does not crash the tooling."""

import json
from pathlib import Path

import pytest

from app.botspec.models import BotSpec
from app.botspec.patch import PatchOp, apply_patch
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario, TestReport

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
CAP = "book_workshop"
GOLDEN_IDS = [
    "golden_basic_book",
    "golden_capacity_10_real",
    "golden_capacity_waitlist",
    "golden_duplicate_rejected",
    "golden_cancel_frees_seat",
    "golden_promotion_order",
    "golden_waitlisted_cancel_no_promotion",
    "golden_promotion_notifies",
    "golden_owner_cancel_promotes",
]


def load_spec(name: str = "workshop.botspec.json") -> BotSpec:
    return BotSpec.model_validate(json.loads((EXAMPLES / name).read_text(encoding="utf-8")))


def load_golden() -> list[Scenario]:
    raw = json.loads((EXAMPLES / "workshop.scenarios.json").read_text(encoding="utf-8"))
    return [Scenario.model_validate(s) for s in raw]


def patch(*ops: tuple[str, list[str], object]) -> BotSpec:
    return apply_patch(load_spec(), [PatchOp(op=o, path=p, value=v) for o, p, v in ops])  # type: ignore[arg-type]


def failed(report: TestReport) -> dict[str, tuple[int | None, str]]:
    return {
        r.scenario_id: (r.failed_step, next((s.message or "" for s in r.steps if not s.passed), ""))
        for r in report.results
        if not r.passed
    }


# --- (1) the golden spec ---------------------------------------------------------------------------


async def test_golden_scenarios_file_has_the_nine() -> None:
    assert [s.id for s in load_golden()] == GOLDEN_IDS


async def test_golden_spec_passes_all_nine_and_every_derived_scenario() -> None:
    spec = load_spec()
    golden, derived = load_golden(), derive_scenarios(spec)
    assert derived
    report = await run_scenarios(spec, [*golden, *derived])
    assert report.total == len(golden) + len(derived)
    assert failed(report) == {}
    assert (report.passed, report.failed) == (report.total, 0)
    for result in report.results:
        assert all(s.narrative.strip() for s in result.steps)


# --- (2) negative controls: the tests have teeth --------------------------------------------------


async def test_waitlist_disabled_breaks_the_waitlist_and_promotion_scenarios() -> None:
    spec = patch(("set", ["capabilities", CAP, "waitlist", "enabled"], False))
    report = await run_scenarios(spec, load_golden())
    bad = failed(report)
    expected_step = {
        "golden_capacity_10_real": 10,  # the 11th person is refused instead of waitlisted
        "golden_capacity_waitlist": 2,
        "golden_promotion_order": 2,
        "golden_waitlisted_cancel_no_promotion": 2,
        "golden_promotion_notifies": 2,
        "golden_owner_cancel_promotes": 2,
    }
    assert {k: v[0] for k, v in bad.items()} == expected_step
    for _, (_, message) in bad.items():
        assert "waitlisted" in message
        assert "capacity_full" in message
    passing = {r.scenario_id for r in report.results if r.passed}
    assert passing == {"golden_basic_book", "golden_duplicate_rejected", "golden_cancel_frees_seat"}


async def test_cancellation_disabled_breaks_the_cancel_scenarios() -> None:
    spec = patch(("set", ["capabilities", CAP, "cancellation", "enabled"], False))
    report = await run_scenarios(spec, load_golden())
    bad = failed(report)
    assert {k: v[0] for k, v in bad.items()} == {
        "golden_cancel_frees_seat": 2,
        "golden_promotion_order": 4,
        "golden_waitlisted_cancel_no_promotion": 4,
        "golden_promotion_notifies": 3,
    }
    for _, (_, message) in bad.items():
        assert "cancellation_disabled" in message
        assert "cancelled" in message
    # the owner cancels regardless of the user-facing cancellation switch
    assert "golden_owner_cancel_promotes" not in bad


async def test_derived_scenarios_also_have_teeth() -> None:
    spec = load_spec()
    broken = patch(("set", ["capabilities", CAP, "waitlist", "auto_promote"], False))
    report = await run_scenarios(broken, derive_scenarios(spec))  # derived from the unbroken spec
    assert {"derived:book_workshop:promotion_order", "derived:book_workshop:owner_cancel_promotes"} <= set(
        failed(report)
    )


# --- (3) the golden modifications ---------------------------------------------------------------------


async def test_capacity_12_fails_exactly_the_real_capacity_scenario() -> None:
    spec = patch(("set", ["capabilities", CAP, "capacity", "value"], 12))
    report = await run_scenarios(spec, load_golden())
    bad = failed(report)
    assert list(bad) == ["golden_capacity_10_real"]
    step, message = bad["golden_capacity_10_real"]
    assert step == 10
    assert "waitlisted" in message
    assert "confirmed" in message

    derived = derive_scenarios(spec)
    configured = next(s for s in derived if s.id == f"derived:{CAP}:configured_capacity")
    assert len({st.actor for st in configured.steps if st.do == "book"}) == 13
    derived_report = await run_scenarios(spec, derived)
    assert failed(derived_report) == {}


async def test_cancellation_deadline_2_keeps_all_nine_and_adds_deadline_scenarios() -> None:
    spec = patch(("set", ["capabilities", CAP, "cancellation", "deadline_hours"], 2))
    golden_report = await run_scenarios(spec, load_golden())
    assert failed(golden_report) == {}
    assert golden_report.passed == 9

    baseline = {s.id for s in derive_scenarios(load_spec())}
    derived = derive_scenarios(spec)
    added = {s.id for s in derived} - baseline
    assert added == {f"derived:{CAP}:cancel_deadline"}
    report = await run_scenarios(spec, derived)
    assert failed(report) == {}
    deadline = next(r for r in report.results if r.scenario_id.endswith(":cancel_deadline"))
    assert deadline.passed
    assert any("گذشتن مهلت لغو" in s.narrative for s in deadline.steps)


# --- (4) the request-only example does not crash the tooling ---------------------------------------


async def test_repair_example_does_not_crash() -> None:
    spec = load_spec("repair.botspec.json")
    derived = derive_scenarios(spec)
    report = await run_scenarios(spec, derived)
    assert report.total == len(derived)
    assert failed(report) == {}

    request_step = Scenario.model_validate(
        {
            "id": "acc",
            "title": "ثبت درخواست",
            "source": "acceptance",
            "steps": [
                {
                    "do": "submit_request",
                    "actor": "ali",
                    "capability": "repair",
                    "form": [
                        {"key": "device", "value": "یخچال"},
                        {"key": "problem", "value": "صدا می‌دهد"},
                        {"key": "phone", "value": "09120000000"},
                        {"key": "address", "value": "تهران"},
                    ],
                    "expect": "submitted",
                },
                {"do": "expect_request", "actor": "ali", "capability": "repair", "expect": "new"},
            ],
        }
    )
    supported = await run_scenarios(spec, [request_step])
    assert failed(supported) == {}


@pytest.mark.parametrize("scenario_id", GOLDEN_IDS)
async def test_each_golden_scenario_individually(scenario_id: str) -> None:
    spec = load_spec()
    scenario = next(s for s in load_golden() if s.id == scenario_id)
    report = await run_scenarios(spec, [scenario])
    assert failed(report) == {}
