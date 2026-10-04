"""Derived scenarios (WP3): deterministic tests generated from each capability's configuration.

``derive_scenarios(spec)`` turns the rules a spec configures into scenarios the runtime must
honor. Every template is emitted only when the configuration makes it meaningful, and each is
written to hold for ANY valid spec: a derived test that fails must mean a real bug, never a wrong
test (the repair loop would chase it).

Ids are stable: ``derived:<capability_key>:<template>``; ``source="derived"``; no requirement ids.

Booking mechanism templates run at capacity 2 (``capacity_override: 2`` in fixed mode, a seeded
capacity field of 2 in per_item mode). Only expectations the roadmap specifies are asserted:
notifications to the owner follow ``notify_owner_on``, promotion notices follow ``notify_user_on``.

Seeds are synthesized from the resource's FieldDefs. Times are relative to the runner's start
clock; the start field is placed far enough ahead that the configured cutoff and cancellation
deadline do not interfere with the scenario's first steps.

Extension point: ``TEMPLATES`` maps a capability type to ``fn(spec, cap) -> list[Scenario]``;
a later package registers ``request`` templates with ``register_templates("request", fn)``.
"""

from collections.abc import Callable
from typing import Any

from app.botspec.models import (
    BookingCapability,
    BotSpec,
    CatalogCapability,
    FieldDef,
    FieldType,
    InfoCapability,
    Resource,
)
from app.botspec.records import validate_record
from app.runtime import formatting
from app.testing.runner import START_CLOCK
from app.testing.scenario import KV, Scenario, SeedRecord, Step, resolve_relative

Template = Callable[[BotSpec, Any], list[Scenario]]

OVERRIDE_CAPACITY = 2
BASE_START_HOURS = 72
MAX_LIMIT_ITEMS = 10  # per-user limit template: skip when the limit is larger than this
MAX_CONFIGURED_CAPACITY = 30  # configured-capacity template: skip above this


# --- seeds ---------------------------------------------------------------------------------------


def _field_value(field: FieldDef, n: int, hours: int, unique: bool) -> str:
    """A valid synthetic string value for ``field``; ``unique`` makes it differ per item ``n``."""
    t = field.type
    if t == FieldType.text:
        return f"مورد {formatting.to_persian_digits(n)}" if unique else "نمونه"
    if t == FieldType.long_text:
        return f"توضیح نمونه {n}" if unique else "توضیح نمونه"
    if t == FieldType.integer:
        return str(100 + n) if unique else "5"
    if t == FieldType.decimal:
        return f"{n}.5" if unique else "1.5"
    if t == FieldType.boolean:
        return "true"
    if t == FieldType.choice:
        return (field.choices or [""])[0]
    if t == FieldType.phone:
        return f"0912{n:07d}" if unique else "09120000000"
    return f"+{hours + (n if unique else 0)}h"  # datetime


def _seed_record(
    resource: Resource, ref: str, n: int, hours: int, overrides: dict[str, str] | None = None
) -> SeedRecord:
    values = []
    for field in resource.fields:
        if overrides and field.key in overrides:
            value = overrides[field.key]
        else:
            value = _field_value(field, n, hours, unique=field.key == resource.title_field)
        values.append(KV(key=field.key, value=value))
    return SeedRecord(ref=ref, collection=resource.key, values=values)


def _rendered_title(spec: BotSpec, resource: Resource, seed: SeedRecord) -> str:
    """The title the bot shows for ``seed`` (the same rendering the runtime uses)."""
    raw = {kv.key: resolve_relative(kv.value, START_CLOCK) for kv in seed.values}
    cleaned, _ = validate_record(resource.fields, raw)
    field = next(f for f in resource.fields if f.key == resource.title_field)
    return formatting.format_field_value(field, cleaned.get(resource.title_field), spec.bot.timezone)


