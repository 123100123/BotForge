from typing import Any

import pytest

from app.botspec.diff import affected_capabilities, diff_specs
from app.botspec.models import BookingCapability, BotSpec
from app.botspec.patch import PatchError, PatchOp, apply_patch

CAPACITY_12 = {"op": "set", "path": ["capabilities", "book_workshop", "capacity", "value"], "value": 12}
DEADLINE_2 = {
    "op": "set",
    "path": ["capabilities", "book_workshop", "cancellation", "deadline_hours"],
    "value": 2,
}
ADD_PHONE = {
    "op": "add",
    "path": ["capabilities", "book_workshop", "form_fields"],
    "value": {"key": "phone", "label": "شماره تماس", "type": "phone", "required": True},
}
REMOVE_ABOUT = {"op": "remove", "path": ["menu", "about"]}


def ops(*raw: dict[str, Any]) -> list[PatchOp]:
    return [PatchOp.model_validate(r) for r in raw]


def book(spec: BotSpec) -> BookingCapability:
    cap = spec.capability("book_workshop")
    assert isinstance(cap, BookingCapability)
    return cap


def test_roadmap_examples_apply(workshop: BotSpec) -> None:
    new = apply_patch(workshop, ops(CAPACITY_12, DEADLINE_2, ADD_PHONE, REMOVE_ABOUT))
    assert book(new).capacity.value == 12
    assert book(new).cancellation.deadline_hours == 2
    assert [f.key for f in book(new).form_fields] == ["phone"]
    assert [m.key for m in new.menu] == ["workshops", "my_bookings"]
    # input untouched
    assert book(workshop).capacity.value == 10 and len(workshop.menu) == 3


def test_patch_is_atomic(workshop: BotSpec) -> None:
    before = workshop.model_dump()
    bad = {"op": "set", "path": ["capabilities", "nope", "title"], "value": "x"}
    with pytest.raises(PatchError) as exc:
        apply_patch(workshop, ops(CAPACITY_12, bad))
    assert exc.value.op_index == 1 and exc.value.code == "path_not_found"
    assert workshop.model_dump() == before


def test_result_revalidated_schema_and_semantic(workshop: BotSpec) -> None:
    with pytest.raises(PatchError) as exc:
        apply_patch(workshop, ops({**CAPACITY_12, "value": 0}))
    assert exc.value.op_index is None and exc.value.code == "invalid_spec"
    assert [i.code for i in exc.value.issues] == ["capacity_value_invalid"]

    with pytest.raises(PatchError) as exc:
        apply_patch(
            workshop,
            ops(DEADLINE_2, {"op": "remove", "path": ["capabilities", "book_workshop", "start_field"]}),
        )
    assert [i.code for i in exc.value.issues] == ["start_field_required"]


def test_golden_modification_capacity(workshop: BotSpec) -> None:
    new = apply_patch(workshop, ops(CAPACITY_12))
    changes = diff_specs(workshop, new)
    assert [(c.path, c.kind, c.old, c.new, c.label_fa) for c in changes] == [
        (["capabilities", "book_workshop", "capacity", "value"], "changed", 10, 12, "ظرفیت: ۱۰ ← ۱۲")
    ]
    assert affected_capabilities(changes) == ["book_workshop"]


def test_golden_modification_deadline(workshop: BotSpec) -> None:
    new = apply_patch(workshop, ops(DEADLINE_2))
    changes = diff_specs(workshop, new)
    assert [(c.path, c.kind, c.old, c.new) for c in changes] == [
        (["capabilities", "book_workshop", "cancellation", "deadline_hours"], "changed", None, 2)
    ]
    assert changes[0].label_fa == "مهلت لغو ثبت‌نام: بدون محدودیت ← تا ۲ ساعت قبل از شروع"


def test_diff_added_removed_and_identical(workshop: BotSpec) -> None:
    assert diff_specs(workshop, workshop) == []
    new = apply_patch(workshop, ops(ADD_PHONE, REMOVE_ABOUT))
    changes = {(tuple(c.path), c.kind): c for c in diff_specs(workshop, new)}
    assert set(changes) == {
        (("capabilities", "book_workshop", "form_fields", "phone"), "added"),
        (("menu", "about"), "removed"),
    }
    assert changes[(("menu", "about"), "removed")].label_fa == "حذف شد: گزینهٔ منو «دربارهٔ ما»"
    assert (
        "شماره تماس" in changes[(("capabilities", "book_workshop", "form_fields", "phone"), "added")].label_fa
    )


def test_diff_nested_context_and_order(workshop: BotSpec) -> None:
    new = apply_patch(
        workshop,
        ops(
            {"op": "set", "path": ["capabilities", "info", "pages", "address", "title"], "value": "نشانی"},
            {"op": "remove", "path": ["menu", "workshops"]},
            {
                "op": "add",
                "path": ["menu"],
                "before": "about",
                "value": {"key": "workshops", "label": "کارگاه‌ها و ثبت‌نام", "capability": "book_workshop"},
            },
        ),
    )
    changes = diff_specs(workshop, new)
    labels = {tuple(c.path): c.label_fa for c in changes}
    assert labels[("capabilities", "info", "pages", "address", "title")] == (
        "صفحه «نشانی» — عنوان: «نشانی و تماس» ← «نشانی»"
    )
    order = next(c for c in changes if c.path == ["menu"])
    assert order.old == ["workshops", "my_bookings", "about"]
    assert order.new == ["my_bookings", "workshops", "about"]


