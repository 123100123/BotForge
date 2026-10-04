"""Runner behaviors: seed errors, failures, inbox semantics, clock, copy-on-override, narratives."""

import json
from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.patch import PatchOp
from app.runtime.runtime import BotRuntime
from app.testing.runner import run_scenario, run_scenarios
from app.testing.scenario import KV, Scenario, ScenarioResult, SeedRecord
from tests.unit.testing.helpers import (
    CAP,
    EXAMPLES,
    PER_ITEM,
    load_example,
    patched,
    scenario,
    seed_item,
    set_cap,
    step,
    workshop,
)


async def run(sc: Scenario, spec: BotSpec | None = None) -> ScenarioResult:
    return await run_scenario(spec or workshop(), sc)


def failure(result: ScenarioResult) -> str:
    assert not result.passed
    assert result.failed_step is not None
    return result.steps[-1].message or ""


# --- happy path and narratives ---------------------------------------------------------------------


async def test_narrative_is_one_persian_sentence_with_result() -> None:
    sc = scenario([step("book", actor="ali", item="w1", expect="confirmed")], capacity_override=2)
    result = await run(sc)
    assert result.passed
    assert result.steps[0].narrative == "علی در «کارگاه عکاسی» ثبت‌نام می‌کند ← تأیید شد"


async def test_every_step_has_a_nonempty_narrative_and_transcript_is_recorded() -> None:
    sc = scenario(
        [
            step("open", actor="sara", item="w1", contains="کارگاه عکاسی"),
            step("book", actor="reza", item="w1", expect="confirmed"),
            step("expect_booking", actor="reza", item="w1", expect="confirmed"),
            step("expect_counts", item="w1", confirmed=1, waitlisted=0),
            step("expect_notified", actor="owner", event="booked"),
            step("advance_time", hours=1.5),
            step("cancel", actor="reza", item="w1", expect="cancelled"),
        ]
    )
    result = await run(sc)
    assert result.passed, [s.message for s in result.steps]
    assert all(s.narrative.strip() for s in result.steps)
    assert [s.index for s in result.steps] == list(range(7))
    assert {"sara", "reza", "owner"} <= {t.actor for t in result.transcript}
    first_in = next(t for t in result.transcript if t.direction == "in")
    assert first_in.text == "/start"
    assert any(t.direction == "out" and t.buttons for t in result.transcript)
    assert result.steps[5].narrative == "۱٫۵ ساعت می‌گذرد ← زمان جلو رفت"


async def test_display_names_and_owner_label() -> None:
    sc = scenario(
        [
            step("book", actor="nima", item="w1", expect="confirmed"),
            step("owner_action", action="cancel", target_actor="nima", item="w1", expect="ok"),
        ]
    )
    result = await run(sc)
    assert result.passed
    assert result.steps[0].narrative.startswith("nima در «کارگاه عکاسی»")
    assert result.steps[1].narrative.startswith("مدیر ثبت‌نام nima")


# --- seed ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seed", "needle"),
    [
        (SeedRecord(ref="w1", collection="nope", values=[KV(key="title", value="x")]), "nope"),
        (SeedRecord(ref="w1", collection="workshop", values=[KV(key="titel", value="x")]), "titel"),
        (SeedRecord(ref="w1", collection="workshop", values=[KV(key="title", value="x")]), "الزامی"),
    ],
)
async def test_seed_errors_fail_at_step_minus_one(seed: SeedRecord, needle: str) -> None:
    result = await run(scenario([step("advance_time", hours=1)], seed=[seed]))
    assert not result.passed
    assert result.failed_step == -1
    assert result.steps[0].index == -1
    assert needle in (result.steps[0].message or "")
    assert result.steps[0].narrative


async def test_seed_bad_datetime_value() -> None:
    result = await run(scenario([step("advance_time", hours=1)], seed=[seed_item(start="فردا")]))
    assert result.failed_step == -1
    assert "زمان شروع" in (result.steps[0].message or "")


# --- failures never crash ----------------------------------------------------------------------------


