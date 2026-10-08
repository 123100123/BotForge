"""Driver steps for request capabilities (WP8): submit_request, owner_action, expect_request."""

from typing import Any

from app.botspec.models import BotSpec
from app.testing import drivers
from app.testing.request_driver import RequestDriver
from app.testing.runner import run_scenario
from app.testing.scenario import KV, Scenario, SeedRecord, Step
from tests.unit.runtime.test_request import repair_spec

FORM = [
    {"key": "device", "value": "یخچال"},
    {"key": "problem", "value": "صدا می‌دهد"},
    {"key": "phone", "value": "09123456789"},
    {"key": "address", "value": "تهران"},
]


def st(do: str, **kw: Any) -> Step:
    if do == "submit_request":
        kw.setdefault("form", FORM)
    if do != "expect_notified":
        kw.setdefault("capability", "repair")
    return Step.model_validate({"do": do, **kw})


def sc(steps: list[Step], seed: list[SeedRecord] | None = None) -> Scenario:
    return Scenario(id="t", title="آزمایش", source="acceptance", seed=seed or [], steps=steps)


async def run(spec: BotSpec, steps: list[Step], seed: list[SeedRecord] | None = None) -> tuple[bool, str]:
    """(passed, message of the failing step or '')."""
    result = await run_scenario(spec, sc(steps, seed))
    failing = [s for s in result.steps if not s.passed]
    return result.passed, (failing[0].message or "") if failing else ""


def item(ref: str, name: str) -> SeedRecord:
    return SeedRecord(ref=ref, collection="appliance", values=[KV(key="name", value=name)])


def test_driver_is_registered() -> None:
    assert isinstance(drivers.DRIVERS["request"], RequestDriver)
    assert drivers.DRIVERS["request"].supported == {"submit_request", "owner_action", "expect_request"}


# --- submit_request ------------------------------------------------------------------------------


async def test_submit_and_expect_request() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali", expect="submitted"),
            st("expect_request", actor="ali", expect="new"),
        ],
    )
    assert ok, msg


async def test_submit_result_phrase_and_transcript() -> None:
    result = await run_scenario(repair_spec(), sc([st("submit_request", actor="ali", expect="submitted")]))
    assert result.steps[0].narrative == "علی در «درخواست تعمیر» درخواست ثبت می‌کند ← ثبت شد"
    sent = [t.text for t in result.transcript if t.actor == "ali" and t.direction == "in"]
    assert sent[0] == "/start" and sent[-4:] == [f["value"] for f in FORM]  # the real event sequence


async def test_unknown_form_key_fails_the_step() -> None:
    ok, msg = await run(
        repair_spec(), [st("submit_request", actor="ali", form=[{"key": "nope", "value": "x"}])]
    )
    assert not ok and "nope" in msg and "device" in msg


async def test_missing_required_form_value_fails_the_step() -> None:
    ok, msg = await run(repair_spec(), [st("submit_request", actor="ali", form=FORM[:2])])
    assert not ok and "phone" in msg


async def test_invalid_form_value_fails_the_step_naming_the_field() -> None:
    bad = [*FORM[:2], {"key": "phone", "value": "abc"}, FORM[3]]
    ok, msg = await run(repair_spec(), [st("submit_request", actor="ali", form=bad)])
    assert not ok and "phone" in msg


async def test_optional_field_is_skipped_and_choice_and_boolean_use_buttons() -> None:
    spec = repair_spec(
        form_fields=[
            {"key": "device", "label": "دستگاه", "type": "choice", "choices": ["یخچال", "کولر"]},
            {"key": "urgent", "label": "فوری", "type": "boolean"},
            {"key": "note", "label": "توضیح", "type": "text", "required": False},
        ]
    )
    form = [{"key": "device", "value": "کولر"}, {"key": "urgent", "value": "false"}]
    ok, msg = await run(spec, [st("submit_request", actor="ali", form=form, expect="submitted")])
    assert ok, msg
    result = await run_scenario(spec, sc([st("submit_request", actor="ali", form=form)]))
    typed = [t.text for t in result.transcript if t.direction == "in"]
    # pressed buttons are shown by their label: the choice, the boolean (false -> خیر) and skip
    assert typed[-3:] == ["کولر", "خیر", "رد کردن"] and "false" not in typed


async def test_submit_with_item_resource_requires_a_seed_item() -> None:
    spec = repair_spec(item_resource=True)
    ok, msg = await run(spec, [st("submit_request", actor="ali")], [item("a", "یخچال")])
    assert not ok and "item" in msg
    ok, msg = await run(
        spec, [st("submit_request", actor="ali", item="a", expect="submitted")], [item("a", "یخچال")]
    )
    assert ok, msg


async def test_submit_picks_the_right_item_even_on_a_later_page() -> None:
    spec = repair_spec(item_resource=True)
    seeds = [item(f"i{n}", f"دستگاه {n}") for n in range(10)]
    ok, msg = await run(
        spec,
        [
            st("submit_request", actor="ali", item="i9", expect="submitted"),
            st("open", actor="ali", view="mine", contains="دستگاه 9"),
        ],
        seeds,
    )
    assert ok, msg


async def test_item_on_a_capability_without_item_resource_fails() -> None:
    spec = repair_spec(item_resource=True)
    spec.capabilities[0].item_resource = None  # type: ignore[union-attr]
    ok, msg = await run(spec, [st("submit_request", actor="ali", item="a")], [item("a", "یخچال")])
    assert not ok and "item_resource" in msg


