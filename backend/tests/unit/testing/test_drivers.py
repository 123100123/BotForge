"""Each driver action, exercised through the runner and (for stored data) a RunContext."""

from typing import ClassVar

import pytest

from app.botspec.models import AnyCapability, BotSpec
from app.runtime.memory_store import MemoryStore
from app.testing import drivers
from app.testing.drivers import RunContext, StepFailure, execute_step
from app.testing.runner import START_CLOCK, _load_seed, run_scenario
from app.testing.scenario import Scenario, SeedRecord, Step
from tests.unit.testing.helpers import (
    CAP,
    FORM_FIELDS,
    load_example,
    op,
    patched,
    scenario,
    seed_item,
    set_cap,
    step,
    workshop,
)


async def make_ctx(spec: BotSpec, seeds: list[SeedRecord] | None = None) -> RunContext:
    ctx = RunContext(spec, MemoryStore(owner_actor_id="owner"), START_CLOCK)
    sc = scenario([step("advance_time", hours=1)], seed=[seed_item()] if seeds is None else seeds)
    await _load_seed(ctx, sc)
    return ctx


async def run_steps(spec: BotSpec, steps: list[Step], **kw: object) -> tuple[bool, str]:
    result = await run_scenario(spec, scenario(steps, **kw))
    return result.passed, result.steps[-1].message or ""


# --- book -----------------------------------------------------------------------------------------


async def test_book_outcomes_and_booking_record() -> None:
    ctx = await make_ctx(workshop())
    out = await execute_step(ctx, step("book", actor="ali", item="w1", expect="confirmed"))
    assert out == "تأیید شد"
    rows = await ctx.store.list_records(CAP, actor_id="ali")
    assert [r.status for r in rows] == ["confirmed"]
    assert rows[0].item_id == ctx.refs["w1"]


async def test_book_without_expect_accepts_any_result() -> None:
    ok, _ = await run_steps(
        workshop(),
        [step("book", actor="ali", item="w1"), step("book", actor="ali", item="w1")],
    )
    assert ok  # the second one is a (duplicate) rejection, accepted because no expectation is set


async def test_book_pages_through_the_list_to_find_the_item() -> None:
    seeds = [seed_item(f"w{i}", title=f"کارگاه {i}", start=f"+{40 + i}h") for i in range(1, 11)]
    ok, msg = await run_steps(
        workshop(),
        [
            step("book", actor="ali", item="w10", expect="confirmed"),
            step("expect_booking", actor="ali", item="w10", expect="confirmed"),
            step("cancel", actor="ali", item="w10", expect="cancelled"),
        ],
        seed=seeds,
    )
    assert ok, msg


async def test_form_answers_by_key_with_skip_for_absent_optionals() -> None:
    spec = patched(*FORM_FIELDS)
    ctx = await make_ctx(spec)
    form = [
        {"key": "level", "value": "پیشرفته"},
        {"key": "phone", "value": "0912 000 0000"},
        {"key": "tools", "value": "بله"},
        {"key": "budget", "value": "2.5"},
        {"key": "bio", "value": "درباره من"},
    ]
    await execute_step(ctx, step("book", actor="ali", item="w1", expect="confirmed", form=form))
    rec = (await ctx.store.list_records(CAP, actor_id="ali"))[0]
    assert rec.data == {
        "level": "پیشرفته",
        "note": None,
        "phone": "09120000000",
        "tools": True,
        "age": None,
        "budget": 2.5,
        "bio": "درباره من",
    }
    assert await ctx.store.get_session("ali") is None


async def test_optional_field_given_a_value_is_typed() -> None:
    spec = patched(*FORM_FIELDS)
    ctx = await make_ctx(spec)
    form = [
        {"key": "level", "value": "مبتدی"},
        {"key": "note", "value": "سلام"},
        {"key": "phone", "value": "09120000000"},
        {"key": "tools", "value": "false"},
        {"key": "age", "value": "۳۰"},
        {"key": "budget", "value": "1"},
        {"key": "bio", "value": "x"},
    ]
    await execute_step(ctx, step("book", actor="ali", item="w1", expect="confirmed", form=form))
    rec = (await ctx.store.list_records(CAP, actor_id="ali"))[0]
    assert rec.data["note"] == "سلام"
    assert rec.data["age"] == 30
    assert rec.data["tools"] is False


async def test_missing_required_form_value_fails_naming_the_field() -> None:
    spec = patched(*FORM_FIELDS)
    ok, msg = await run_steps(spec, [step("book", actor="ali", item="w1", expect="confirmed")])
    assert not ok
    assert "سطح" in msg
    assert "level" in msg


