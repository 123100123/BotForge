"""BotSpec: the declarative, data-only description of one bot (frozen contract, WP0).

Structural rule: every collection is a list of objects with a unique ``key``; paths address
list elements by key, never by index. No free-form maps anywhere in this tree.

Model-level validators enforce only single-object constraints (Capacity consistency, choice
fields). They raise ``PydanticCustomError`` whose error type is the stable issue code, so
``validate.parse_spec`` reports them with the same codes ``validate_spec`` uses.
Cross-object rules live in ``validate.py``.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

SPEC_VERSION = 1
KEY_PATTERN = r"^[a-z][a-z0-9_]{0,23}$"
Key = Annotated[str, StringConstraints(pattern=KEY_PATTERN)]


class StrictModel(BaseModel):
    """Base for LLM-facing models: unknown properties are rejected, not silently dropped."""

    model_config = ConfigDict(extra="forbid")


class FieldType(StrEnum):
    text = "text"
    long_text = "long_text"
    integer = "integer"
    decimal = "decimal"
    datetime = "datetime"
    boolean = "boolean"
    choice = "choice"
    phone = "phone"


def field_def_problems(type_: FieldType, choices: list[str] | None) -> list[tuple[str, str]]:
    """Single-object FieldDef checks shared by the model validator and validate_spec."""
    problems: list[tuple[str, str]] = []
    if type_ == FieldType.choice:
        if choices is None or len(choices) < 2:
            problems.append(("choice_without_choices", "a choice field needs at least two choices"))
        elif len(set(choices)) != len(choices):
            problems.append(("duplicate_choice", "choices must be unique"))
    elif choices:
        problems.append(("choices_on_non_choice", "only choice fields may define choices"))
    return problems


class FieldDef(StrictModel):
    key: Key
    label: str  # Persian, shown to users and in the admin
    type: FieldType
    required: bool = True
    choices: list[str] | None = None  # required iff type == choice; [] counts as none
    default: str | None = None  # string form; coerced by type (checked by validate_spec)

    @model_validator(mode="after")
    def _check_choices(self) -> "FieldDef":
        for code, msg in field_def_problems(self.type, self.choices):
            raise PydanticCustomError(code, msg)
        return self


class Resource(StrictModel):  # owner-managed entity
    key: Key
    label: str
    label_plural: str
    fields: list[FieldDef]
    title_field: Key


class BotMeta(StrictModel):
    name: str
    welcome_text: str
    timezone: str = "Asia/Tehran"
    language: Literal["fa"] = "fa"


class TextOverride(StrictModel):
    key: str  # must be a text key declared in text_keys.TEXT_KEYS for the capability type
    value: str  # may use only that key's whitelisted {placeholders}


class InfoPage(StrictModel):
    key: Key
    title: str
    body: str


class InfoCapability(StrictModel):
    type: Literal["info"]
    key: Key
    title: str
    pages: list[InfoPage]


class CatalogCapability(StrictModel):
    type: Literal["catalog"]
    key: Key
    title: str
    resource: Key
    detail_fields: list[Key]
    upcoming_only_field: Key | None = None  # datetime field; hide past items
    sort_field: Key | None = None
    sort_desc: bool = False
    texts: list[TextOverride] = []


def capacity_problems(mode: str, value: int | None, field: str | None) -> list[tuple[str, str]]:
    """Single-object Capacity checks shared by the model validator and validate_spec."""
    if mode == "fixed":
        if value is None or field is not None:
            return [("capacity_mode_mismatch", "fixed capacity needs 'value' and no 'field'")]
        if value < 1:
            return [("capacity_value_invalid", "capacity value must be >= 1")]
    elif mode == "per_item" and (field is None or value is not None):
        return [("capacity_mode_mismatch", "per_item capacity needs 'field' and no 'value'")]
    return []


class Capacity(StrictModel):
    mode: Literal["fixed", "per_item"]
    value: int | None = None  # required iff fixed; >= 1
    field: Key | None = None  # required iff per_item; required integer field on the resource

    @model_validator(mode="after")
    def _check_mode(self) -> "Capacity":
        for code, msg in capacity_problems(self.mode, self.value, self.field):
            raise PydanticCustomError(code, msg)
        return self


class Waitlist(StrictModel):
    enabled: bool = False
    auto_promote: bool = True


class Cancellation(StrictModel):
    enabled: bool = True
    deadline_hours: int | None = None  # cancel refused when now > start - deadline_hours


class BookingCapability(StrictModel):
    type: Literal["booking"]
    key: Key
    title: str
    resource: Key  # the bookable items
    capacity: Capacity
    start_field: Key | None = None  # datetime field on the resource
    detail_fields: list[Key]
    form_fields: list[FieldDef] = []  # asked at booking; no datetime type
    one_active_per_user_per_item: bool = True
    max_active_per_user: int | None = None
    closes_hours_before_start: int | None = None
    waitlist: Waitlist = Waitlist()
    cancellation: Cancellation = Cancellation()
    notify_owner_on: list[Literal["booked", "waitlisted", "cancelled"]] = []
    notify_user_on: list[Literal["promoted"]] = ["promoted"]
    texts: list[TextOverride] = []


class StatusDef(StrictModel):
    key: Key
    label: str


class OwnerAction(StrictModel):
    key: Key
    label: str
    from_statuses: list[Key]
    to_status: Key


class RequestCapability(StrictModel):
    type: Literal["request"]
    key: Key
    title: str
    form_fields: list[FieldDef]
    item_resource: Key | None = None  # optional: pick one item from a resource
    statuses: list[StatusDef]
    initial_status: Key
    owner_actions: list[OwnerAction]
    notify_owner_on: list[Literal["submitted"]] = ["submitted"]
    notify_user_on: list[Literal["status_changed"]] = ["status_changed"]
    texts: list[TextOverride] = []


AnyCapability = InfoCapability | CatalogCapability | BookingCapability | RequestCapability
Capability = Annotated[AnyCapability, Field(discriminator="type")]


class MenuItem(StrictModel):
    key: Key
    label: str
    capability: Key
    view: Literal["main", "mine"] = "main"  # "mine" = my reservations / my requests


class BotSpec(StrictModel):
    spec_version: Literal[1] = 1
    bot: BotMeta
    resources: list[Resource]
    capabilities: list[Capability]
    menu: list[MenuItem]

    def capability(self, key: str) -> AnyCapability | None:
        return next((c for c in self.capabilities if c.key == key), None)

    def resource(self, key: str) -> Resource | None:
        return next((r for r in self.resources if r.key == key), None)
