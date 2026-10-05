"""Spec outline: the only view of a spec the acceptance-test author sees (frozen contract, WP0).

Contains keys, titles, labels, types and field definitions (including choices, needed to fill
forms). Deliberately omits every rule value: capacity, waitlist, cancellation, deadlines,
cutoffs, per-user limits, notifications, owner-action transitions, sort options, text overrides,
info page bodies. Acceptance scenarios must come from the owner's requirements, not the spec.

``enabled``/``audience`` are included: a disabled capability cannot be reached by users at all,
and a staff/managers capability can only be driven by the owner persona.
"""

from typing import Literal

from pydantic import BaseModel

from app.botspec.models import (
    Audience,
    BookingCapability,
    BotSpec,
    CatalogCapability,
    FieldDef,
    FieldType,
    InfoCapability,
    OrdersCapability,
    RequestCapability,
)

CapabilityType = Literal["info", "catalog", "booking", "request", "orders"]


class OutlineField(BaseModel):
    key: str
    label: str
    type: FieldType
    required: bool
    choices: list[str] | None = None


class OutlineResource(BaseModel):
    key: str
    label: str
    label_plural: str
    title_field: str
    fields: list[OutlineField]


class OutlineItem(BaseModel):  # info page, request/orders status, or owner action
    key: str
    label: str


class OutlineCapability(BaseModel):
    key: str
    type: CapabilityType
    title: str
    resource: str | None = None  # catalog/booking/orders resource, or request item_resource
    form_fields: list[OutlineField] = []  # booking/request form, orders checkout fields
    pages: list[OutlineItem] = []  # info
    statuses: list[OutlineItem] = []  # request, orders
    owner_actions: list[OutlineItem] = []  # request, orders
    preset: Literal["booking", "events"] | None = None  # booking only
    enabled: bool = True
    audience: Audience = "everyone"


class OutlineMenuItem(BaseModel):
    key: str
    label: str
    capability: str
    view: Literal["main", "mine"]


class SpecOutline(BaseModel):
    bot_name: str
    resources: list[OutlineResource]
    capabilities: list[OutlineCapability]
    menu: list[OutlineMenuItem]


def _fields(fields: list[FieldDef]) -> list[OutlineField]:
    return [
        OutlineField(key=f.key, label=f.label, type=f.type, required=f.required, choices=f.choices)
        for f in fields
    ]


def spec_outline(spec: BotSpec) -> SpecOutline:
    caps: list[OutlineCapability] = []
    for cap in spec.capabilities:
        oc = OutlineCapability(
            key=cap.key, type=cap.type, title=cap.title, enabled=cap.enabled, audience=cap.audience
        )
        if isinstance(cap, InfoCapability):
            oc.pages = [OutlineItem(key=p.key, label=p.title) for p in cap.pages]
        elif isinstance(cap, CatalogCapability):
            oc.resource = cap.resource
        elif isinstance(cap, BookingCapability):
            oc.resource = cap.resource
            oc.form_fields = _fields(cap.form_fields)
            oc.preset = cap.preset
        elif isinstance(cap, OrdersCapability):
            oc.resource = cap.resource
            oc.form_fields = _fields(cap.checkout_fields)
            oc.statuses = [OutlineItem(key=s.key, label=s.label) for s in cap.statuses]
            oc.owner_actions = [OutlineItem(key=a.key, label=a.label) for a in cap.owner_actions]
        elif isinstance(cap, RequestCapability):
            oc.resource = cap.item_resource
            oc.form_fields = _fields(cap.form_fields)
            oc.statuses = [OutlineItem(key=s.key, label=s.label) for s in cap.statuses]
            oc.owner_actions = [OutlineItem(key=a.key, label=a.label) for a in cap.owner_actions]
        caps.append(oc)
    return SpecOutline(
        bot_name=spec.bot.name,
        resources=[
            OutlineResource(
                key=r.key,
                label=r.label,
                label_plural=r.label_plural,
                title_field=r.title_field,
                fields=_fields(r.fields),
            )
            for r in spec.resources
        ],
        capabilities=caps,
        menu=[
            OutlineMenuItem(key=m.key, label=m.label, capability=m.capability, view=m.view) for m in spec.menu
        ],
    )
