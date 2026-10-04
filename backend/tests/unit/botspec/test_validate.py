from collections.abc import Callable
from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.text_keys import TEXT_KEYS, fill_text
from app.botspec.validate import check_spec, has_errors, parse_spec, validate_spec

Mutator = Callable[[dict[str, Any]], None]


def cap(d: dict[str, Any], key: str) -> dict[str, Any]:
    return next(c for c in d["capabilities"] if c["key"] == key)


def menu(d: dict[str, Any], key: str) -> dict[str, Any]:
    return next(m for m in d["menu"] if m["key"] == key)


def booking(d: dict[str, Any]) -> dict[str, Any]:
    return cap(d, "book_workshop")


def field(name: str, type_: str, **kw: Any) -> dict[str, Any]:
    return {"key": name, "label": name, "type": type_, **kw}


def test_golden_specs_have_zero_issues(workshop: BotSpec, repair: BotSpec) -> None:
    assert validate_spec(workshop) == []
    assert validate_spec(repair) == []


def test_parse_spec_roundtrip(workshop_data: dict[str, Any]) -> None:
    spec, issues = parse_spec(workshop_data)
    assert issues == [] and spec is not None
    assert BotSpec.model_validate(spec.model_dump(mode="json")) == spec


def _set(path: list[str], value: Any) -> Mutator:
    def m(d: dict[str, Any]) -> None:
        node = booking(d)
        for seg in path[:-1]:
            node = node[seg]
        node[path[-1]] = value

    return m


def _key_collision(d: dict[str, Any]) -> None:
    cap(d, "info")["key"] = "workshop"
    menu(d, "about")["capability"] = "workshop"


def _reserved(d: dict[str, Any]) -> None:
    cap(d, "info")["key"] = "menu"
    menu(d, "about")["capability"] = "menu"


def _many_menu(d: dict[str, Any]) -> None:
    d["menu"] = [
        {"key": f"m{i}", "label": "x", "capability": "book_workshop", "view": "main"} for i in range(9)
    ]


def _per_item_optional(d: dict[str, Any]) -> None:
    booking(d)["capacity"] = {"mode": "per_item", "value": None, "field": "price"}


def _per_item_text(d: dict[str, Any]) -> None:
    booking(d)["capacity"] = {"mode": "per_item", "value": None, "field": "title"}


WORKSHOP_NEGATIVE: list[tuple[str, Mutator, str, list[str] | None]] = [
    (
        "duplicate menu key",
        lambda d: d["menu"].append(dict(d["menu"][0])),
        "duplicate_key",
        ["menu", "workshops"],
    ),
    (
        "duplicate field key",
        lambda d: d["resources"][0]["fields"].append(field("title", "text")),
        "duplicate_key",
        ["resources", "workshop", "fields", "title"],
    ),
    (
        "unknown resource",
        _set(["resource"], "course"),
        "unknown_resource",
        ["capabilities", "book_workshop", "resource"],
    ),
    (
        "unknown capability",
        lambda d: menu(d, "about").update(capability="nope"),
        "unknown_capability",
        ["menu", "about", "capability"],
    ),
    (
        "unknown detail field",
        _set(["detail_fields"], ["description", "room"]),
        "unknown_field",
        ["capabilities", "book_workshop", "detail_fields", "room"],
    ),
    (
        "unknown title field",
        lambda d: d["resources"][0].update(title_field="name"),
        "unknown_field",
        ["resources", "workshop", "title_field"],
    ),
    (
        "start field not datetime",
        _set(["start_field"], "title"),
        "field_type_mismatch",
        ["capabilities", "book_workshop", "start_field"],
    ),
    (
        "capacity field not integer",
        _per_item_text,
        "field_type_mismatch",
        ["capabilities", "book_workshop", "capacity", "field"],
    ),
    ("capacity field optional", _per_item_optional, "capacity_field_not_required", None),
    (
        "fixed capacity without value",
        _set(["capacity", "value"], None),
        "capacity_mode_mismatch",
        ["capabilities", "book_workshop", "capacity"],
    ),
    ("fixed capacity with field", _set(["capacity", "field"], "price"), "capacity_mode_mismatch", None),
    ("capacity zero", _set(["capacity", "value"], 0), "capacity_value_invalid", None),
    (
        "choice with one choice",
        lambda d: d["resources"][0]["fields"].append(field("level", "choice", choices=["مقدماتی"])),
        "choice_without_choices",
        ["resources", "workshop", "fields", "level"],
    ),
    (
        "choices on text field",
        lambda d: d["resources"][0]["fields"][0].update(choices=["a", "b"]),
        "choices_on_non_choice",
        None,
    ),
    (
        "datetime form field",
        _set(["form_fields"], [field("when", "datetime")]),
        "datetime_form_field",
        ["capabilities", "book_workshop", "form_fields", "when"],
    ),
    (
        "deadline without start field",
        lambda d: (_set(["start_field"], None)(d), _set(["cancellation", "deadline_hours"], 2)(d)),
        "start_field_required",
        ["capabilities", "book_workshop", "cancellation", "deadline_hours"],
    ),
    (
        "cutoff without start field",
        lambda d: (_set(["start_field"], None)(d), _set(["closes_hours_before_start"], 3)(d)),
        "start_field_required",
        None,
    ),
    ("negative deadline", _set(["cancellation", "deadline_hours"], -1), "value_out_of_range", None),
    ("zero per-user limit", _set(["max_active_per_user"], 0), "value_out_of_range", None),
    (
        "invalid default",
        lambda d: d["resources"][0]["fields"][4].update(default="ارزان"),
        "invalid_default",
        ["resources", "workshop", "fields", "price", "default"],
    ),
    (
        "mine on info",
        lambda d: menu(d, "about").update(view="mine"),
        "mine_view_unsupported",
        ["menu", "about", "view"],
    ),
    (
        "unknown text key",
        _set(["texts"], [{"key": "hello", "value": "سلام"}]),
        "unknown_text_key",
        ["capabilities", "book_workshop", "texts", "hello"],
    ),
    (
        "bad placeholder",
        _set(["texts"], [{"key": "confirmed", "value": "ثبت شد {user}"}]),
        "invalid_placeholder",
        ["capabilities", "book_workshop", "texts", "confirmed", "value"],
    ),
    ("empty menu", lambda d: d.update(menu=[]), "menu_empty", None),
    ("menu too long", _many_menu, "menu_too_long", None),
    ("no capabilities", lambda d: d.update(capabilities=[], menu=[]), "no_capabilities", None),
    ("resource/capability key collision", _key_collision, "key_collision", ["resources", "workshop"]),
    ("reserved key", _reserved, "reserved_key", ["capabilities", "menu"]),
    # schema layer
    (
        "extra property",
        lambda d: booking(d).update(price_rule="x"),
        "schema_extra_forbidden",
        ["capabilities", "book_workshop", "price_rule"],
    ),
    (
        "bad key pattern",
        lambda d: menu(d, "about").update(key="About Us"),
        "schema_string_pattern_mismatch",
        ["menu", "About Us", "key"],
    ),
    (
        "unknown capability type",
        lambda d: cap(d, "info").update(type="faq"),
        "schema_union_tag_invalid",
        None,
    ),
]


