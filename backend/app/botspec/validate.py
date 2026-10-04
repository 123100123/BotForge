"""Semantic validation of a BotSpec (frozen contract, WP0).

``validate_spec(spec)`` returns every semantic issue; errors block the build, warnings do not.
``parse_spec(data)`` runs Pydantic schema validation and converts its errors into SpecIssues with
key-addressed paths, so the agent's tools can return one issue format for both layers.

Issue codes (stable; the UI and tests key on them):
  schema_<pydantic type>   schema-level error from parse_spec (e.g. schema_missing,
                           schema_extra_forbidden, schema_string_pattern_mismatch)
  duplicate_key            key repeated within one collection
  reserved_key             a resource or capability uses the reserved key "menu"
  key_collision            a resource key equals a capability key (they share the record
                           collection namespace)
  unknown_resource         resource / item_resource reference does not exist
  unknown_capability       menu item references a missing capability
  unknown_field            title_field / detail_fields / start_field / upcoming_only_field /
                           sort_field / capacity.field missing on the resource
  field_type_mismatch      start_field / upcoming_only_field not datetime; capacity.field not integer
  capacity_field_not_required  per_item capacity field is optional on the resource
  capacity_mode_mismatch   capacity value/field inconsistent with mode
  capacity_value_invalid   fixed capacity value < 1
  choice_without_choices   choice field with fewer than two choices
  duplicate_choice         repeated choice
  choices_on_non_choice    non-choice field with choices
  invalid_default          FieldDef.default cannot be coerced to the field type
  datetime_form_field      form_fields contain a datetime field
  start_field_required     deadline_hours / closes_hours_before_start set without start_field
  value_out_of_range       negative hours, max_active_per_user < 1
  mine_view_unsupported    "mine" menu item on an info or catalog capability
  unknown_status           initial_status / from_statuses / to_status not in statuses
  callback_too_long        an owner action's callback data could exceed 64 bytes
  unknown_text_key         texts key not declared for the capability type
  invalid_placeholder      texts value uses a placeholder not whitelisted for its key
  menu_empty / menu_too_long / no_capabilities
  cancel_without_mine      (warning) booking allows cancellation but has no "mine" menu item
  capability_unreachable   (warning) capability not referenced by any menu item
"""

from collections import Counter
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.botspec.models import (
    AnyCapability,
    BookingCapability,
    BotSpec,
    CatalogCapability,
    FieldDef,
    FieldType,
    RequestCapability,
    Resource,
    TextOverride,
    capacity_problems,
    field_def_problems,
)
from app.botspec.records import RecordValueError, coerce_value
from app.botspec.text_keys import allowed_placeholders, placeholders_in
from app.runtime.callbacks import ACT_OWN, CallbackError, make_callback  # leaf module, no cycle

RESERVED_KEYS = frozenset({"menu"})
MAX_MENU_ITEMS = 8
# Largest record id we budget for in owner-action callback data ("own" arg = "<id>.<action>").
_MAX_RECORD_ID_TOKEN = "999999999999"


class SpecIssue(BaseModel):
    path: list[str]  # key-addressed, e.g. ["capabilities", "book_workshop", "capacity"]
    code: str  # stable snake_case code (see module docstring)
    message: str
    severity: Literal["error", "warning"] = "error"


def has_errors(issues: Iterable[SpecIssue]) -> bool:
    return any(i.severity == "error" for i in issues)


# --------------------------------------------------------------------------- schema layer


def _key_path(data: Any, loc: tuple[int | str, ...]) -> list[str]:
    """Convert a Pydantic error location on raw input to a key-addressed path."""
    path: list[str] = []
    node = data
    for seg in loc:
        if isinstance(seg, int):
            elem = node[seg] if isinstance(node, list) and 0 <= seg < len(node) else None
            key = elem.get("key") if isinstance(elem, dict) else None
            path.append(key if isinstance(key, str) else str(seg))
            node = elem
        else:
            if isinstance(node, dict) and seg not in node and node.get("type") == seg:
                continue  # discriminated-union tag inserted by Pydantic
            path.append(seg)
            node = node.get(seg) if isinstance(node, dict) else None
    return path


_OWN_CODES = {
    "capacity_mode_mismatch",
    "capacity_value_invalid",
    "choice_without_choices",
    "duplicate_choice",
    "choices_on_non_choice",
}


def schema_issues(data: Any, exc: ValidationError) -> list[SpecIssue]:
    issues = []
    for err in exc.errors(include_url=False):
        etype = err["type"]
        code = etype if etype in _OWN_CODES else f"schema_{etype}"
        issues.append(SpecIssue(path=_key_path(data, err["loc"]), code=code, message=err["msg"]))
    return issues


def parse_spec(data: Any) -> tuple[BotSpec | None, list[SpecIssue]]:
    """Schema-validate raw data. Returns (spec, []) or (None, schema issues)."""
    try:
        return BotSpec.model_validate(data), []
    except ValidationError as exc:
        return None, schema_issues(data, exc)


