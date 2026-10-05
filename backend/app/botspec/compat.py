"""Data-compatibility check between a live spec and a proposed one (frozen contract, WP0).

``check_compat(old, new, record_counts)`` where ``record_counts`` maps a collection key (resource
key or capability key) to its number of live records; missing keys count as 0.
Messages are Persian (they appear on the owner's review card).

Codes:
  field_type_changed             error   a field (resource field or form field) changed type
  required_field_without_default error   a resource with records gains a required field without a
                                         default (newly added, or optional -> required)
  capability_type_changed        error   same key, different capability type, records exist
  collection_removed_with_records warning resource or capability with records removed
  field_removed_with_records     warning field removed from a collection with records
  capacity_lowered               warning fixed capacity lowered while bookings exist (or below the
                                         known highest confirmed count per item)
  capacity_mode_changed          warning capacity mode changed while bookings exist
  booking_resource_changed       warning booking points at another resource while bookings exist
  booking_preset_changed         warning booking preset (booking <-> events) changed while bookings
                                         exist
  booking_category_changed       warning booking category_field changed while bookings exist
  status_removed_with_records    warning request/orders status removed while records exist
  orders_resource_changed        warning orders point at another resource while orders exist

Orders behave like request: checkout_fields are compared like form_fields, removed statuses warn.
Enabling/disabling a capability or changing its audience never touches data (no issue).
"""

from app.botspec.models import (
    BookingCapability,
    BotSpec,
    FieldDef,
    OrdersCapability,
    RequestCapability,
    StatusDef,
)
from app.botspec.validate import SpecIssue


def _err(path: list[str], code: str, msg: str) -> SpecIssue:
    return SpecIssue(path=path, code=code, message=msg, severity="error")


def _warn(path: list[str], code: str, msg: str) -> SpecIssue:
    return SpecIssue(path=path, code=code, message=msg, severity="warning")


def _fields_compat(
    base: list[str],
    old_fields: list[FieldDef],
    new_fields: list[FieldDef],
    count: int,
    *,
    check_required: bool,
) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    new_by = {f.key: f for f in new_fields}
    old_by = {f.key: f for f in old_fields}
    for key, of in old_by.items():
        nf = new_by.get(key)
        if nf is None:
            if count > 0:
                issues.append(
                    _warn(
                        [*base, key],
                        "field_removed_with_records",
                        f"فیلد «{of.label}» حذف می‌شود؛ داده‌های قبلی آن پنهان می‌ماند.",
                    )
                )
        elif nf.type != of.type:
            issues.append(
                _err(
                    [*base, key, "type"],
                    "field_type_changed",
                    f"نوع فیلد «{of.label}» قابل تغییر نیست؛ یک فیلد جدید بسازید.",
                )
            )
    if check_required and count > 0:
        for key, nf in new_by.items():
            of = old_by.get(key)
            newly_required = nf.required and (of is None or not of.required)
            if newly_required and nf.default is None:
                issues.append(
                    _err(
                        [*base, key],
                        "required_field_without_default",
                        f"فیلد اجباری «{nf.label}» برای رکوردهای موجود مقدار ندارد؛ "
                        "آن را اختیاری کنید یا مقدار پیش‌فرض بدهید.",
                    )
                )
    return issues