@pytest.mark.parametrize(
    ("mutate", "code", "path"),
    [pytest.param(m, c, p, id=name) for name, m, c, p in WORKSHOP_NEGATIVE],
)
def test_negative_workshop(
    workshop_data: dict[str, Any], mutate: Mutator, code: str, path: list[str] | None
) -> None:
    mutate(workshop_data)
    issues = check_spec(workshop_data)
    matching = [i for i in issues if i.code == code]
    assert matching, f"expected {code}, got {[(i.code, i.path) for i in issues]}"
    assert all(i.severity == "error" for i in matching)
    if path is not None:
        assert path in [i.path for i in matching]


def test_unknown_status(repair_data: dict[str, Any]) -> None:
    repair_data["capabilities"][0]["initial_status"] = "pending"
    repair_data["capabilities"][0]["owner_actions"][2]["to_status"] = "closed"
    issues = check_spec(repair_data)
    paths = {tuple(i.path) for i in issues if i.code == "unknown_status"}
    assert paths == {
        ("capabilities", "repair", "initial_status"),
        ("capabilities", "repair", "owner_actions", "mark_done", "to_status"),
    }


def test_callback_too_long(repair_data: dict[str, Any]) -> None:
    long_cap = "r" * 24
    repair_data["capabilities"][0]["key"] = long_cap
    for m in repair_data["menu"]:
        if m["capability"] == "repair":
            m["capability"] = long_cap
    repair_data["capabilities"][0]["owner_actions"][0]["key"] = "a" * 24
    issues = check_spec(repair_data)
    codes = [(i.code, i.path) for i in issues]
    assert ("callback_too_long", ["capabilities", long_cap, "owner_actions", "a" * 24]) in codes
    # the shorter action keys still fit
    assert sum(1 for c, _ in codes if c == "callback_too_long") == 1


def test_item_resource_must_exist(repair_data: dict[str, Any]) -> None:
    repair_data["capabilities"][0]["item_resource"] = "appliance"
    assert "unknown_resource" in {i.code for i in check_spec(repair_data)}


def test_cancel_without_mine_is_warning(workshop_data: dict[str, Any]) -> None:
    workshop_data["menu"] = [m for m in workshop_data["menu"] if m["key"] != "my_bookings"]
    issues = check_spec(workshop_data)
    assert [(i.code, i.severity) for i in issues] == [("cancel_without_mine", "warning")]
    assert not has_errors(issues)


def test_unreachable_capability_is_warning(workshop_data: dict[str, Any]) -> None:
    workshop_data["menu"] = [m for m in workshop_data["menu"] if m["key"] != "about"]
    issues = check_spec(workshop_data)
    assert [(i.code, i.severity, i.path) for i in issues] == [
        ("capability_unreachable", "warning", ["capabilities", "info"])
    ]


def test_valid_text_override_passes(workshop_data: dict[str, Any]) -> None:
    booking(workshop_data)["texts"] = [
        {"key": "waitlisted", "value": "ظرفیت «{title}» پر است؛ نفر {position} لیست انتظار هستید."}
    ]
    assert check_spec(workshop_data) == []


def test_text_registry_covers_all_types() -> None:
    assert set(TEXT_KEYS) == {"info", "catalog", "booking", "request"}
    for key in (
        "confirmed",
        "waitlisted",
        "full",
        "duplicate",
        "cancelled",
        "promoted",
        "cancel_deadline_passed",
        "owner_booked",
    ):
        assert key in TEXT_KEYS["booking"]
    for key in ("ask_field", "submitted", "status_changed", "owner_submitted", "not_allowed"):
        assert key in TEXT_KEYS["request"]


def test_fill_text_is_single_pass_literal() -> None:
    assert fill_text("{title} - {user}", {"title": "{user}", "user": "علی"}) == "{user} - علی"
    assert fill_text("{x} {missing}", {"x": "1"}) == "1 {missing}"