async def test_submit_rejected_item_expectation() -> None:
    # An item that is removed mid-flow is covered at the engine level; here: expect mismatch fails.
    ok, msg = await run(repair_spec(), [st("submit_request", actor="ali", expect="rejected")])
    assert not ok and "submitted" in msg


async def test_submit_fails_when_the_home_has_no_entry() -> None:
    data = repair_spec().model_dump(mode="json")
    data["menu"] = [m for m in data["menu"] if m["capability"] != "repair"]  # legacy: irrelevant
    ok, msg = await run(BotSpec.model_validate(data), [st("submit_request", actor="ali")])
    assert ok, msg
    next(c for c in data["capabilities"] if c["key"] == "repair")["enabled"] = False
    ok, msg = await run(BotSpec.model_validate(data), [st("submit_request", actor="ali")])
    assert not ok and "منو" in msg


# --- owner_action --------------------------------------------------------------------------------


async def test_owner_action_ok_and_status_follows() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali"),
            st("owner_action", action="approve", target_actor="ali", expect="ok"),
            st("expect_request", actor="ali", expect="approved"),
            st("expect_notified", actor="ali", event="status_changed"),
        ],
    )
    assert ok, msg


async def test_owner_action_is_sent_as_an_admin_event() -> None:
    result = await run_scenario(
        repair_spec(),
        sc([st("submit_request", actor="ali"), st("owner_action", action="approve", target_actor="ali")]),
    )
    admin = [t.text for t in result.transcript if t.actor == "owner" and t.direction == "in"]
    assert admin[-1].startswith("[مدیریت] repair:own:") and admin[-1].endswith(".approve")
    assert result.steps[1].narrative.startswith("مدیر روی درخواست علی در «درخواست تعمیر» اقدام «تأیید»")


async def test_owner_action_rejected_from_wrong_status() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali"),
            st(
                "owner_action",
                action="mark_done",
                target_actor="ali",
                expect="rejected",
                reason="not_allowed",
            ),
            st("expect_request", actor="ali", expect="new"),
        ],
    )
    assert ok, msg


async def test_owner_action_by_non_owner_is_rejected_not_allowed() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali"),
            st(
                "owner_action",
                actor="sara",
                action="approve",
                target_actor="ali",
                expect="rejected",
                reason="not_allowed",
            ),
            st("expect_request", actor="ali", expect="new"),
        ],
    )
    assert ok, msg


async def test_owner_action_expectation_mismatch_fails_with_both_sides() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali"),
            st("owner_action", action="approve", target_actor="ali", expect="rejected"),
        ],
    )
    assert not ok and "رد شدن" in msg and "ok" in msg


async def test_owner_action_without_a_request_fails() -> None:
    ok, msg = await run(repair_spec(), [st("owner_action", action="approve", target_actor="ali")])
    assert not ok and "درخواستی" in msg


async def test_owner_action_unknown_key_is_rejected_not_allowed() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali"),
            st("owner_action", action="explode", target_actor="ali", expect="rejected", reason="not_allowed"),
        ],
    )
    assert ok, msg


async def test_owner_action_targets_the_latest_request_of_the_target_actor() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali"),
            st("submit_request", actor="sara"),
            st("submit_request", actor="ali"),
            st("owner_action", action="approve", target_actor="ali"),
            st("expect_request", actor="ali", expect="approved"),
            st("expect_request", actor="sara", expect="new"),
        ],
    )
    assert ok, msg


async def test_owner_action_item_selects_the_request_on_that_item() -> None:
    spec = repair_spec(item_resource=True)
    seeds = [item("a", "یخچال"), item("b", "کولر")]
    ok, msg = await run(
        spec,
        [
            st("submit_request", actor="ali", item="a"),
            st("submit_request", actor="ali", item="b"),
            st("owner_action", action="approve", target_actor="ali", item="a"),
            st("expect_request", actor="ali", expect="new"),  # the latest request (on b) is untouched
        ],
        seeds,
    )
    assert ok, msg


# --- expect_request ------------------------------------------------------------------------------


async def test_expect_request_mismatch_names_both_statuses() -> None:
    ok, msg = await run(
        repair_spec(),
        [st("submit_request", actor="ali"), st("expect_request", actor="ali", expect="approved")],
    )
    assert not ok and "تأیید شده" in msg and "در انتظار بررسی" in msg


async def test_expect_request_without_a_request() -> None:
    ok, msg = await run(repair_spec(), [st("expect_request", actor="ali", expect="new")])
    assert not ok and "بدون درخواست" in msg
    ok, msg = await run(repair_spec(), [st("expect_request", actor="ali", expect="none")])
    assert ok, msg


# --- notifications -------------------------------------------------------------------------------


async def test_owner_notified_submitted_and_inbox_is_cleared() -> None:
    ok, msg = await run(
        repair_spec(),
        [
            st("submit_request", actor="ali"),
            st("expect_notified", actor="owner", event="submitted"),
            st("expect_notified", actor="owner", event="submitted"),  # consumed by the first check
        ],
    )
    assert not ok and "ثبت درخواست" not in msg and "هیچ پیامی" in msg


async def test_no_owner_notice_when_not_configured() -> None:
    ok, _ = await run(
        repair_spec(notify_owner_on=[]),
        [st("submit_request", actor="ali"), st("expect_notified", actor="owner", event="submitted")],
    )
    assert not ok