def check_spec(data: Any) -> list[SpecIssue]:
    """Schema validation followed by semantic validation (when the schema passes)."""
    spec, issues = parse_spec(data)
    return issues if spec is None else validate_spec(spec)


# --------------------------------------------------------------------------- semantic layer


class _Collector:
    def __init__(self) -> None:
        self.issues: list[SpecIssue] = []

    def error(self, path: list[str], code: str, message: str) -> None:
        self.issues.append(SpecIssue(path=path, code=code, message=message))

    def warn(self, path: list[str], code: str, message: str) -> None:
        self.issues.append(SpecIssue(path=path, code=code, message=message, severity="warning"))

    def unique(self, path: list[str], keys: Iterable[str], what: str) -> None:
        for key, n in Counter(keys).items():
            if n > 1:
                self.error([*path, key], "duplicate_key", f"{what} key '{key}' is used {n} times")


def _check_fields(c: _Collector, path: list[str], fields: list[FieldDef], *, form: bool) -> None:
    c.unique(path, (f.key for f in fields), "field")
    for f in fields:
        fpath = [*path, f.key]
        for code, msg in field_def_problems(f.type, f.choices):
            c.error(fpath, code, msg)
        if form and f.type == FieldType.datetime:
            c.error(fpath, "datetime_form_field", "form fields cannot be datetime (users never type dates)")
        if f.default is not None:
            try:
                coerce_value(f, f.default)
            except RecordValueError as exc:
                c.error([*fpath, "default"], "invalid_default", f"default is not a valid {f.type}: {exc}")


def _check_field_ref(
    c: _Collector,
    path: list[str],
    resource: Resource | None,
    field_key: str | None,
    *,
    want: FieldType | None = None,
) -> FieldDef | None:
    if field_key is None or resource is None:
        return None
    field = next((f for f in resource.fields if f.key == field_key), None)
    if field is None:
        c.error(path, "unknown_field", f"resource '{resource.key}' has no field '{field_key}'")
        return None
    if want is not None and field.type != want:
        c.error(
            path, "field_type_mismatch", f"field '{field_key}' must be {want.value}, not {field.type.value}"
        )
    return field


def _check_texts(c: _Collector, path: list[str], cap_type: str, texts: list[TextOverride]) -> None:
    c.unique(path, (t.key for t in texts), "text")
    for t in texts:
        allowed = allowed_placeholders(cap_type, t.key)
        if allowed is None:
            c.error([*path, t.key], "unknown_text_key", f"'{t.key}' is not a {cap_type} text key")
            continue
        bad = sorted(placeholders_in(t.value) - allowed)
        if bad:
            c.error(
                [*path, t.key, "value"],
                "invalid_placeholder",
                f"placeholders {bad} are not allowed for '{t.key}'; allowed: {sorted(allowed)}",
            )


def _check_resource_ref(c: _Collector, path: list[str], spec: BotSpec, key: str) -> Resource | None:
    resource = spec.resource(key)
    if resource is None:
        c.error(path, "unknown_resource", f"resource '{key}' does not exist")
    return resource


def _check_catalog(c: _Collector, spec: BotSpec, cap: CatalogCapability, base: list[str]) -> None:
    res = _check_resource_ref(c, [*base, "resource"], spec, cap.resource)
    for fk in cap.detail_fields:
        _check_field_ref(c, [*base, "detail_fields", fk], res, fk)
    _check_field_ref(c, [*base, "upcoming_only_field"], res, cap.upcoming_only_field, want=FieldType.datetime)
    _check_field_ref(c, [*base, "sort_field"], res, cap.sort_field)
    _check_texts(c, [*base, "texts"], cap.type, cap.texts)


def _check_booking(c: _Collector, spec: BotSpec, cap: BookingCapability, base: list[str]) -> None:
    res = _check_resource_ref(c, [*base, "resource"], spec, cap.resource)
    cpath = [*base, "capacity"]
    for code, msg in capacity_problems(cap.capacity.mode, cap.capacity.value, cap.capacity.field):
        c.error(cpath, code, msg)
    if cap.capacity.mode == "per_item":
        field = _check_field_ref(c, [*cpath, "field"], res, cap.capacity.field, want=FieldType.integer)
        if field is not None and not field.required:
            c.error(
                [*cpath, "field"],
                "capacity_field_not_required",
                f"capacity field '{field.key}' must be a required field",
            )
    _check_field_ref(c, [*base, "start_field"], res, cap.start_field, want=FieldType.datetime)
    for fk in cap.detail_fields:
        _check_field_ref(c, [*base, "detail_fields", fk], res, fk)
    _check_fields(c, [*base, "form_fields"], cap.form_fields, form=True)

    if cap.cancellation.deadline_hours is not None:
        dpath = [*base, "cancellation", "deadline_hours"]
        if cap.start_field is None:
            c.error(dpath, "start_field_required", "deadline_hours requires start_field")
        if cap.cancellation.deadline_hours < 0:
            c.error(dpath, "value_out_of_range", "deadline_hours must be >= 0")
    if cap.closes_hours_before_start is not None:
        cl_path = [*base, "closes_hours_before_start"]
        if cap.start_field is None:
            c.error(cl_path, "start_field_required", "closes_hours_before_start requires start_field")
        if cap.closes_hours_before_start < 0:
            c.error(cl_path, "value_out_of_range", "closes_hours_before_start must be >= 0")
    if cap.max_active_per_user is not None and cap.max_active_per_user < 1:
        c.error([*base, "max_active_per_user"], "value_out_of_range", "max_active_per_user must be >= 1")

    if cap.cancellation.enabled and not any(m.capability == cap.key and m.view == "mine" for m in spec.menu):
        c.warn(
            base,
            "cancel_without_mine",
            "cancellation is enabled but no 'mine' menu item lets users reach their bookings",
        )
    _check_texts(c, [*base, "texts"], cap.type, cap.texts)


