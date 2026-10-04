import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.botspec.compat import check_compat
from app.botspec.models import BotSpec, FieldDef
from app.botspec.outline import spec_outline
from app.botspec.patch import PatchOp, apply_patch
from app.botspec.records import validate_record


def patched(spec: BotSpec, *raw: dict[str, Any]) -> BotSpec:
    return apply_patch(spec, [PatchOp.model_validate(r) for r in raw])


def codes(issues: list[Any]) -> list[tuple[str, str]]:
    return [(i.code, i.severity) for i in issues]


LIVE = {"workshop": 4, "book_workshop": 12}
NEW_FIELD = {
    "op": "add",
    "path": ["resources", "workshop", "fields"],
    "value": {"key": "room", "label": "کلاس", "type": "text", "required": True},
}

# ---------------------------------------------------------------- compat


def test_compat_clean_for_golden_modifications(workshop: BotSpec) -> None:
    up = patched(
        workshop, {"op": "set", "path": ["capabilities", "book_workshop", "capacity", "value"], "value": 12}
    )
    assert check_compat(workshop, up, LIVE) == []


def test_field_type_changed_is_error(workshop: BotSpec) -> None:
    new = patched(
        workshop,
        {"op": "set", "path": ["resources", "workshop", "fields", "price", "type"], "value": "decimal"},
    )
    issues = check_compat(workshop, new, {})
    assert codes(issues) == [("field_type_changed", "error")]
    assert issues[0].path == ["resources", "workshop", "fields", "price", "type"]


def test_required_field_without_default(workshop: BotSpec) -> None:
    new = patched(workshop, NEW_FIELD)
    assert codes(check_compat(workshop, new, LIVE)) == [("required_field_without_default", "error")]
    assert check_compat(workshop, new, {}) == []  # no records -> fine
    with_default = patched(workshop, {**NEW_FIELD, "value": {**NEW_FIELD["value"], "default": "۱"}})
    assert check_compat(workshop, with_default, LIVE) == []
    made_required = patched(
        workshop,
        {"op": "set", "path": ["resources", "workshop", "fields", "price", "required"], "value": True},
    )
    assert codes(check_compat(workshop, made_required, LIVE)) == [("required_field_without_default", "error")]


def test_removals_with_records_warn(workshop: BotSpec) -> None:
    no_price = patched(
        workshop,
        {"op": "remove", "path": ["resources", "workshop", "fields", "price"]},
        {
            "op": "set",
            "path": ["capabilities", "book_workshop", "detail_fields"],
            "value": ["description", "teacher", "starts_at"],
        },
    )
    assert codes(check_compat(workshop, no_price, LIVE)) == [("field_removed_with_records", "warning")]
    assert check_compat(workshop, no_price, {}) == []

    no_booking = patched(
        workshop,
        {"op": "remove", "path": ["menu", "workshops"]},
        {"op": "remove", "path": ["menu", "my_bookings"]},
        {"op": "remove", "path": ["capabilities", "book_workshop"]},
    )
    assert codes(check_compat(workshop, no_booking, LIVE)) == [("collection_removed_with_records", "warning")]


def test_capacity_lowered(workshop: BotSpec) -> None:
    down = patched(
        workshop, {"op": "set", "path": ["capabilities", "book_workshop", "capacity", "value"], "value": 8}
    )
    assert codes(check_compat(workshop, down, LIVE)) == [("capacity_lowered", "warning")]
    assert check_compat(workshop, down, {}) == []
    exact = {"book_workshop": 7}
    assert check_compat(workshop, down, LIVE, max_confirmed_per_item=exact) == []
    assert codes(check_compat(workshop, down, LIVE, max_confirmed_per_item={"book_workshop": 9})) == [
        ("capacity_lowered", "warning")
    ]


def test_request_status_removed(repair: BotSpec) -> None:
    new = patched(
        repair,
        {"op": "remove", "path": ["capabilities", "repair", "owner_actions", "mark_done"]},
        {"op": "remove", "path": ["capabilities", "repair", "statuses", "done"]},
    )
    assert codes(check_compat(repair, new, {"repair": 3})) == [("status_removed_with_records", "warning")]


# ---------------------------------------------------------------- outline


