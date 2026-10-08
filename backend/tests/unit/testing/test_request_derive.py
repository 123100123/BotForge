"""Derived scenarios for request capabilities (WP8): shape, variants on the real runtime, controls."""

from typing import Any

import pytest

from app.botspec.models import BotSpec, RequestCapability
from app.testing.derive import TEMPLATES, derive_scenarios
from app.testing.request_derive import request_templates, unreachable_actions
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario, TestReport
from tests.unit.runtime.test_request import repair_data, repair_spec

REPAIR_IDS = [
    "derived:repair:submit_and_track",
    "derived:repair:owner_notified",
    "derived:repair:action_approve",
    "derived:repair:action_reject",
    "derived:repair:action_mark_done",
    "derived:repair:action_not_allowed",
    "derived:repair:non_owner_rejected",
    "derived:repair:status_changed_notified",
]


def cap_of(spec: BotSpec) -> RequestCapability:
    cap = spec.capability("repair")
    assert isinstance(cap, RequestCapability)
    return cap


def mine(spec: BotSpec) -> list[Scenario]:
    return [s for s in derive_scenarios(spec) if s.id.startswith("derived:repair:")]


def failed_ids(report: TestReport) -> dict[str, str]:
    out = {}
    for r in report.results:
        if not r.passed:
            out[r.scenario_id] = next(s.message or "" for s in r.steps if not s.passed)
    return out


async def run_all(spec: BotSpec) -> TestReport:
    scenarios = derive_scenarios(spec)
    report = await run_scenarios(spec, scenarios)
    assert report.total == len(scenarios)
    return report


def variant(**cap: Any) -> BotSpec:
    return repair_spec(**cap)


def test_templates_are_registered() -> None:
    assert TEMPLATES["request"] is request_templates


# --- the example spec ----------------------------------------------------------------------------


def test_repair_example_scenario_ids_and_metadata() -> None:
    scenarios = mine(repair_spec())
    assert [s.id for s in scenarios] == REPAIR_IDS
    assert all(s.source == "derived" and s.requirement_ids == [] for s in scenarios)
    assert all(s.capability_keys == ["repair"] for s in scenarios)
    assert all("درخواست تعمیر" in s.title for s in scenarios)
    assert len({s.id for s in scenarios}) == len(scenarios)


async def test_repair_example_derived_scenarios_pass_on_the_real_runtime() -> None:
    report = await run_all(repair_spec())
    assert failed_ids(report) == {}
    assert report.passed == len(REPAIR_IDS) + 1  # + the info capability's scenario


def test_repair_path_scenarios_reach_statuses_through_other_actions() -> None:
    by_id = {s.id: s for s in mine(repair_spec())}
    done = by_id["derived:repair:action_mark_done"]
    assert [s.action for s in done.steps if s.do == "owner_action"] == ["approve", "mark_done"]
    assert done.steps[-1].do == "expect_request" and done.steps[-1].expect == "done"
    bad = by_id["derived:repair:action_not_allowed"]
    owner = [s for s in bad.steps if s.do == "owner_action"]
    assert (owner[0].action, owner[0].expect, owner[0].reason) == ("mark_done", "rejected", "not_allowed")
    assert bad.steps[-1].expect == "new"


# --- variants ------------------------------------------------------------------------------------


async def test_variant_with_item_resource() -> None:
    spec = repair_spec(item_resource=True)
    scenarios = mine(spec)
    assert [s.id for s in scenarios] == [*REPAIR_IDS, "derived:repair:item_tied"]
    tied = scenarios[-1]
    assert [s.ref for s in tied.seed] == ["i1", "i2"]
    assert tied.steps[0].item == "i2" and tied.steps[-1].contains == "مورد ۲"
    assert (await run_all(spec)).failed == 0


async def test_variant_with_item_resource_and_notifications_off() -> None:
    spec = repair_spec(item_resource=True, notify_owner_on=[], notify_user_on=[])
    assert (await run_all(spec)).failed == 0


async def test_variant_with_an_unreachable_action() -> None:
    data = repair_data()
    cap = next(c for c in data["capabilities"] if c["key"] == "repair")
    cap["statuses"].append({"key": "archived", "label": "بایگانی"})
    cap["owner_actions"].append(
        {"key": "restore", "label": "بازیابی", "from_statuses": ["archived"], "to_status": "new"}
    )
    spec = BotSpec.model_validate(data)
    assert unreachable_actions(cap_of(spec)) == ["restore"]
    ids = [s.id for s in mine(spec)]
    assert "derived:repair:action_restore" not in ids and "derived:repair:action_approve" in ids
    assert (await run_all(spec)).failed == 0


async def test_variant_with_a_multi_hop_reachable_action() -> None:
    data = repair_data()
    cap = next(c for c in data["capabilities"] if c["key"] == "repair")
    cap["owner_actions"].append(
        {"key": "reopen", "label": "بازگشایی", "from_statuses": ["done"], "to_status": "new"}
    )
    spec = BotSpec.model_validate(data)
    assert unreachable_actions(cap_of(spec)) == []
    reopen = next(s for s in mine(spec) if s.id.endswith("action_reopen"))
    assert [s.action for s in reopen.steps if s.do == "owner_action"] == ["approve", "mark_done", "reopen"]
    assert (await run_all(spec)).failed == 0


async def test_variant_notifications_off_drops_notice_templates() -> None:
    spec = variant(notify_owner_on=[], notify_user_on=[])
    ids = [s.id for s in mine(spec)]
    assert "derived:repair:owner_notified" not in ids
    assert "derived:repair:status_changed_notified" not in ids
    assert "derived:repair:action_approve" in ids
    assert (await run_all(spec)).failed == 0