async def test_invalid_choice_answer_is_reported_not_looped() -> None:
    spec = patched(*FORM_FIELDS)
    form = [{"key": "level", "value": "خبره"}]
    ok, msg = await run_steps(spec, [step("book", actor="ali", item="w1", form=form)])
    assert not ok
    assert "پذیرفته نشد" in msg
    assert "level" in msg


async def test_form_on_a_rejected_booking_is_not_asked() -> None:
    spec = patched(*FORM_FIELDS, set_cap("one_active_per_user_per_item", True))
    form = [
        {"key": "level", "value": "مبتدی"},
        {"key": "phone", "value": "09120000000"},
        {"key": "tools", "value": "true"},
        {"key": "budget", "value": "1"},
        {"key": "bio", "value": "x"},
    ]
    ok, msg = await run_steps(
        spec,
        [
            step("book", actor="ali", item="w1", expect="confirmed", form=form),
            step("book", actor="ali", item="w1", expect="rejected", reason="duplicate"),
        ],
    )
    assert ok, msg


# --- cancel and owner cancel -------------------------------------------------------------------------


async def test_cancel_and_rejected_cancel_reason() -> None:
    spec = patched(set_cap("cancellation.enabled", False))
    ok, msg = await run_steps(
        spec,
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("cancel", actor="ali", item="w1", expect="rejected", reason="cancellation_disabled"),
            step("expect_booking", actor="ali", item="w1", expect="confirmed"),
        ],
    )
    assert ok, msg


async def test_cancel_deadline_rejection_after_advancing_time() -> None:
    spec = patched(set_cap("cancellation.deadline_hours", 24))
    ok, msg = await run_steps(
        spec,
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("advance_time", hours=25),
            step("cancel", actor="ali", item="w1", expect="rejected", reason="cancel_deadline_passed"),
        ],
    )
    assert ok, msg


async def test_owner_cancel_ok_and_expectation_mismatch() -> None:
    book = step("book", actor="ali", item="w1", expect="confirmed")
    good = step("owner_action", action="cancel", target_actor="ali", item="w1", expect="ok")
    ok, msg = await run_steps(
        workshop(), [book, good, step("expect_booking", actor="ali", item="w1", expect="cancelled")]
    )
    assert ok, msg
    bad = step("owner_action", action="cancel", target_actor="ali", item="w1", expect="rejected")
    ok, msg = await run_steps(workshop(), [book, bad])
    assert not ok
    assert "cancelled" in msg


async def test_owner_cancel_by_a_customer_is_not_allowed() -> None:
    ok, msg = await run_steps(
        workshop(),
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step(
                "owner_action",
                actor="sara",
                action="cancel",
                target_actor="ali",
                item="w1",
                expect="rejected",
                reason="not_allowed",
            ),
            step("expect_booking", actor="ali", item="w1", expect="confirmed"),
        ],
    )
    assert ok, msg


async def test_owner_cancel_ignores_cancellation_rules() -> None:
    spec = patched(set_cap("cancellation.enabled", False))
    ok, msg = await run_steps(
        spec,
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("owner_action", action="cancel", target_actor="ali", item="w1", expect="ok"),
        ],
    )
    assert ok, msg


async def test_owner_action_other_than_cancel_is_rejected_by_the_driver() -> None:
    ok, msg = await run_steps(
        workshop(),
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("owner_action", action="approve", target_actor="ali", item="w1"),
        ],
    )
    assert not ok
    assert "approve" in msg


# --- expectations ------------------------------------------------------------------------------------


async def test_expect_booking_none_and_latest_booking_wins() -> None:
    ok, msg = await run_steps(
        workshop(),
        [
            step("expect_booking", actor="ali", item="w1", expect="none"),
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("cancel", actor="ali", item="w1", expect="cancelled"),
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("expect_booking", actor="ali", item="w1", expect="confirmed"),
        ],
    )
    assert ok, msg


async def test_expect_counts_mismatch_reports_both_numbers() -> None:
    ok, msg = await run_steps(
        workshop(),
        [step("book", actor="ali", item="w1"), step("expect_counts", item="w1", confirmed=3, waitlisted=0)],
    )
    assert not ok
    assert "۳" in msg
    assert "۱" in msg


async def test_expect_counts_only_checks_given_numbers() -> None:
    ok, msg = await run_steps(
        workshop(),
        [step("book", actor="ali", item="w1"), step("expect_counts", item="w1", waitlisted=0)],
    )
    assert ok, msg


# --- open --------------------------------------------------------------------------------------------


async def test_open_main_mine_and_item_detail() -> None:
    ok, msg = await run_steps(
        workshop(),
        [
            step("open", actor="ali", contains="کارگاه عکاسی"),
            step("open", actor="ali", view="mine", contains="ندارید"),
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("open", actor="ali", view="mine", contains="کارگاه عکاسی"),
            step("open", actor="ali", item="w1", contains="مریم احمدی"),
        ],
    )
    assert ok, msg


