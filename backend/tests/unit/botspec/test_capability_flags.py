"""Business OS spec additions: enabled/audience flags, booking events preset, orders type."""

import copy
from typing import Any

import pytest

from app.botspec.compat import check_compat
from app.botspec.diff import diff_specs
from app.botspec.models import BotSpec, OrdersCapability
from app.botspec.outline import spec_outline
from app.botspec.patch import PatchOp, apply_patch
from app.botspec.validate import check_spec, has_errors, validate_spec
from tests.unit.botspec.conftest import load_json

STATUSES = [
    {"key": "new", "label": "جدید"},
    {"key": "sent", "label": "ارسال‌شده"},
    {"key": "done", "label": "تحویل‌شده"},
]
OWNER_ACTIONS = [
    {"key": "send", "label": "ارسال", "from_statuses": ["new"], "to_status": "sent"},
    {"key": "deliver", "label": "تحویل", "from_statuses": ["sent"], "to_status": "done"},
]


def orders_cap(**over: Any) -> dict[str, Any]:
    cap: dict[str, Any] = {
        "type": "orders",
        "key": "shop",
        "title": "فروشگاه",
        "resource": "product",
        "price_field": "price",
        "stock_field": "stock",
        "checkout_fields": [
            {"key": "address", "label": "نشانی", "type": "long_text"},
            {"key": "phone", "label": "تلفن", "type": "phone"},
        ],
        "statuses": copy.deepcopy(STATUSES),
        "initial_status": "new",
        "owner_actions": copy.deepcopy(OWNER_ACTIONS),
        "cancellable_statuses": ["new"],
    }
    cap.update(over)
    return cap


def events_cap(**over: Any) -> dict[str, Any]:
    cap: dict[str, Any] = {
        "type": "booking",
        "key": "events",
        "title": "رویدادها",
        "resource": "event",
        "capacity": {"mode": "fixed", "value": 20},
        "start_field": "starts_at",
        "detail_fields": ["starts_at", "category"],
        "preset": "events",
        "reminder_hours_before": 24,
        "category_field": "category",
    }
    cap.update(over)
    return cap


def business_data() -> dict[str, Any]:
    return {
        "bot": {"name": "کافه نمونه", "welcome_text": "خوش آمدید!"},
        "resources": [
            {
                "key": "product",
                "label": "کالا",
                "label_plural": "کالاها",
                "title_field": "title",
                "fields": [
                    {"key": "title", "label": "نام", "type": "text"},
                    {"key": "price", "label": "قیمت", "type": "integer"},
                    {"key": "stock", "label": "موجودی", "type": "integer", "required": False},
                    {"key": "note", "label": "توضیح", "type": "text", "required": False},
                ],
            },
            {
                "key": "event",
                "label": "رویداد",
                "label_plural": "رویدادها",
                "title_field": "title",
                "fields": [
                    {"key": "title", "label": "عنوان", "type": "text"},
                    {"key": "starts_at", "label": "زمان", "type": "datetime"},
                    {
                        "key": "category",
                        "label": "دسته",
                        "type": "choice",
                        "choices": ["کارگاه", "همایش"],
                    },
                ],
            },
        ],
        "capabilities": [
            orders_cap(),
            events_cap(),
            {
                "type": "info",
                "key": "info",
                "title": "دربارهٔ ما",
                "pages": [{"key": "a", "title": "ما", "body": "متن"}],
            },
        ],
        "menu": [
            {"key": "shop_menu", "label": "فروشگاه", "capability": "shop"},
            {"key": "my_orders", "label": "سفارش‌های من", "capability": "shop", "view": "mine"},
            {"key": "events_menu", "label": "رویدادها", "capability": "events"},
            {"key": "my_events", "label": "رویدادهای من", "capability": "events", "view": "mine"},
            {"key": "about", "label": "دربارهٔ ما", "capability": "info"},
        ],
    }


def codes(data: dict[str, Any]) -> set[str]:
    return {i.code for i in check_spec(data) if i.severity == "error"}


def cap_of(data: dict[str, Any], key: str) -> dict[str, Any]:
    return next(c for c in data["capabilities"] if c["key"] == key)


# ---------------------------------------------------------------- backward compatibility