def _form_values(cap: BookingCapability) -> list[KV]:
    """Valid answers for the required form fields (optional ones are left to `skip`)."""
    out = []
    for field in cap.form_fields:
        if not field.required:
            continue
        t = field.type
        if t == FieldType.choice:
            value = (field.choices or [""])[0]
        elif t == FieldType.boolean:
            value = "true"
        elif t == FieldType.integer:
            value = "3"
        elif t == FieldType.decimal:
            value = "1.5"
        elif t == FieldType.phone:
            value = "09120000000"
        elif t == FieldType.long_text:
            value = "توضیح نمونه"
        else:
            value = "نمونه"
        out.append(KV(key=field.key, value=value))
    return out


def _has_menu(spec: BotSpec, cap_key: str, view: str) -> bool:
    return any(m.capability == cap_key and m.view == view for m in spec.menu)


# --- booking -------------------------------------------------------------------------------------


class _Booking:
    """Builder for the scenarios of one booking capability."""

    def __init__(self, spec: BotSpec, cap: BookingCapability, resource: Resource) -> None:
        self.spec = spec
        self.cap = cap
        self.resource = resource
        gap = max(cap.closes_hours_before_start or 0, cap.cancellation.deadline_hours or 0)
        self.start_hours = BASE_START_HOURS + gap
        self.override = OVERRIDE_CAPACITY if cap.capacity.mode == "fixed" else None
        self.form = _form_values(cap)
        self.out: list[Scenario] = []

    # seeds
    def seeds(self, count: int = 1, capacity: int = OVERRIDE_CAPACITY) -> list[SeedRecord]:
        overrides: dict[str, str] = {}
        if self.cap.start_field:
            overrides[self.cap.start_field] = f"+{self.start_hours}h"
        if self.cap.capacity.mode == "per_item" and self.cap.capacity.field:
            overrides[self.cap.capacity.field] = str(capacity)
        return [
            _seed_record(self.resource, f"i{n}", n, self.start_hours, overrides) for n in range(1, count + 1)
        ]

    # steps
    def book(self, actor: str, item: str, expect: str, reason: str | None = None) -> Step:
        return Step.model_validate(
            {
                "do": "book",
                "actor": actor,
                "capability": self.cap.key,
                "item": item,
                "expect": expect,
                "reason": reason,
                "form": [kv.model_dump() for kv in self.form],
            }
        )

    def cancel(self, actor: str, item: str, expect: str, reason: str | None = None) -> Step:
        return Step(
            do="cancel", actor=actor, capability=self.cap.key, item=item, expect=expect, reason=reason
        )

    def owner_cancel(self, target: str, item: str) -> Step:
        return Step(
            do="owner_action",
            capability=self.cap.key,
            action="cancel",
            target_actor=target,
            item=item,
            expect="ok",
        )

    def booking(self, actor: str, item: str, expect: str) -> Step:
        return Step(do="expect_booking", actor=actor, capability=self.cap.key, item=item, expect=expect)

    def counts(self, item: str, confirmed: int, waitlisted: int) -> Step:
        return Step(
            do="expect_counts",
            capability=self.cap.key,
            item=item,
            confirmed=confirmed,
            waitlisted=waitlisted,
        )

    def notified(self, actor: str, event: str) -> Step:
        return Step(do="expect_notified", actor=actor, event=event)  # type: ignore[arg-type]

    def advance(self, hours: float) -> Step:
        return Step(do="advance_time", hours=hours)

    def owner_notices(self, event: str) -> list[Step]:
        return [self.notified("owner", event)] if event in self.cap.notify_owner_on else []

    # scenario
    def add(
        self,
        template: str,
        title: str,
        steps: list[Step],
        seed: list[SeedRecord],
        use_override: bool = True,
    ) -> None:
        self.out.append(
            Scenario(
                id=f"derived:{self.cap.key}:{template}",
                title=f"{self.cap.title}: {title}",
                source="derived",
                capability_keys=[self.cap.key],
                capacity_override=self.override if use_override else None,
                seed=seed,
                steps=steps,
            )
        )

    # --- templates -------------------------------------------------------------------------------

    def build(self) -> list[Scenario]:
        cap, wl = self.cap, self.cap.waitlist
        promotes = wl.enabled and wl.auto_promote
        self.basic()
        self.capacity_reached()
        if cap.one_active_per_user_per_item:
            self.duplicate()
        limit = cap.max_active_per_user
        if limit is not None and limit <= MAX_LIMIT_ITEMS:
            self.user_limit(limit)
        if cap.cancellation.enabled:
            self.cancel_frees_seat()
            if wl.enabled:
                self.waitlisted_cancel()
            if promotes:
                self.promotion_order()
            elif wl.enabled:
                self.no_auto_promote()
            deadline = cap.cancellation.deadline_hours
            if deadline is not None:
                self.cancel_deadline(deadline)
        else:
            self.cancellation_disabled()
        if cap.closes_hours_before_start is not None:
            self.booking_cutoff(cap.closes_hours_before_start)
        if cap.start_field:
            self.item_started()
        if not cap.one_active_per_user_per_item and (limit is None or limit >= 2):
            self.duplicate_allowed()
        self.owner_cancel_basic()
        if promotes:
            self.owner_cancel_promotes()
        fixed = cap.capacity.value if cap.capacity.mode == "fixed" else None
        if fixed is not None and 1 <= fixed <= MAX_CONFIGURED_CAPACITY:
            self.configured_capacity(fixed)
        return self.out

    def basic(self) -> None:
        seed = self.seeds()
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.booking("ali", "i1", "confirmed"),
            self.counts("i1", 1, 0),
            *self.owner_notices("booked"),
        ]
        if _has_menu(self.spec, self.cap.key, "mine"):
            title = _rendered_title(self.spec, self.resource, seed[0])
            steps.append(Step(do="open", actor="ali", capability=self.cap.key, view="mine", contains=title))
        self.add("basic", "ثبت‌نام ساده و نمایش در «ثبت‌نام‌های من»", steps, seed)

    def capacity_reached(self) -> None:
        wl = self.cap.waitlist.enabled
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.book("sara", "i1", "confirmed"),
        ]
        if wl:
            steps += [
                self.book("reza", "i1", "waitlisted"),
                self.booking("reza", "i1", "waitlisted"),
                self.counts("i1", 2, 1),
                *self.owner_notices("waitlisted"),
            ]
            title = "پس از پر شدن ظرفیت، نفر بعدی به لیست انتظار می‌رود"
        else:
            steps += [
                self.book("reza", "i1", "rejected", "capacity_full"),
                self.booking("reza", "i1", "none"),
                self.counts("i1", 2, 0),
            ]
            title = "پس از پر شدن ظرفیت، ثبت‌نام جدید رد می‌شود"
        self.add("capacity_reached", title, steps, self.seeds())

    def duplicate(self) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.book("ali", "i1", "rejected", "duplicate"),
            self.counts("i1", 1, 0),
        ]
        self.add("duplicate", "ثبت‌نام تکراری یک نفر در یک مورد رد می‌شود", steps, self.seeds())

    def user_limit(self, limit: int) -> None:
        items = [f"i{n}" for n in range(1, limit + 2)]
        steps = [self.book("ali", item, "confirmed") for item in items[:limit]]
        steps += [
            self.book("ali", items[limit], "rejected", "user_limit"),
            self.booking("ali", items[limit], "none"),
        ]
        self.add(
            "user_limit",
            f"سقف {formatting.to_persian_digits(limit)} ثبت‌نام فعال برای هر کاربر",
            steps,
            self.seeds(limit + 1),
        )

    def cancel_frees_seat(self) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.book("sara", "i1", "confirmed"),
            self.cancel("ali", "i1", "cancelled"),
            *self.owner_notices("cancelled"),
            self.booking("ali", "i1", "cancelled"),
            self.counts("i1", 1, 0),
            self.book("reza", "i1", "confirmed"),
            self.counts("i1", 2, 0),
        ]
        self.add("cancel_frees_seat", "لغو ثبت‌نام یک جا آزاد می‌کند", steps, self.seeds())

    def cancellation_disabled(self) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.cancel("ali", "i1", "rejected", "cancellation_disabled"),
            self.booking("ali", "i1", "confirmed"),
            self.counts("i1", 1, 0),
        ]
        self.add("cancellation_disabled", "لغو ثبت‌نام توسط کاربر ممکن نیست", steps, self.seeds())

    def _waitlist_full(self) -> list[Step]:
        """ali, sara confirmed; reza, u4 waitlisted (capacity 2)."""
        return [
            self.book("ali", "i1", "confirmed"),
            self.book("sara", "i1", "confirmed"),
            self.book("reza", "i1", "waitlisted"),
            self.book("u4", "i1", "waitlisted"),
        ]

    def promotion_order(self) -> None:
        steps = [
            *self._waitlist_full(),
            self.cancel("ali", "i1", "cancelled"),
            self.booking("ali", "i1", "cancelled"),
            self.booking("reza", "i1", "confirmed"),
            self.booking("u4", "i1", "waitlisted"),
            self.counts("i1", 2, 1),
        ]
        if "promoted" in self.cap.notify_user_on:
            steps.append(self.notified("reza", "promoted"))
        self.add(
            "promotion_order",
            "با لغو یک ثبت‌نام، اولین نفر لیست انتظار قطعی می‌شود",
            steps,
            self.seeds(),
        )

    def no_auto_promote(self) -> None:
        steps = [
            *self._waitlist_full(),
            self.cancel("ali", "i1", "cancelled"),
            self.booking("reza", "i1", "waitlisted"),
            self.booking("u4", "i1", "waitlisted"),
            self.counts("i1", 1, 2),
        ]
        self.add(
            "no_auto_promote",
            "بدون جایگزینی خودکار، نفر لیست انتظار پس از لغو همچنان منتظر می‌ماند",
            steps,
            self.seeds(),
        )

    def waitlisted_cancel(self) -> None:
        steps = [
            *self._waitlist_full(),
            self.cancel("reza", "i1", "cancelled"),
            self.booking("reza", "i1", "cancelled"),
            self.booking("u4", "i1", "waitlisted"),
            self.counts("i1", 2, 1),
        ]
        self.add(
            "waitlisted_cancel",
            "لغو توسط نفر لیست انتظار کسی را قطعی نمی‌کند",
            steps,
            self.seeds(),
        )

    def cancel_deadline(self, deadline: int) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.book("sara", "i1", "confirmed"),
            self.cancel("ali", "i1", "cancelled"),
            self.booking("ali", "i1", "cancelled"),
        ]
        steps += [  # for deadline 0 this is past the start, where the driver cancels via "mine"
            self.advance(self.start_hours - deadline + 0.5),
            self.cancel("sara", "i1", "rejected", "cancel_deadline_passed"),
            self.booking("sara", "i1", "confirmed"),
        ]
        self.add(
            "cancel_deadline",
            f"لغو تا {formatting.to_persian_digits(deadline)} ساعت پیش از شروع مجاز و پس از آن رد می‌شود",
            steps,
            self.seeds(),
        )

    def booking_cutoff(self, hours: int) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.advance(self.start_hours - hours + 0.5),
            self.book("sara", "i1", "rejected", "booking_closed"),
            self.booking("sara", "i1", "none"),
            self.counts("i1", 1, 0),
        ]
        self.add(
            "booking_cutoff",
            f"ثبت‌نام تا {formatting.to_persian_digits(hours)} ساعت پیش از شروع باز است و پس از آن بسته می‌شود",
            steps,
            self.seeds(),
        )

    def item_started(self) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.advance(self.start_hours + 0.5),
            self.book("sara", "i1", "rejected", "booking_closed"),
            self.booking("sara", "i1", "none"),
            self.counts("i1", 1, 0),
        ]
        self.add("item_started", "پس از شروع، ثبت‌نام در مورد بسته است", steps, self.seeds())

    def duplicate_allowed(self) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.book("ali", "i1", "confirmed"),  # capacity 2: both fit
            self.counts("i1", 2, 0),
        ]
        self.add("duplicate_allowed", "ثبت‌نام مکرر یک نفر در یک مورد مجاز است", steps, self.seeds())

    def owner_cancel_basic(self) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.owner_cancel("ali", "i1"),
            self.booking("ali", "i1", "cancelled"),
            self.counts("i1", 0, 0),
        ]
        self.add("owner_cancel", "مدیر می‌تواند ثبت‌نام کاربر را لغو کند", steps, self.seeds())

    def owner_cancel_promotes(self) -> None:
        steps = [
            self.book("ali", "i1", "confirmed"),
            self.book("sara", "i1", "confirmed"),
            self.book("reza", "i1", "waitlisted"),
            self.owner_cancel("ali", "i1"),
            self.booking("ali", "i1", "cancelled"),
            self.booking("reza", "i1", "confirmed"),
            self.counts("i1", 2, 0),
        ]
        if "promoted" in self.cap.notify_user_on:
            steps.append(self.notified("reza", "promoted"))
        self.add(
            "owner_cancel_promotes",
            "لغو توسط مدیر نفر اول لیست انتظار را قطعی می‌کند",
            steps,
            self.seeds(),
        )

    def configured_capacity(self, n: int) -> None:
        wl = self.cap.waitlist.enabled
        steps = [self.book(f"u{k}", "i1", "confirmed") for k in range(1, n + 1)]
        last = f"u{n + 1}"
        if wl:
            steps += [self.book(last, "i1", "waitlisted"), self.counts("i1", n, 1)]
        else:
            steps += [self.book(last, "i1", "rejected", "capacity_full"), self.counts("i1", n, 0)]
        self.add(
            "configured_capacity",
            f"ظرفیت تنظیم‌شده ({formatting.to_persian_digits(n)} نفر) دقیقاً رعایت می‌شود",
            steps,
            self.seeds(),
            use_override=False,
        )