async def test_open_contains_checks_button_labels_too() -> None:
    ok, msg = await run_steps(workshop(), [step("open", actor="ali", contains="ثبت‌نام‌های من")])
    assert ok, msg  # that string is a button label of the list, not part of its text


async def test_open_contains_failure_lists_what_was_shown() -> None:
    ok, msg = await run_steps(workshop(), [step("open", actor="ali", contains="غایب")])
    assert not ok
    assert "غایب" in msg
    assert "کارگاه عکاسی" in msg


async def test_open_info_single_and_multiple_pages() -> None:
    ok, msg = await run_steps(
        workshop(), [step("open", actor="ali", capability="info", contains="نشانی و تماس")], seed=[]
    )
    assert ok, msg
    repair = load_example("repair.botspec.json")
    result = await run_scenario(
        repair,
        Scenario(
            id="i",
            title="x",
            source="acceptance",
            steps=[step("open", actor="ali", capability="info", contains="ساعات کاری")],
        ),
    )
    assert result.passed


async def test_open_without_menu_item_fails_clearly() -> None:
    ok, msg = await run_steps(workshop(), [step("open", actor="ali", capability="info", view="mine")])
    assert not ok
    assert "mine" in msg


async def test_legacy_menu_items_are_not_needed_to_open() -> None:
    spec = patched(op("remove", ["menu", "my_bookings"]), op("remove", ["menu", "workshops"]))
    ok, msg = await run_steps(spec, [step("open", actor="ali", view="mine")])
    assert ok, msg


async def test_open_item_on_info_is_rejected() -> None:
    ok, msg = await run_steps(workshop(), [step("open", actor="ali", capability="info", item="w1")])
    assert not ok
    assert "info" in msg


# --- registry ----------------------------------------------------------------------------------------


async def test_request_driver_registry_extension_point() -> None:
    repair = load_example("repair.botspec.json")
    sc = Scenario(
        id="r",
        title="x",
        source="acceptance",
        steps=[step("submit_request", actor="ali", capability="repair", expect="submitted")],
    )
    before = drivers.DRIVERS["request"]

    class Fake:
        supported: ClassVar[frozenset[str]] = frozenset({"submit_request"})

        async def perform(self, ctx: RunContext, st: Step, cap: AnyCapability) -> str:
            if st.actor != "ali":
                raise StepFailure("no")
            return "ثبت شد"

    try:
        drivers.register_driver("request", Fake())
        result = await run_scenario(repair, sc)
        assert result.passed
        assert result.steps[0].narrative == "علی در «درخواست تعمیر» درخواست ثبت می‌کند ← ثبت شد"
    finally:
        drivers.register_driver("request", before)
    assert not (await run_scenario(repair, sc)).passed


# --- started items (not listed) and unknown form keys ------------------------------------------------


async def test_book_on_a_started_item_is_rejected_booking_closed() -> None:
    ok, msg = await run_steps(
        workshop(),
        [
            step("book", actor="ali", item="w1", expect="rejected", reason="booking_closed"),
            step("expect_booking", actor="ali", item="w1", expect="none"),
        ],
        seed=[seed_item(start="-1h")],
    )
    assert ok, msg


async def test_book_fallback_fails_when_the_detail_has_no_book_button() -> None:
    ctx = await make_ctx(workshop())
    ctx.refs["w1"] = 9999  # stale id: neither listed nor shown by the engine
    with pytest.raises(StepFailure) as exc:
        await execute_step(ctx, step("book", actor="ali", item="w1"))
    assert "book_workshop:book:9999" in exc.value.message


@pytest.mark.parametrize("with_mine_menu", [True, False])
async def test_cancel_after_the_start_is_rejected_via_mine(with_mine_menu: bool) -> None:
    ops = [set_cap("cancellation.deadline_hours", 0)]
    if not with_mine_menu:
        ops.append(op("remove", ["menu", "my_bookings"]))
    ok, msg = await run_steps(
        patched(*ops),
        [
            step("book", actor="ali", item="w1", expect="confirmed"),
            step("advance_time", hours=49),
            step("cancel", actor="ali", item="w1", expect="rejected", reason="cancel_deadline_passed"),
            step("expect_booking", actor="ali", item="w1", expect="confirmed"),
        ],
    )
    assert ok, msg


async def test_unknown_form_key_fails_naming_it() -> None:
    form = [{"key": "levl", "value": "مبتدی"}]
    ok, msg = await run_steps(patched(*FORM_FIELDS), [step("book", actor="ali", item="w1", form=form)])
    assert not ok
    assert "«levl»" in msg
    assert "level" in msg  # lists the real keys
    ok, msg = await run_steps(workshop(), [step("book", actor="ali", item="w1", form=form)])
    assert not ok
    assert "«levl»" in msg