def test_key_rename_refused(workshop: BotSpec) -> None:
    with pytest.raises(PatchError) as exc:
        apply_patch(workshop, ops({"op": "set", "path": ["menu", "about", "key"], "value": "info"}))
    assert exc.value.code == "key_change_forbidden"
    whole = {"key": "contact", "label": "تماس", "capability": "info", "view": "main"}
    with pytest.raises(PatchError) as exc:
        apply_patch(workshop, ops({"op": "set", "path": ["menu", "about"], "value": whole}))
    assert exc.value.code == "key_change_forbidden"


def test_capability_type_change_refused(workshop: BotSpec) -> None:
    with pytest.raises(PatchError) as exc:
        apply_patch(
            workshop, ops({"op": "set", "path": ["capabilities", "info", "type"], "value": "catalog"})
        )
    assert exc.value.code == "type_change_forbidden"
    catalog = {"type": "catalog", "key": "info", "title": "x", "resource": "workshop", "detail_fields": []}
    with pytest.raises(PatchError) as exc:
        apply_patch(workshop, ops({"op": "set", "path": ["capabilities", "info"], "value": catalog}))
    assert exc.value.code == "type_change_forbidden"


def test_field_type_change_is_a_patch_but_compat_flags_it(workshop: BotSpec) -> None:
    new = apply_patch(
        workshop,
        ops({"op": "set", "path": ["resources", "workshop", "fields", "price", "type"], "value": "decimal"}),
    )
    assert new.resources[0].fields[4].type == "decimal"


def test_set_whole_sub_object_and_element(workshop: BotSpec) -> None:
    new = apply_patch(
        workshop,
        ops(
            {
                "op": "set",
                "path": ["capabilities", "book_workshop", "waitlist"],
                "value": {"enabled": False, "auto_promote": False},
            },
            {
                "op": "set",
                "path": ["menu", "about"],
                "value": {"key": "about", "label": "تماس با ما", "capability": "info", "view": "main"},
            },
            {"op": "set", "path": ["capabilities", "book_workshop", "notify_owner_on"], "value": ["booked"]},
        ),
    )
    assert book(new).waitlist.enabled is False
    assert new.menu[2].label == "تماس با ما"
    assert book(new).notify_owner_on == ["booked"]


@pytest.mark.parametrize(
    ("op", "code"),
    [
        ({"op": "set", "path": ["menu"], "value": []}, "invalid_target"),
        (
            {"op": "add", "path": ["capabilities", "book_workshop", "detail_fields"], "value": "title"},
            "invalid_target",
        ),
        (
            {
                "op": "set",
                "path": ["capabilities", "book_workshop", "detail_fields", "teacher"],
                "value": "x",
            },
            "invalid_target",
        ),
        ({"op": "remove", "path": ["capabilities", "book_workshop", "title"]}, "invalid_target"),
        ({"op": "remove", "path": ["menu"]}, "invalid_target"),
        (
            {"op": "add", "path": ["menu"], "value": {"key": "about", "label": "x", "capability": "info"}},
            "duplicate_key",
        ),
        ({"op": "add", "path": ["menu"], "value": {"label": "x", "capability": "info"}}, "invalid_op"),
        (
            {
                "op": "add",
                "path": ["menu"],
                "before": "nope",
                "value": {"key": "x", "label": "x", "capability": "info"},
            },
            "path_not_found",
        ),
        ({"op": "add", "path": ["menu", "about"], "value": {"key": "x"}}, "invalid_target"),
        ({"op": "set", "path": ["capabilities", "book_workshop", "price"], "value": 1}, "path_not_found"),
        ({"op": "set", "path": [], "value": {}}, "invalid_target"),
        ({"op": "set", "path": ["menu", "about", "label"], "value": "x", "before": "y"}, "invalid_op"),
    ],
)
def test_invalid_ops(workshop: BotSpec, op: dict[str, Any], code: str) -> None:
    with pytest.raises(PatchError) as exc:
        apply_patch(workshop, ops(op))
    assert exc.value.code == code and exc.value.op_index == 0


def test_remove_optional_scalar_sets_null(workshop: BotSpec) -> None:
    patched = apply_patch(workshop, ops(DEADLINE_2))
    new = apply_patch(
        patched,
        ops({"op": "remove", "path": ["capabilities", "book_workshop", "cancellation", "deadline_hours"]}),
    )
    assert book(new).cancellation.deadline_hours is None
    assert diff_specs(workshop, new) == []


def test_malformed_op_dict_reports_index(workshop: BotSpec) -> None:
    with pytest.raises(PatchError) as exc:
        apply_patch(workshop, [PatchOp.model_validate(CAPACITY_12), {"op": "move", "path": []}])  # type: ignore[list-item]
    assert exc.value.op_index == 1 and exc.value.code == "invalid_op"


def test_diff_capability_type_replaced(workshop_data: dict[str, Any], workshop: BotSpec) -> None:
    workshop_data["capabilities"][0] = {
        "type": "catalog",
        "key": "info",
        "title": "فهرست",
        "resource": "workshop",
        "detail_fields": [],
    }
    changes = diff_specs(workshop, BotSpec.model_validate(workshop_data))
    assert [(c.path, c.kind) for c in changes] == [(["capabilities", "info"], "changed")]
    assert changes[0].label_fa == "قابلیت «info» جایگزین شد: «دربارهٔ ما» ← «فهرست»"