async def test_expected_vs_actual_in_failure_message() -> None:
    sc = scenario([step("book", actor="ali", item="w1", expect="waitlisted")], capacity_override=2)
    result = await run(sc)
    assert result.failed_step == 0
    msg = failure(result)
    assert "waitlisted" in msg
    assert "confirmed" in msg
    assert "انتظار" in msg
    assert result.steps[0].narrative.endswith("تأیید شد")


async def test_rejection_reason_is_reported() -> None:
    sc = scenario(
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("book", actor="ali", item="w1", expect="confirmed"),
        ]
    )
    result = await run(sc)
    assert result.failed_step == 1
    assert "duplicate" in failure(result)


async def test_wrong_rejection_reason() -> None:
    sc = scenario(
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("book", actor="ali", item="w1", expect="rejected", reason="capacity_full"),
        ]
    )
    msg = failure(await run(sc))
    assert "capacity_full" in msg
    assert "duplicate" in msg


async def test_stops_at_first_failing_step() -> None:
    sc = scenario(
        [
            step("expect_booking", actor="ali", item="w1", expect="confirmed"),
            step("advance_time", hours=1),
        ]
    )
    result = await run(sc)
    assert result.failed_step == 0
    assert len(result.steps) == 1


async def test_missing_button_names_it() -> None:
    # The item started in the past, so the list does not offer its button (`open` has no fallback).
    sc = scenario([step("open", actor="ali", item="w1")], seed=[seed_item(start="-1h")])
    msg = failure(await run(sc))
    assert "book_workshop:item:" in msg
    assert "کارگاه عکاسی" in msg


async def test_missing_menu_entry_fails_clearly() -> None:
    spec = patched(
        PatchOp(op="remove", path=["menu", "workshops"]),
        PatchOp(op="remove", path=["menu", "my_bookings"]),
    )
    msg = failure(await run(scenario([step("book", actor="ali", item="w1")]), spec))
    assert "منو" in msg


async def test_exception_inside_a_step_becomes_a_failed_step(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(self: Any, event: Any, spec: Any, store: Any) -> Any:
        raise RuntimeError("موتور خراب شد")

    monkeypatch.setattr(BotRuntime, "handle", boom)
    result = await run(scenario([step("book", actor="ali", item="w1", expect="confirmed")]))
    assert result.failed_step == 0
    assert "RuntimeError" in failure(result)
    assert "موتور خراب شد" in failure(result)


async def test_unknown_capability_and_wrong_type_do_not_crash() -> None:
    r1 = await run(scenario([step("book", actor="ali", item="w1", capability="ghost")]))
    assert "ghost" in failure(r1)
    r2 = await run(scenario([step("book", actor="ali", item="w1", capability="info")]))
    assert "پشتیبانی نمی‌شود" in failure(r2)


async def test_cancel_without_booking_and_owner_cancel_without_item() -> None:
    r1 = await run(scenario([step("cancel", actor="ali", item="w1")]))
    assert "ثبت‌نام فعالی" in failure(r1)
    r2 = await run(scenario([step("owner_action", action="cancel", target_actor="ali")]))
    assert "item" in failure(r2)


async def test_request_step_without_required_form_values_fails() -> None:
    repair = load_example("repair.botspec.json")
    sc = Scenario(
        id="r",
        title="درخواست",
        source="acceptance",
        steps=[step("submit_request", actor="ali", capability="repair")],
    )
    result = await run_scenario(repair, sc)
    assert not result.passed
    assert "form" in failure(result)  # the request driver is installed (WP8); the form answers are missing


# --- inbox semantics -------------------------------------------------------------------------------


async def test_notified_matches_and_clears_inbox() -> None:
    sc = scenario(
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("expect_notified", actor="owner", event="booked"),
            step("expect_notified", actor="owner", event="booked"),
        ]
    )
    result = await run(sc)
    assert result.failed_step == 2
    assert "booked" in failure(result)