async def test_variant_only_one_notification_kind() -> None:
    spec = variant(notify_user_on=[])
    ids = [s.id for s in mine(spec)]
    assert "derived:repair:owner_notified" in ids and "derived:repair:status_changed_notified" not in ids
    assert (await run_all(spec)).failed == 0


async def test_variant_every_action_allowed_everywhere_has_no_disallowed_template() -> None:
    every = ["new", "approved", "rejected", "done"]
    actions = [
        {"key": "approve", "label": "تأیید", "from_statuses": every, "to_status": "approved"},
        {"key": "reject", "label": "رد", "from_statuses": every, "to_status": "rejected"},
    ]
    spec = variant(owner_actions=actions)
    ids = [s.id for s in mine(spec)]
    assert "derived:repair:action_not_allowed" not in ids
    assert (await run_all(spec)).failed == 0


async def test_variant_without_owner_actions() -> None:
    spec = variant(owner_actions=[])
    ids = [s.id for s in mine(spec)]
    assert ids == ["derived:repair:submit_and_track", "derived:repair:owner_notified"]
    assert (await run_all(spec)).failed == 0


async def test_variant_with_choice_boolean_and_optional_fields() -> None:
    spec = variant(
        form_fields=[
            {"key": "device", "label": "دستگاه", "type": "choice", "choices": ["یخچال", "کولر"]},
            {"key": "urgent", "label": "فوری", "type": "boolean"},
            {"key": "count", "label": "تعداد", "type": "integer"},
            {"key": "note", "label": "توضیح", "type": "text", "required": False},
        ]
    )
    assert (await run_all(spec)).failed == 0


async def test_legacy_menu_items_do_not_decide_reachability() -> None:
    """«درخواست‌های من» is always reachable (``sup.mine``), with or without legacy menu items."""
    data = repair_data()
    full = [s.model_dump() for s in mine(BotSpec.model_validate(data))]
    data["menu"] = [m for m in data["menu"] if m["capability"] != "repair"]
    spec = BotSpec.model_validate(data)
    assert [s.model_dump() for s in mine(spec)] == full
    assert "open" in [s.do for s in mine(spec)[0].steps]
    assert (await run_all(spec)).failed == 0


def test_disabled_capability_emits_nothing() -> None:
    data = repair_data()
    next(c for c in data["capabilities"] if c["key"] == "repair")["enabled"] = False
    assert mine(BotSpec.model_validate(data)) == []


# --- negative controls ---------------------------------------------------------------------------


async def run_derived_from_on(derived_from: BotSpec, run_on: BotSpec) -> dict[str, str]:
    report = await run_scenarios(run_on, derive_scenarios(derived_from))
    return failed_ids(report)


def changed(mutate: Any) -> BotSpec:
    data = repair_data()
    mutate(next(c for c in data["capabilities"] if c["key"] == "repair"))
    return BotSpec.model_validate(data)


def action(cap: dict[str, Any], key: str) -> dict[str, Any]:
    return next(a for a in cap["owner_actions"] if a["key"] == key)


async def test_control_baseline_same_spec_passes() -> None:
    assert await run_derived_from_on(repair_spec(), repair_spec()) == {}


async def test_control_different_from_statuses_fail_the_action_scenarios() -> None:
    # approve is only allowed from "approved" in the runtime under test, not from "new"
    other = changed(lambda c: action(c, "approve").update(from_statuses=["approved"]))
    failures = await run_derived_from_on(repair_spec(), other)
    assert "derived:repair:action_approve" in failures
    assert "derived:repair:status_changed_notified" in failures
    assert "derived:repair:action_mark_done" in failures  # its path goes through approve
    assert "derived:repair:submit_and_track" not in failures


async def test_control_widened_from_statuses_fail_the_disallowed_scenario() -> None:
    other = changed(lambda c: action(c, "mark_done").update(from_statuses=["new", "approved"]))
    failures = await run_derived_from_on(repair_spec(), other)
    assert list(failures) == ["derived:repair:action_not_allowed"]
    assert "(ok)" in failures["derived:repair:action_not_allowed"]  # it was applied instead of refused


async def test_control_wrong_target_status_fails_the_action_scenario() -> None:
    other = changed(lambda c: action(c, "reject").update(to_status="done"))
    failures = await run_derived_from_on(repair_spec(), other)
    assert list(failures) == ["derived:repair:action_reject"]


async def test_control_notifications_off_fail_the_notice_scenarios() -> None:
    other = changed(lambda c: c.update(notify_owner_on=[], notify_user_on=[]))
    failures = await run_derived_from_on(repair_spec(), other)
    assert set(failures) == {"derived:repair:owner_notified", "derived:repair:status_changed_notified"}


async def test_control_missing_owner_action_fails() -> None:
    other = changed(lambda c: c.update(owner_actions=[a for a in c["owner_actions"] if a["key"] != "reject"]))
    failures = await run_derived_from_on(repair_spec(), other)
    assert "derived:repair:action_reject" in failures


@pytest.mark.parametrize("scenario_id", REPAIR_IDS)
async def test_each_derived_scenario_passes_individually(scenario_id: str) -> None:
    spec = repair_spec()
    scenario = next(s for s in derive_scenarios(spec) if s.id == scenario_id)
    report = await run_scenarios(spec, [scenario])
    assert failed_ids(report) == {}