def check_compat(
    old: BotSpec,
    new: BotSpec,
    record_counts: dict[str, int],
    *,
    max_confirmed_per_item: dict[str, int] | None = None,
) -> list[SpecIssue]:
    """Issues raised by moving live data from ``old`` to ``new``.

    ``max_confirmed_per_item`` (optional, booking capability key -> highest confirmed count on a
    single item) makes the capacity warning exact; without it, lowering a fixed capacity warns
    whenever the booking collection has records.
    """
    issues: list[SpecIssue] = []

    def count(key: str) -> int:
        return record_counts.get(key, 0)

    new_res = {r.key: r for r in new.resources}
    for r in old.resources:
        base = ["resources", r.key]
        nr = new_res.get(r.key)
        if nr is None:
            if count(r.key) > 0:
                issues.append(
                    _warn(
                        base,
                        "collection_removed_with_records",
                        f"«{r.label_plural}» حذف می‌شود؛ {count(r.key)} رکورد آن نگه داشته و پنهان می‌شود.",
                    )
                )
            continue
        issues += _fields_compat([*base, "fields"], r.fields, nr.fields, count(r.key), check_required=True)
    # Resources that are new have no records, so their required fields are fine.

    new_caps = {c.key: c for c in new.capabilities}
    for oc in old.capabilities:
        base = ["capabilities", oc.key]
        n = count(oc.key)
        nc = new_caps.get(oc.key)
        if nc is None:
            if n > 0:
                issues.append(
                    _warn(
                        base,
                        "collection_removed_with_records",
                        f"«{oc.title}» حذف می‌شود؛ {n} رکورد آن نگه داشته و پنهان می‌شود.",
                    )
                )
            continue
        if nc.type != oc.type:
            if n > 0:
                issues.append(
                    _err(
                        [*base, "type"],
                        "capability_type_changed",
                        f"نوع «{oc.title}» با وجود رکوردهای موجود قابل تغییر نیست.",
                    )
                )
            continue
        if isinstance(oc, BookingCapability | RequestCapability) and isinstance(
            nc, BookingCapability | RequestCapability
        ):
            issues += _fields_compat(
                [*base, "form_fields"], oc.form_fields, nc.form_fields, n, check_required=False
            )
        if isinstance(oc, BookingCapability) and isinstance(nc, BookingCapability) and n > 0:
            issues += _booking_compat(base, oc, nc, max_confirmed_per_item)
        if isinstance(oc, RequestCapability) and isinstance(nc, RequestCapability) and n > 0:
            issues += _statuses_compat(base, oc.statuses, nc.statuses, "درخواست‌های")
        if isinstance(oc, OrdersCapability) and isinstance(nc, OrdersCapability):
            issues += _fields_compat(
                [*base, "checkout_fields"], oc.checkout_fields, nc.checkout_fields, n, check_required=False
            )
            if n > 0:
                issues += _statuses_compat(base, oc.statuses, nc.statuses, "سفارش‌های")
                if nc.resource != oc.resource:
                    issues.append(
                        _warn(
                            [*base, "resource"],
                            "orders_resource_changed",
                            f"«{oc.title}» به منبع دیگری وصل می‌شود؛ "
                            "سفارش‌های قبلی به کالاهای قبلی اشاره می‌کنند.",
                        )
                    )
    return issues


def _statuses_compat(
    base: list[str], old: list[StatusDef], new: list[StatusDef], records_fa: str
) -> list[SpecIssue]:
    new_status = {s.key for s in new}
    return [
        _warn(
            [*base, "statuses", s.key],
            "status_removed_with_records",
            f"وضعیت «{s.label}» حذف می‌شود؛ {records_fa} این وضعیت بدون وضعیت معتبر می‌مانند.",
        )
        for s in old
        if s.key not in new_status
    ]


def _booking_compat(
    base: list[str],
    oc: BookingCapability,
    nc: BookingCapability,
    max_confirmed_per_item: dict[str, int] | None,
) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    if nc.resource != oc.resource:
        issues.append(
            _warn(
                [*base, "resource"],
                "booking_resource_changed",
                f"«{oc.title}» به منبع دیگری وصل می‌شود؛ رزروهای قبلی به موارد قبلی اشاره می‌کنند.",
            )
        )
    if nc.preset != oc.preset:
        issues.append(
            _warn(
                [*base, "preset"],
                "booking_preset_changed",
                f"نوع «{oc.title}» بین رزرو و رویداد تغییر می‌کند؛ ثبت‌نام‌های قبلی حفظ می‌شوند.",
            )
        )
    if nc.category_field != oc.category_field:
        issues.append(
            _warn(
                [*base, "category_field"],
                "booking_category_changed",
                f"دسته‌بندی «{oc.title}» تغییر می‌کند؛ اشتراک‌های دسته‌بندی قبلی ممکن است بی‌اثر شوند.",
            )
        )
    if oc.capacity.mode != nc.capacity.mode:
        issues.append(
            _warn(
                [*base, "capacity", "mode"],
                "capacity_mode_changed",
                "نوع ظرفیت تغییر می‌کند؛ ظرفیت موارد دارای رزرو ممکن است کمتر شود.",
            )
        )
    elif (
        nc.capacity.mode == "fixed"
        and oc.capacity.value is not None
        and (nc.capacity.value is not None and nc.capacity.value < oc.capacity.value)
    ):
        known = (max_confirmed_per_item or {}).get(oc.key)
        if known is None or known > nc.capacity.value:
            issues.append(
                _warn(
                    [*base, "capacity", "value"],
                    "capacity_lowered",
                    "ظرفیت کمتر می‌شود؛ رزروهای تأییدشدهٔ فعلی باقی می‌مانند و تا "
                    "کمتر شدن تعداد، رزرو جدید تأیید نمی‌شود.",
                )
            )
    return issues