def booking_templates(spec: BotSpec, cap: BookingCapability) -> list[Scenario]:
    resource = spec.resource(cap.resource)
    if resource is None or not _has_menu(spec, cap.key, "main"):
        return []  # users cannot reach this capability; nothing a scenario could drive
    return _Booking(spec, cap, resource).build()


# --- catalog and info ----------------------------------------------------------------------------


def catalog_templates(spec: BotSpec, cap: CatalogCapability) -> list[Scenario]:
    resource = spec.resource(cap.resource)
    if resource is None or not _has_menu(spec, cap.key, "main"):
        return []
    seed = _seed_record(resource, "i1", 1, BASE_START_HOURS)
    title = _rendered_title(spec, resource, seed)
    return [
        Scenario(
            id=f"derived:{cap.key}:open",
            title=f"{cap.title}: باز کردن فهرست، عنوان آیتم دیده می‌شود",
            source="derived",
            capability_keys=[cap.key],
            seed=[seed],
            steps=[Step(do="open", actor="ali", capability=cap.key, contains=title)],
        )
    ]


def info_templates(spec: BotSpec, cap: InfoCapability) -> list[Scenario]:
    if not cap.pages or not _has_menu(spec, cap.key, "main"):
        return []
    # One page is shown whole; several pages are listed by title. The first title is in both.
    contains = cap.pages[0].title
    return [
        Scenario(
            id=f"derived:{cap.key}:open",
            title=f"{cap.title}: باز کردن بخش، محتوای صفحه دیده می‌شود",
            source="derived",
            capability_keys=[cap.key],
            steps=[Step(do="open", actor="ali", capability=cap.key, contains=contains)],
        )
    ]


# --- registry ------------------------------------------------------------------------------------

TEMPLATES: dict[str, Template] = {
    "booking": booking_templates,
    "catalog": catalog_templates,
    "info": info_templates,
}  # "request" is registered by a later package


def register_templates(cap_type: str, fn: Template) -> None:
    """Install (or replace) the derived-scenario template function of a capability type."""
    TEMPLATES[cap_type] = fn


def derive_scenarios(spec: BotSpec) -> list[Scenario]:
    """Scenarios generated from every capability's configuration, in capability order."""
    out: list[Scenario] = []
    for cap in spec.capabilities:
        fn = TEMPLATES.get(cap.type)
        if fn is not None:
            out.extend(fn(spec, cap))
    return out
