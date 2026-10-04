"""Derived scenarios: stable ids, emitted only when meaningful, and ALL passing on the real runtime
for every spec variant (a failing derived scenario must always mean a real bug)."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.patch import PatchOp
from app.botspec.validate import validate_spec
from app.testing.derive import TEMPLATES, derive_scenarios, register_templates
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario
from tests.unit.testing.helpers import (
    BOOK,
    CAP,
    EXAMPLES,
    FORM_FIELDS,
    PER_ITEM,
    load_example,
    op,
    patched,
    set_cap,
    workshop,
)

Variant = Callable[[], BotSpec]


def _v(*ops: PatchOp) -> Variant:
    return lambda: patched(*ops)


def _catalog_info_only() -> BotSpec:
    data: dict[str, Any] = {
        "bot": {"name": "ربات", "welcome_text": "سلام"},
        "resources": [
            {
                "key": "event",
                "label": "رویداد",
                "label_plural": "رویدادها",
                "title_field": "title",
                "fields": [
                    {"key": "title", "label": "عنوان", "type": "text"},
                    {"key": "starts_at", "label": "زمان", "type": "datetime"},
                    {"key": "price", "label": "هزینه", "type": "integer", "required": False},
                    {"key": "online", "label": "آنلاین", "type": "boolean"},
                    {"key": "kind", "label": "نوع", "type": "choice", "choices": ["الف", "ب"]},
                    {"key": "contact", "label": "تماس", "type": "phone"},
                    {"key": "weight", "label": "وزن", "type": "decimal"},
                ],
            }
        ],
        "capabilities": [
            {
                "type": "catalog",
                "key": "events",
                "title": "رویدادها",
                "resource": "event",
                "detail_fields": ["starts_at", "price"],
                "upcoming_only_field": "starts_at",
                "sort_field": "starts_at",
            },
            {
                "type": "info",
                "key": "about",
                "title": "دربارهٔ ما",
                "pages": [
                    {"key": "p1", "title": "صفحهٔ اول", "body": "متن اول"},
                    {"key": "p2", "title": "صفحهٔ دوم", "body": "متن دوم"},
                ],
            },
            {
                "type": "info",
                "key": "hours",
                "title": "ساعات",
                "pages": [{"key": "h", "title": "ساعات کاری", "body": "۹ تا ۱۷"}],
            },
        ],
        "menu": [
            {"key": "m1", "label": "رویدادها", "capability": "events"},
            {"key": "m2", "label": "دربارهٔ ما", "capability": "about"},
            {"key": "m3", "label": "ساعات", "capability": "hours"},
        ],
    }
    return BotSpec.model_validate(data)


def _title_field(field: dict[str, Any], value_field: str) -> list[PatchOp]:
    """Add ``field`` to the workshop resource and make it the title."""
    return [
        op("add", ["resources", "workshop", "fields"], field),
        op("set", ["resources", "workshop", "title_field"], value_field),
    ]


VARIANTS: dict[str, Variant] = {
    "base": workshop,
    "per_item_capacity": _v(*PER_ITEM),
    "per_item_waitlist_off": _v(*PER_ITEM, set_cap("waitlist.enabled", False)),
    "waitlist_off": _v(set_cap("waitlist.enabled", False)),
    "auto_promote_off": _v(set_cap("waitlist.auto_promote", False)),
    "promoted_notice_off": _v(set_cap("notify_user_on", [])),
    "owner_notices_all": _v(set_cap("notify_owner_on", ["booked", "waitlisted", "cancelled"])),
    "deadline_24": _v(set_cap("cancellation.deadline_hours", 24)),
    "deadline_2": _v(set_cap("cancellation.deadline_hours", 2)),
    "deadline_1": _v(set_cap("cancellation.deadline_hours", 1)),
    "deadline_0": _v(set_cap("cancellation.deadline_hours", 0)),
    "deadline_500": _v(set_cap("cancellation.deadline_hours", 500)),
    "cutoff_3": _v(set_cap("closes_hours_before_start", 3)),
    "cutoff_1": _v(set_cap("closes_hours_before_start", 1)),
    "cutoff_0": _v(set_cap("closes_hours_before_start", 0)),
    "cutoff_100": _v(set_cap("closes_hours_before_start", 100)),
    "limit_1": _v(set_cap("max_active_per_user", 1)),
    "limit_2": _v(set_cap("max_active_per_user", 2)),
    "limit_9": _v(set_cap("max_active_per_user", 9)),
    "limit_12_skipped": _v(set_cap("max_active_per_user", 12)),
    "form_fields": _v(*FORM_FIELDS),
    "form_fields_waitlist_off_limit": _v(
        *FORM_FIELDS, set_cap("waitlist.enabled", False), set_cap("max_active_per_user", 2)
    ),
    "duplicates_allowed": _v(set_cap("one_active_per_user_per_item", False)),
    "cancellation_disabled": _v(set_cap("cancellation.enabled", False)),
    "cancellation_disabled_waitlist_off": _v(
        set_cap("cancellation.enabled", False), set_cap("waitlist.enabled", False)
    ),
    "capacity_1": _v(set_cap("capacity", {"mode": "fixed", "value": 1})),
    "capacity_3": _v(set_cap("capacity", {"mode": "fixed", "value": 3})),
    "capacity_30": _v(set_cap("capacity", {"mode": "fixed", "value": 30})),
    "capacity_31_no_configured": _v(set_cap("capacity", {"mode": "fixed", "value": 31})),
    "no_start_field": _v(op("remove", [*BOOK, "start_field"])),
    "no_mine_menu": _v(op("remove", ["menu", "my_bookings"])),
    "no_main_menu": _v(op("remove", ["menu", "workshops"])),
    "no_menu_for_booking": _v(op("remove", ["menu", "workshops"]), op("remove", ["menu", "my_bookings"])),
    "integer_title": _v(*_title_field({"key": "code", "label": "کد", "type": "integer"}, "code")),
    "choice_title": _v(
        *_title_field({"key": "kind", "label": "نوع", "type": "choice", "choices": ["الف", "ب"]}, "kind")
    ),
    "datetime_title": _v(op("set", ["resources", "workshop", "title_field"], "starts_at")),
    "everything": _v(
        *PER_ITEM,
        *FORM_FIELDS,
        set_cap("waitlist.auto_promote", True),
        set_cap("cancellation.deadline_hours", 5),
        set_cap("closes_hours_before_start", 2),
        set_cap("max_active_per_user", 2),
        set_cap("notify_owner_on", ["booked", "waitlisted", "cancelled"]),
    ),
    "catalog_and_info_only": _catalog_info_only,
}

# Template ids expected (suffixes of derived:book_workshop:<id>) for a few variants.
ALL_BOOKING = {
    "basic",
    "capacity_reached",
    "duplicate",
    "cancel_frees_seat",
    "waitlisted_cancel",
    "promotion_order",
    "owner_cancel",
    "owner_cancel_promotes",
    "configured_capacity",
    "item_started",
}


def derived_ids(spec: BotSpec) -> set[str]:
    return {s.id.split(":", 2)[2] for s in derive_scenarios(spec) if s.id.startswith(f"derived:{CAP}:")}


@pytest.mark.parametrize("name", list(VARIANTS))
async def test_every_derived_scenario_passes_on_the_real_runtime(name: str) -> None:
    spec = VARIANTS[name]()
    assert not [i for i in validate_spec(spec) if i.severity == "error"]
    scenarios = derive_scenarios(spec)
    assert scenarios or name in {"no_menu_for_booking"}
    report = await run_scenarios(spec, scenarios)
    bad = [
        (r.scenario_id, r.failed_step, [s.message for s in r.steps if not s.passed])
        for r in report.results
        if not r.passed
    ]
    assert not bad, bad
    assert report.total == len(scenarios)


@pytest.mark.parametrize("name", list(VARIANTS))
def test_derivation_is_deterministic_stable_and_well_formed(name: str) -> None:
    spec = VARIANTS[name]()
    a, b = derive_scenarios(spec), derive_scenarios(spec)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]
    ids = [s.id for s in a]
    assert len(set(ids)) == len(ids)
    for s in a:
        assert s.source == "derived"
        assert s.requirement_ids == []
        assert s.capability_keys
        assert s.id.startswith(f"derived:{s.capability_keys[0]}:")
        assert s.title.strip()
        # round-trips through the frozen model (what the agent tools will serialize)
        assert Scenario.model_validate(json.loads(s.model_dump_json())) == s


def test_base_workshop_templates() -> None:
    spec = workshop()
    assert derived_ids(spec) == ALL_BOOKING
    by_id = {s.id: s for s in derive_scenarios(spec)}
    assert by_id[f"derived:{CAP}:capacity_reached"].capacity_override == 2
    configured = by_id[f"derived:{CAP}:configured_capacity"]
    assert configured.capacity_override is None
    assert {st.actor for st in configured.steps if st.do == "book"} == {f"u{i}" for i in range(1, 12)}
    assert configured.steps[-2].expect == "waitlisted"
    assert "derived:info:open" in by_id


def test_waitlist_off_templates() -> None:
    spec = patched(set_cap("waitlist.enabled", False))
    ids = derived_ids(spec)
    assert ids == {
        "basic",
        "capacity_reached",
        "duplicate",
        "cancel_frees_seat",
        "owner_cancel",
        "configured_capacity",
        "item_started",
    }
    capacity = next(s for s in derive_scenarios(spec) if s.id.endswith(":capacity_reached"))
    last = [st for st in capacity.steps if st.do == "book"][-1]
    assert (last.expect, last.reason) == ("rejected", "capacity_full")


def test_auto_promote_off_swaps_promotion_for_no_promotion() -> None:
    ids = derived_ids(patched(set_cap("waitlist.auto_promote", False)))
    assert "no_auto_promote" in ids
    assert not ids & {"promotion_order", "owner_cancel_promotes"}


def test_conditional_templates_appear_with_their_configuration() -> None:
    assert "cancel_deadline" in derived_ids(patched(set_cap("cancellation.deadline_hours", 2)))
    assert "booking_cutoff" in derived_ids(patched(set_cap("closes_hours_before_start", 3)))
    assert "user_limit" in derived_ids(patched(set_cap("max_active_per_user", 2)))
    assert "user_limit" not in derived_ids(patched(set_cap("max_active_per_user", 12)))
    assert "duplicate" not in derived_ids(patched(set_cap("one_active_per_user_per_item", False)))
    disabled = derived_ids(patched(set_cap("cancellation.enabled", False)))
    assert "cancellation_disabled" in disabled
    assert not disabled & {"cancel_frees_seat", "waitlisted_cancel", "promotion_order"}
    assert "owner_cancel" in disabled  # the owner can still cancel
    assert "configured_capacity" not in derived_ids(
        patched(set_cap("capacity", {"mode": "fixed", "value": 31}))
    )
    assert "configured_capacity" in derived_ids(patched(set_cap("capacity", {"mode": "fixed", "value": 30})))
    assert "configured_capacity" not in derived_ids(patched(*PER_ITEM))


def test_deadline_and_cutoff_zero_now_include_the_after_halves() -> None:
    spec = patched(set_cap("cancellation.deadline_hours", 0), set_cap("closes_hours_before_start", 0))
    by_id = {s.id: s for s in derive_scenarios(spec)}
    assert any(st.reason == "cancel_deadline_passed" for st in by_id[f"derived:{CAP}:cancel_deadline"].steps)
    assert any(st.reason == "booking_closed" for st in by_id[f"derived:{CAP}:booking_cutoff"].steps)
    assert f"derived:{CAP}:item_started" in by_id


def test_duplicate_allowed_only_when_the_flag_is_false() -> None:
    assert "duplicate_allowed" not in derived_ids(workshop())
    off = patched(set_cap("one_active_per_user_per_item", False))
    assert "duplicate_allowed" in derived_ids(off)
    assert "duplicate" not in derived_ids(off)
    limited = patched(set_cap("one_active_per_user_per_item", False), set_cap("max_active_per_user", 1))
    assert "duplicate_allowed" not in derived_ids(limited)  # a limit of 1 would refuse the second booking


async def test_duplicate_allowed_catches_a_spec_that_still_forbids_duplicates() -> None:
    allowed = patched(set_cap("one_active_per_user_per_item", False))
    scenario = next(s for s in derive_scenarios(allowed) if s.id.endswith(":duplicate_allowed"))
    report = await run_scenarios(workshop(), [scenario])  # the flag is true here
    assert report.failed == 1
    assert report.results[0].failed_step == 1
    assert "duplicate" in (report.results[0].steps[-1].message or "")


def test_per_item_capacity_is_seeded_not_overridden() -> None:
    spec = patched(*PER_ITEM)
    for s in derive_scenarios(spec):
        if s.id.startswith(f"derived:{CAP}:"):
            assert s.capacity_override is None
            for seed in s.seed:
                assert {kv.key: kv.value for kv in seed.values}["seats"] == "2"


def test_form_values_cover_required_fields_only() -> None:
    spec = patched(*FORM_FIELDS)
    basic = next(s for s in derive_scenarios(spec) if s.id.endswith(":basic"))
    keys = {kv.key for kv in basic.steps[0].form}
    assert keys == {"level", "phone", "tools", "budget", "bio"}


def test_seed_values_are_relative_and_far_enough_for_deadline_and_cutoff() -> None:
    spec = patched(set_cap("cancellation.deadline_hours", 100), set_cap("closes_hours_before_start", 30))
    s = next(x for x in derive_scenarios(spec) if x.id.endswith(":basic"))
    start = {kv.key: kv.value for kv in s.seed[0].values}["starts_at"]
    assert start == "+172h"


def test_catalog_and_info_only_spec() -> None:
    spec = _catalog_info_only()
    ids = [s.id for s in derive_scenarios(spec)]
    assert ids == ["derived:events:open", "derived:about:open", "derived:hours:open"]
    catalog = derive_scenarios(spec)[0]
    assert catalog.steps[0].contains == "مورد ۱"


def test_capabilities_without_a_main_menu_item_are_skipped() -> None:
    assert (
        derive_scenarios(patched(op("remove", ["menu", "workshops"]), op("remove", ["menu", "my_bookings"])))
        != []
    )
    spec = patched(op("remove", ["menu", "workshops"]), op("remove", ["menu", "my_bookings"]))
    assert not [s for s in derive_scenarios(spec) if s.id.startswith(f"derived:{CAP}:")]


def test_request_capabilities_emit_request_templates() -> None:
    repair = load_example("repair.botspec.json")
    ids = [s.id for s in derive_scenarios(repair)]
    assert ids[-1] == "derived:info:open"
    assert "derived:repair:submit_and_track" in ids


def test_template_registry_extension_point() -> None:
    repair = load_example("repair.botspec.json")
    before = TEMPLATES.get("request")
    marker = Scenario.model_validate(
        {
            "id": "derived:repair:x",
            "title": "x",
            "source": "derived",
            "steps": [{"do": "advance_time", "hours": 1}],
        }
    )
    try:
        register_templates("request", lambda spec, cap: [marker])
        assert marker in derive_scenarios(repair)
    finally:
        if before is None:
            TEMPLATES.pop("request", None)
        else:
            TEMPLATES["request"] = before


def test_golden_example_files_still_parse() -> None:
    raw = json.loads((EXAMPLES / "workshop.scenarios.json").read_text(encoding="utf-8"))
    assert len(raw) == 9