def _check_request(c: _Collector, spec: BotSpec, cap: RequestCapability, base: list[str]) -> None:
    if cap.item_resource is not None:
        _check_resource_ref(c, [*base, "item_resource"], spec, cap.item_resource)
    _check_fields(c, [*base, "form_fields"], cap.form_fields, form=True)
    c.unique([*base, "statuses"], (s.key for s in cap.statuses), "status")
    c.unique([*base, "owner_actions"], (a.key for a in cap.owner_actions), "owner action")
    statuses = {s.key for s in cap.statuses}
    if cap.initial_status not in statuses:
        c.error(
            [*base, "initial_status"],
            "unknown_status",
            f"initial_status '{cap.initial_status}' is not a declared status",
        )
    for act in cap.owner_actions:
        apath = [*base, "owner_actions", act.key]
        for st in act.from_statuses:
            if st not in statuses:
                c.error([*apath, "from_statuses"], "unknown_status", f"status '{st}' is not declared")
        if act.to_status not in statuses:
            c.error([*apath, "to_status"], "unknown_status", f"status '{act.to_status}' is not declared")
        try:
            make_callback(cap.key, ACT_OWN, f"{_MAX_RECORD_ID_TOKEN}.{act.key}")
        except CallbackError:
            c.error(
                apath,
                "callback_too_long",
                "capability key + owner action key are too long for 64-byte callback data; shorten them",
            )
    _check_texts(c, [*base, "texts"], cap.type, cap.texts)


def validate_spec(spec: BotSpec) -> list[SpecIssue]:
    """Every semantic issue of a schema-valid spec, errors and warnings."""
    c = _Collector()

    # Keys and namespaces
    c.unique(["resources"], (r.key for r in spec.resources), "resource")
    c.unique(["capabilities"], (cap.key for cap in spec.capabilities), "capability")
    c.unique(["menu"], (m.key for m in spec.menu), "menu item")
    cap_keys = {cap.key for cap in spec.capabilities}
    for r in spec.resources:
        if r.key in RESERVED_KEYS:
            c.error(["resources", r.key], "reserved_key", f"'{r.key}' is a reserved key")
        if r.key in cap_keys:
            c.error(["resources", r.key], "key_collision", f"resource key '{r.key}' is also a capability key")
    for cap in spec.capabilities:
        if cap.key in RESERVED_KEYS:
            c.error(["capabilities", cap.key], "reserved_key", f"'{cap.key}' is a reserved key")

    # Resources
    for r in spec.resources:
        base = ["resources", r.key]
        _check_fields(c, [*base, "fields"], r.fields, form=False)
        _check_field_ref(c, [*base, "title_field"], r, r.title_field)

    # Capabilities
    if not spec.capabilities:
        c.error(["capabilities"], "no_capabilities", "the bot needs at least one capability")
    for cap in spec.capabilities:
        base = ["capabilities", cap.key]
        if cap.type == "info":
            c.unique([*base, "pages"], (p.key for p in cap.pages), "page")
        elif isinstance(cap, CatalogCapability):
            _check_catalog(c, spec, cap, base)
        elif isinstance(cap, BookingCapability):
            _check_booking(c, spec, cap, base)
        elif isinstance(cap, RequestCapability):
            _check_request(c, spec, cap, base)

    # Menu
    if not spec.menu:
        c.error(["menu"], "menu_empty", "the menu needs at least one item")
    elif len(spec.menu) > MAX_MENU_ITEMS:
        c.error(["menu"], "menu_too_long", f"the menu allows at most {MAX_MENU_ITEMS} items")
    by_key: dict[str, AnyCapability] = {cap.key: cap for cap in spec.capabilities}
    for m in spec.menu:
        target = by_key.get(m.capability)
        if target is None:
            c.error(
                ["menu", m.key, "capability"],
                "unknown_capability",
                f"capability '{m.capability}' does not exist",
            )
        elif m.view == "mine" and target.type not in ("booking", "request"):
            c.error(
                ["menu", m.key, "view"],
                "mine_view_unsupported",
                f"'mine' view needs a booking or request capability, not {target.type}",
            )
    referenced = {m.capability for m in spec.menu}
    for cap in spec.capabilities:
        if cap.key not in referenced:
            c.warn(
                ["capabilities", cap.key],
                "capability_unreachable",
                f"capability '{cap.key}' is not reachable from the menu",
            )
    return c.issues