@pytest.mark.parametrize("name", ["workshop.botspec.json", "repair.botspec.json"])
def test_examples_still_parse_and_validate(name: str) -> None:
    data = load_json(name)
    spec = BotSpec.model_validate(data)
    assert not has_errors(validate_spec(spec))
    for cap in spec.capabilities:
        assert cap.enabled is True and cap.audience == "everyone"
    # Dumping adds the defaults; the result parses back to the same spec.
    assert BotSpec.model_validate(spec.model_dump(mode="json")) == spec


def test_flag_defaults_and_values() -> None:
    data = business_data()
    spec = BotSpec.model_validate(data)
    booking = spec.capability("events")
    assert booking is not None and booking.type == "booking"
    assert booking.preset == "events" and booking.reminder_hours_before == 24
    data["capabilities"][2]["audience"] = "boss"
    assert "schema_literal_error" in codes(data)


def test_business_spec_is_valid() -> None:
    issues = check_spec(business_data())
    assert not has_errors(issues), issues
    assert isinstance(BotSpec.model_validate(business_data()).capability("shop"), OrdersCapability)


# ---------------------------------------------------------------- orders validation


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"resource": "nope"}, "unknown_resource"),
        ({"price_field": "nope"}, "unknown_field"),
        ({"price_field": "title"}, "field_type_mismatch"),
        ({"stock_field": "note"}, "field_type_mismatch"),
        ({"statuses": [*STATUSES, STATUSES[0]]}, "duplicate_key"),
        ({"initial_status": "pending"}, "unknown_status"),
        ({"cancellable_statuses": ["pending"]}, "unknown_status"),
        (
            {"owner_actions": [{"key": "x", "label": "x", "from_statuses": ["zz"], "to_status": "sent"}]},
            "unknown_status",
        ),
        (
            {
                "key": "s" * 24,
                "owner_actions": [
                    {"key": "a" * 24, "label": "x", "from_statuses": ["new"], "to_status": "sent"}
                ],
            },
            "callback_too_long",
        ),
        (
            {"checkout_fields": [{"key": f"f{i}", "label": "x", "type": "text"} for i in range(6)]},
            "too_many_checkout_fields",
        ),
        ({"checkout_fields": [{"key": "when", "label": "زمان", "type": "datetime"}]}, "datetime_form_field"),
        (
            {"checkout_fields": [{"key": "c", "label": "x", "type": "choice", "choices": ["a"]}]},
            "choice_without_choices",
        ),
        ({"texts": [{"key": "nope", "value": "x"}]}, "unknown_text_key"),
        ({"texts": [{"key": "placed", "value": "{limit}"}]}, "invalid_placeholder"),
    ],
)
def test_orders_validation_codes(over: dict[str, Any], code: str) -> None:
    data = business_data()
    shop = cap_of(data, "shop")
    shop.update(over)
    if "key" in over:  # keep the menu pointing at the renamed capability
        for m in data["menu"]:
            if m["capability"] == "shop":
                m["capability"] = over["key"]
    assert code in codes(data)


def test_orders_text_override_valid() -> None:
    data = business_data()
    cap_of(data, "shop")["texts"] = [{"key": "placed", "value": "سفارش {id} ثبت شد؛ مبلغ {total}"}]
    assert codes(data) == set()


# ---------------------------------------------------------------- booking events preset


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"category_field": "title"}, "field_type_mismatch"),
        ({"category_field": "nope"}, "unknown_field"),
        ({"reminder_hours_before": 0}, "value_out_of_range"),
        ({"reminder_hours_before": 721}, "value_out_of_range"),
        ({"start_field": None, "detail_fields": ["category"]}, "start_field_required"),
        ({"preset": "party"}, "schema_literal_error"),
    ],
)
def test_booking_preset_validation(over: dict[str, Any], code: str) -> None:
    data = business_data()
    cap_of(data, "events").update(over)
    assert code in codes(data)


def test_booking_reminder_bounds_accepted() -> None:
    for hours in (1, 720):
        data = business_data()
        cap_of(data, "events")["reminder_hours_before"] = hours
        assert codes(data) == set()


# ---------------------------------------------------------------- enabled flag and the menu


def test_menu_no_longer_drives_reachability() -> None:
    """Navigation is compiled from the enabled capabilities (runtime/nav.py): an empty or long
    legacy menu, or a capability no menu item points at, is valid and warning-free."""
    data = business_data()
    data["menu"] = []
    assert codes(data) == set()
    assert {i.code for i in check_spec(data)} == set()
    data = business_data()
    data["menu"] += [{"key": f"more{i}", "label": "بیشتر", "capability": "info"} for i in range(12)]
    assert codes(data) == set()