def test_outline_omits_rule_values(workshop: BotSpec, repair: BotSpec) -> None:
    out = spec_outline(workshop)
    dumped = json.dumps(out.model_dump(mode="json"), ensure_ascii=False)
    for forbidden in (
        "capacity",
        "waitlist",
        "cancellation",
        "deadline",
        "notify",
        "auto_promote",
        "one_active",
        "body",
        "آموزشگاه ما",
    ):
        assert forbidden not in dumped
    booking = next(c for c in out.capabilities if c.key == "book_workshop")
    assert booking.type == "booking" and booking.resource == "workshop"
    assert [(f.key, f.type) for f in out.resources[0].fields] == [
        ("title", "text"),
        ("description", "long_text"),
        ("teacher", "text"),
        ("starts_at", "datetime"),
        ("price", "integer"),
    ]
    assert [m.view for m in out.menu] == ["main", "mine", "main"]

    rout = spec_outline(repair)
    req = rout.capabilities[0]
    assert [s.key for s in req.statuses] == ["new", "approved", "rejected", "done"]
    assert [a.key for a in req.owner_actions] == ["approve", "reject", "mark_done"]
    rdump = json.dumps(rout.model_dump(mode="json"))
    assert "from_statuses" not in rdump and "to_status" not in rdump and "initial_status" not in rdump


# ---------------------------------------------------------------- records


def fd(key: str, type_: str, **kw: Any) -> FieldDef:
    return FieldDef.model_validate({"key": key, "label": key, "type": type_, **kw})


@pytest.mark.parametrize(
    ("type_", "raw", "expected", "extra"),
    [
        ("integer", "۱۲", 12, {}),
        ("integer", "١٢", 12, {}),
        ("integer", "۱٬۵۰۰٬۰۰۰", 1500000, {}),
        ("integer", "1,500,000", 1500000, {}),
        ("integer", 7, 7, {}),
        ("decimal", "۱٫۵", 1.5, {}),
        ("decimal", "2.25", 2.25, {}),
        ("boolean", "بله", True, {}),
        ("boolean", "خیر", False, {}),
        ("boolean", True, True, {}),
        ("phone", "۰۹۱۲ ۳۴۵ ۶۷۸۹", "09123456789", {}),
        ("phone", "0098-912-345-6789", "+989123456789", {}),
        ("choice", " صبح ", "صبح", {"choices": ["صبح", "عصر"]}),
        ("text", "  سلام ", "سلام", {}),
        ("datetime", "2026-10-06T18:00:00+03:30", "2026-10-06T14:30:00+00:00", {}),
        ("datetime", "۲۰۲۶-۱۰-۰۶T۱۴:۳۰:۰۰Z", "2026-10-06T14:30:00+00:00", {}),
        ("datetime", datetime(2026, 10, 6, 14, 30, 5, 123, tzinfo=UTC), "2026-10-06T14:30:05+00:00", {}),
    ],
)
def test_coercion(type_: str, raw: Any, expected: Any, extra: dict[str, Any]) -> None:
    cleaned, errors = validate_record([fd("f", type_, **extra)], {"f": raw})
    assert errors == []
    assert cleaned == {"f": expected}


@pytest.mark.parametrize(
    ("type_", "raw", "extra"),
    [
        ("integer", "دوازده", {}),
        ("integer", "1.5", {}),
        ("integer", True, {}),
        ("decimal", "nan", {}),
        ("boolean", "شاید", {}),
        ("phone", "abc", {}),
        ("phone", "۱۲۳", {}),
        ("choice", "شب", {"choices": ["صبح", "عصر"]}),
        ("datetime", "2026-10-06T14:30:00", {}),  # naive
        ("datetime", "فردا", {}),
    ],
)
def test_coercion_errors(type_: str, raw: Any, extra: dict[str, Any]) -> None:
    cleaned, errors = validate_record([fd("f", type_, label="فیلد", **extra)], {"f": raw})
    assert len(errors) == 1 and "«فیلد»" in errors[0]
    assert "f" not in cleaned


def test_required_default_optional_unknown() -> None:
    fields = [
        fd("name", "text", label="نام"),
        fd("seats", "integer", default="۳"),
        fd("note", "long_text", required=False),
    ]
    cleaned, errors = validate_record(fields, {"name": "  ", "extra": "x"})
    assert errors == ["«نام» الزامی است."]
    assert cleaned == {"name": None, "seats": 3, "note": None}
