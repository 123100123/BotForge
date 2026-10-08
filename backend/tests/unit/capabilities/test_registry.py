"""Registry integrity, matching on the example specs, and every default_ops on the workshop spec."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.botspec.models import BookingCapability, BotSpec, OrdersCapability, RequestCapability
from app.botspec.patch import apply_patch
from app.botspec.validate import validate_spec
from app.capabilities.registry import CATEGORY_ORDER, REGISTRY, REGISTRY_BY_ID, REGISTRY_IDS, unique_key
from app.capabilities.resolve import find_cycle
from app.capabilities.service import catalog_markdown, list_capabilities
from app.runtime.nav import compile_user_home, virtual_menu
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios

EXAMPLES = Path(__file__).resolve().parents[4] / "examples"

EXPECTED_IDS = (
    "catalog",
    "orders",
    "inventory",
    "payments",
    "booking",
    "forms",
    "approvals",
    "events",
    "announcements",
    "staff",
    "staff_reporting",
    "reporting",
    "spreadsheet_intelligence",
    "scheduled_reports",
    "copilot",
    "info",
    "support",
    "feedback",
)


def load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def workshop() -> BotSpec:
    return BotSpec.model_validate(load("workshop.botspec.json"))


@pytest.fixture
def repair() -> BotSpec:
    return BotSpec.model_validate(load("repair.botspec.json"))


def test_ids_are_the_contract() -> None:
    assert REGISTRY_IDS == EXPECTED_IDS
    assert len(set(REGISTRY_IDS)) == len(REGISTRY_IDS)


def test_edges_reference_existing_ids_and_no_cycles() -> None:
    for cap in REGISTRY:
        for dep in (*cap.requires, *cap.requires_any, *cap.conflicts):
            assert dep in REGISTRY_BY_ID, f"{cap.id} -> {dep}"
            assert dep != cap.id
    assert find_cycle(REGISTRY) is None


def test_entries_are_complete() -> None:
    for cap in REGISTRY:
        assert cap.category in CATEGORY_ORDER
        assert cap.name and cap.description and cap.features and cap.realised_by
        if cap.kind == "spec":
            assert cap.handoff_prompt, cap.id
        else:
            assert cap.matches(BotSpec.model_validate(load("workshop.botspec.json"))) == []
    assert REGISTRY_BY_ID["reporting"].default_enabled
    assert not REGISTRY_BY_ID["payments"].available and not REGISTRY_BY_ID["payments"].configurable
    assert REGISTRY_BY_ID["inventory"].module_default_config == {"low_stock_threshold": 5}
    assert (
        REGISTRY_BY_ID["orders"].handoff_prompt
        == "فروشگاه آنلاین با فهرست محصولات، سبد خرید و ثبت سفارش اضافه کن"
    )
    assert set(REGISTRY_BY_ID["orders"].metrics) >= {"order_count", "revenue", "top_products"}


def test_matches_workshop(workshop: BotSpec) -> None:
    got = {cap.id: cap.matches(workshop) for cap in REGISTRY if cap.kind == "spec"}
    assert got == {
        "catalog": [],
        "orders": [],
        "booking": ["book_workshop"],
        "forms": [],
        "events": [],
        "info": ["info"],
        "support": [],
        "feedback": [],
    }


def test_matches_repair(repair: BotSpec) -> None:
    request_keys = [c.key for c in repair.capabilities if isinstance(c, RequestCapability)]
    assert request_keys, "repair example has a request capability"
    assert REGISTRY_BY_ID["forms"].matches(repair) == [
        k for k in request_keys if k not in ("support", "feedback")
    ]
    assert REGISTRY_BY_ID["booking"].matches(repair) == []


def test_forms_excludes_support_and_feedback(workshop: BotSpec) -> None:
    for cid in ("support", "feedback"):
        ops = REGISTRY_BY_ID[cid].default_ops(workshop)
        assert ops is not None
        spec = apply_patch(workshop, ops)
        assert REGISTRY_BY_ID[cid].matches(spec) == [cid]
        assert REGISTRY_BY_ID["forms"].matches(spec) == []


def test_events_matches_preset_not_booking(workshop: BotSpec) -> None:
    ops = REGISTRY_BY_ID["events"].default_ops(workshop)
    assert ops is not None
    spec = apply_patch(workshop, ops)
    assert REGISTRY_BY_ID["events"].matches(spec) == ["events"]
    assert REGISTRY_BY_ID["booking"].matches(spec) == ["book_workshop"]


@pytest.mark.parametrize("cap_id", [c.id for c in REGISTRY if c.kind == "spec"])
async def test_default_ops_apply_validate_and_pass_derived_tests(workshop: BotSpec, cap_id: str) -> None:
    cap = REGISTRY_BY_ID[cap_id]
    ops = cap.default_ops(workshop)
    if ops is None:
        assert cap_id in {"catalog", "orders", "booking", "forms"}, f"{cap_id} should have defaults"
        return
    spec = apply_patch(workshop, ops)  # raises PatchError when invalid
    assert not [i for i in validate_spec(spec) if i.severity == "error"]
    keys = cap.matches(spec)
    assert keys, f"{cap_id}: the default ops must realise the capability"
    assert spec.menu == workshop.menu, f"{cap_id}: toggles no longer write menu items"
    assert any(e.capability in keys for e in virtual_menu(spec)), f"{cap_id}: must be reachable"
    report = await run_scenarios(spec, derive_scenarios(spec))
    assert report.failed == 0, [r.scenario_id for r in report.results if not r.passed]
    assert apply_patch(workshop, ops) == spec  # deterministic


def test_events_default_shape(workshop: BotSpec) -> None:
    spec = apply_patch(workshop, REGISTRY_BY_ID["events"].default_ops(workshop) or [])
    cap = spec.capability("events")
    assert isinstance(cap, BookingCapability)
    assert cap.preset == "events" and cap.category_field == "category" and cap.reminder_hours_before == 24
    assert (
        cap.start_field == "starts_at"
        and cap.capacity.mode == "per_item"
        and cap.capacity.field == "capacity"
    )
    resource = spec.resource(cap.resource)
    assert resource is not None and resource.key == "event"
    assert [f.key for f in resource.fields] == [
        "title",
        "description",
        "category",
        "starts_at",
        "location",
        "capacity",
    ]
    home = compile_user_home(spec, "customer")
    assert [(e.key, e.label) for e in home if e.capability == "events"] == [
        ("evt", "📅 رویدادها"),
        ("evt.mine", "🗓 ثبت‌نام‌های من"),
    ]


def test_events_key_suffixed_when_taken(workshop: BotSpec) -> None:
    data = workshop.model_dump(mode="json")
    data["capabilities"][0]["key"] = "events"  # the info capability now owns "events"
    for m in data["menu"]:
        if m["capability"] == "info":
            m["capability"] = "events"
    spec = BotSpec.model_validate(data)
    out = apply_patch(spec, REGISTRY_BY_ID["events"].default_ops(spec) or [])
    assert REGISTRY_BY_ID["events"].matches(out) == ["events_2"]


def test_orders_default_needs_one_priced_catalog_resource(workshop: BotSpec) -> None:
    assert REGISTRY_BY_ID["orders"].default_ops(workshop) is None  # no catalog
    data = copy.deepcopy(workshop.model_dump(mode="json"))
    data["capabilities"].append(
        {
            "type": "catalog",
            "key": "catalog",
            "title": "فهرست",
            "resource": "workshop",
            "detail_fields": ["description"],
        }
    )
    data["menu"].append({"key": "cat", "label": "فهرست", "capability": "catalog", "view": "main"})
    spec = BotSpec.model_validate(data)
    ops = REGISTRY_BY_ID["orders"].default_ops(spec)
    assert ops is not None
    out = apply_patch(spec, ops)
    orders = out.capability("orders")
    assert isinstance(orders, OrdersCapability)
    assert orders.resource == "workshop" and orders.price_field == "price"
    assert [s.key for s in orders.statuses] == ["new", "confirmed", "delivered", "cancelled"]
    assert orders.initial_status == "new" and orders.cancellable_statuses == ["new"]
    assert [a.key for a in orders.owner_actions] == ["confirm", "deliver", "cancel"]


def test_fixed_key_taken_by_other_type_needs_agent(workshop: BotSpec) -> None:
    data = workshop.model_dump(mode="json")
    data["capabilities"][0]["key"] = "support"
    for m in data["menu"]:
        if m["capability"] == "info":
            m["capability"] = "support"
    spec = BotSpec.model_validate(data)
    assert REGISTRY_BY_ID["support"].default_ops(spec) is None


def test_unique_key() -> None:
    assert unique_key("events", set()) == "events"
    assert unique_key("events", {"events", "events_2"}) == "events_3"
    assert len(unique_key("a" * 24, {"a" * 24})) == 24


def test_list_capabilities_without_spec() -> None:
    out = list_capabilities(None, [])
    assert [c.id for c in out.categories] == list(CATEGORY_ORDER)
    assert [c.name for c in out.categories] == ["تجارت", "عملیات", "تیم", "هوش کسب‌وکار", "مشتریان"]
    caps = {c.id: c for cat in out.categories for c in cat.capabilities}
    assert set(caps) == set(EXPECTED_IDS)
    assert caps["reporting"].enabled and not caps["copilot"].enabled
    assert caps["events"].needs_agent  # no bot yet: the agent builds it first


def test_list_capabilities_workshop(workshop: BotSpec) -> None:
    caps = {c.id: c for cat in list_capabilities(workshop, []).categories for c in cat.capabilities}
    assert caps["booking"].enabled and caps["booking"].spec_keys == ["book_workshop"]
    assert caps["info"].enabled
    assert not caps["events"].enabled and not caps["events"].needs_agent
    assert caps["orders"].needs_agent and caps["orders"].handoff_prompt
    assert caps["inventory"].config == {"low_stock_threshold": 5}
    assert caps["booking"].config["reminder_hours_before"] is None
    assert caps["booking"].audience == "everyone"


def test_catalog_markdown_lists_every_id() -> None:
    md = catalog_markdown()
    for cid in EXPECTED_IDS:
        assert f"| {cid} |" in md
    assert "unavailable" in md and "needs agent" in md