async def test_notified_any_message_and_wrong_event() -> None:
    base = [step("book", actor="ali", item="w1", expect="confirmed")]
    assert (await run(scenario([*base, step("expect_notified", actor="owner")]))).passed
    bad = await run(scenario([*base, step("expect_notified", actor="owner", event="promoted")]))
    assert bad.failed_step == 1
    assert "booked" in failure(bad)  # lists what the inbox did hold


async def test_acting_actors_own_replies_are_not_inbox() -> None:
    sc = scenario(
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("expect_notified", actor="ali"),
        ]
    )
    assert (await run(sc)).failed_step == 1  # ali only received replies to his own actions


async def test_notified_contains() -> None:
    base = [step("book", actor="ali", item="w1", expect="confirmed")]
    assert (await run(scenario([*base, step("expect_notified", actor="owner", contains="علی")]))).passed
    bad = await run(scenario([*base, step("expect_notified", actor="owner", contains="zzz-none")]))
    assert not bad.passed


async def test_owner_inbox_holds_messages_before_owner_first_acts() -> None:
    sc = scenario(
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("open", actor="owner", capability=CAP),
            step("expect_notified", actor="owner", event="booked"),
        ]
    )
    assert (await run(sc)).passed


# --- clock, override, isolation ---------------------------------------------------------------------


async def test_advance_time_moves_the_clock() -> None:
    spec = patched(set_cap("closes_hours_before_start", 3))
    # start is +48h: booking is open until 45h have passed.
    assert (await run(scenario([step("book", actor="ali", item="w1", expect="confirmed")]), spec)).passed
    late = scenario(
        [
            step("advance_time", hours=46),
            step("book", actor="ali", item="w1", expect="rejected", reason="booking_closed"),
        ]
    )
    assert (await run(late, spec)).passed
    early = scenario(
        [step("advance_time", hours=44), step("book", actor="ali", item="w1", expect="confirmed")]
    )
    assert (await run(early, spec)).passed


async def test_capacity_override_applies_to_a_copy() -> None:
    spec = workshop()
    sc = scenario(
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("book", actor="sara", item="w1", expect="confirmed"),
            step("book", actor="reza", item="w1", expect="waitlisted"),
        ],
        capacity_override=2,
    )
    assert (await run(sc, spec)).passed
    booking = spec.capability(CAP)
    assert booking is not None
    assert booking.capacity.value == 10  # type: ignore[union-attr]


async def test_override_ignored_in_per_item_mode() -> None:
    spec = patched(*PER_ITEM)
    sc = scenario(
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("book", actor="sara", item="w1", expect="confirmed"),
            step("book", actor="reza", item="w1", expect="waitlisted"),
        ],
        seed=[seed_item(seats="2")],
        capacity_override=5,
    )
    assert (await run(sc, spec)).passed


async def test_scenarios_do_not_share_state() -> None:
    sc1 = scenario([step("book", actor="ali", item="w1", expect="confirmed")], id="a")
    sc2 = scenario([step("book", actor="ali", item="w1", expect="confirmed")], id="b")
    report = await run_scenarios(workshop(), [sc1, sc2])
    assert (report.total, report.passed, report.failed) == (2, 2, 0)
    assert [r.scenario_id for r in report.results] == ["a", "b"]
    assert report.duration_ms >= 0


async def test_report_counts_failures() -> None:
    bad = scenario([step("expect_booking", actor="ali", item="w1", expect="confirmed")], id="bad")
    good = scenario([step("advance_time", hours=1)], id="good")
    report = await run_scenarios(workshop(), [bad, good])
    assert (report.total, report.passed, report.failed) == (2, 1, 1)


async def test_runner_is_deterministic() -> None:
    raw = json.loads((EXAMPLES / "workshop.scenarios.json").read_text(encoding="utf-8"))
    scenarios = [Scenario.model_validate(s) for s in raw]
    a = await run_scenarios(workshop(), scenarios)
    b = await run_scenarios(workshop(), scenarios)
    assert [r.model_dump() for r in a.results] == [r.model_dump() for r in b.results]