def test_at_least_one_capability_must_stay_enabled() -> None:
    data = business_data()
    for cap in data["capabilities"]:
        cap["enabled"] = False
    assert codes(data) == {"no_enabled_capabilities"}
    cap_of(data, "info")["enabled"] = True
    assert codes(data) == set()


def test_legacy_menu_items_must_still_be_well_formed() -> None:
    data = business_data()
    data["menu"].append({"key": "ghost", "label": "x", "capability": "nope"})
    assert "unknown_capability" in codes(data)


def test_nav_is_a_reserved_key() -> None:
    data = business_data()
    cap_of(data, "info")["key"] = "nav"
    data["menu"] = [m for m in data["menu"] if m["capability"] != "info"]
    assert "reserved_key" in codes(data)


def test_mine_view_allowed_for_orders_not_info() -> None:
    data = business_data()
    assert "mine_view_unsupported" not in codes(data)
    data["menu"].append({"key": "bad", "label": "x", "capability": "info", "view": "mine"})
    assert "mine_view_unsupported" in codes(data)


# ---------------------------------------------------------------- outline, patch, compat, diff


def test_outline_renders_orders_and_events_preset() -> None:
    outline = spec_outline(BotSpec.model_validate(business_data()))
    shop = next(c for c in outline.capabilities if c.key == "shop")
    assert shop.type == "orders" and shop.resource == "product"
    assert [f.key for f in shop.form_fields] == ["address", "phone"]
    assert [s.key for s in shop.statuses] == ["new", "sent", "done"]
    assert [a.key for a in shop.owner_actions] == ["send", "deliver"]
    events = next(c for c in outline.capabilities if c.key == "events")
    assert events.preset == "events"
    assert all(c.enabled and c.audience == "everyone" for c in outline.capabilities)


def test_patch_adds_orders_capability_to_example() -> None:
    spec = BotSpec.model_validate(load_json("workshop.botspec.json"))
    cap = orders_cap(resource="workshop", stock_field=None)
    new = apply_patch(
        spec,
        [
            PatchOp(op="add", path=["capabilities"], value=cap),
            PatchOp(
                op="add", path=["menu"], value={"key": "shop_menu", "label": "خرید", "capability": "shop"}
            ),
        ],
    )
    added = new.capability("shop")
    assert isinstance(added, OrdersCapability) and added.price_field == "price"
    disabled = apply_patch(new, [PatchOp(op="set", path=["capabilities", "shop", "enabled"], value=False)])
    assert disabled.capability("shop").enabled is False  # type: ignore[union-attr]
    restricted = apply_patch(
        new, [PatchOp(op="set", path=["capabilities", "shop", "audience"], value="staff")]
    )
    assert restricted.capability("shop").audience == "staff"  # type: ignore[union-attr]
    changes = diff_specs(new, disabled)
    assert [c.path for c in changes] == [["capabilities", "shop", "enabled"]]
    added_changes = diff_specs(spec, new)
    assert {c.kind for c in added_changes} == {"added"}


def test_compat_orders_status_removal_and_booking_preset() -> None:
    old = BotSpec.model_validate(business_data())
    data = business_data()
    shop = cap_of(data, "shop")
    shop["statuses"] = [s for s in STATUSES if s["key"] != "done"]
    shop["owner_actions"] = [OWNER_ACTIONS[0]]
    events = cap_of(data, "events")
    events["preset"] = "booking"
    events["category_field"] = None
    new = BotSpec.model_validate(data)
    assert not has_errors(validate_spec(new))
    found = {(i.code, tuple(i.path)) for i in check_compat(old, new, {"shop": 3, "events": 2})}
    assert ("status_removed_with_records", ("capabilities", "shop", "statuses", "done")) in found
    assert ("booking_preset_changed", ("capabilities", "events", "preset")) in found
    assert ("booking_category_changed", ("capabilities", "events", "category_field")) in found
    assert check_compat(old, new, {}) == []
    # Toggling enabled/audience never touches data.
    flags = business_data()
    cap_of(flags, "shop").update(enabled=False, audience="managers")
    assert check_compat(old, BotSpec.model_validate(flags), {"shop": 5}) == []
