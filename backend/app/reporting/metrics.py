"""Declarative metrics per capability type, all expressed in the ``runtime.aggregate`` vocabulary.

A ``MetricDef`` has an id, a Persian label, a kind (``scalar`` | ``series`` | ``breakdown`` |
``table``), a unit and ``build(cap, window) -> QuerySpec | callable``:

- a ``QuerySpec`` runs through ``aggregate.evaluate`` over the rows of ``collection(cap)``;
- a callable ``(Data) -> result`` covers what one spec cannot say (a ratio, a join between two
  collections). Scalars return ``float | None``; series and breakdowns return ``[(label, value)]``;
  tables return ``[{"label", "value", ...}]``.

``window`` is ``(since, until)`` on the creation time of a record (some metrics use another field
or none at all, see each builder). Scalar metrics that depend on the window also get ``previous``,
computed with the same builder over the previous window. Metrics that describe the current state
(open requests, upcoming events, capacity use) are not windowed and have no ``previous``.

Capability ids are registry-style: ``orders``, ``booking``, ``events`` (booking with preset
``events``), ``forms`` (the ``request`` type), ``catalog`` and ``info``.

Record conventions (``botspec/models.py`` docstring): orders live in ``K`` with ``data.total`` and
order lines in ``K.lines``; bookings have status ``confirmed`` | ``waitlisted`` | ``cancelled`` and
``item_id`` pointing at the resource record.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any, Literal

from app.botspec.models import (
    AnyCapability,
    BookingCapability,
    CatalogCapability,
    OrdersCapability,
    RequestCapability,
)
from app.runtime.aggregate import QuerySpec, Row, evaluate, to_number
from app.runtime.formatting import parse_datetime
from app.schemas.business import MetricValue, SeriesPoint

Window = tuple[datetime | None, datetime | None]
Kind = Literal["scalar", "series", "breakdown", "table"]

TOMAN = "تومان"
PERCENT = "٪"
HOURS = "ساعت"
NO_CATEGORY = "بدون دسته"
TOP_PRODUCTS = 5

BOOKING_STATUS_LABELS = {"confirmed": "قطعی", "waitlisted": "در لیست انتظار", "cancelled": "لغو شده"}
RSVP_STATUS_LABELS = {"confirmed": "شرکت می‌کنند", "waitlisted": "در لیست انتظار", "cancelled": "لغو شده"}
LIVE_BOOKING = ["confirmed", "waitlisted"]


@dataclass
class Data:
    """Everything a metric may read: rows per collection (unfiltered), timezone and the clock."""

    rows: dict[str, list[Row]]
    tz: tzinfo
    now: datetime

    def of(self, collection: str) -> list[Row]:
        return self.rows.get(collection, [])


Custom = Callable[[Data], Any]
Plan = QuerySpec | Custom


def _always(_cap: Any) -> bool:
    return True


def _own_collection(cap: Any) -> str:
    return cap.key


@dataclass(frozen=True)
class MetricDef:
    id: str
    label_fa: str
    kind: Kind
    unit: str | None
    build: Callable[[Any, Window], Plan]
    collection: Callable[[Any], str] = _own_collection
    windowed: bool = True
    labels: Callable[[Any], dict[str, str]] | None = None  # breakdown: status key -> Persian label
    applies: Callable[[Any], bool] = field(default=_always)


# --- capability ids and collections -----------------------------------------------------------


def capability_id(cap: AnyCapability) -> str:
    if isinstance(cap, BookingCapability):
        return "events" if cap.preset == "events" else "booking"
    return {"orders": "orders", "request": "forms", "catalog": "catalog", "info": "info"}[cap.type]


def collections_for(cap: AnyCapability) -> list[str]:
    """Every collection the metrics of ``cap`` read."""
    if isinstance(cap, OrdersCapability):
        return [cap.key, f"{cap.key}.lines"]
    if isinstance(cap, BookingCapability):
        return [cap.key, cap.resource]
    if isinstance(cap, RequestCapability):
        return [cap.key] + ([cap.item_resource] if cap.item_resource else [])
    if isinstance(cap, CatalogCapability):
        return [cap.resource]
    return []


# --- helpers ----------------------------------------------------------------------------------


def _q(window: Window, **kw: Any) -> QuerySpec:
    return QuerySpec(since=window[0], until=window[1], **kw)


def _cancelled_statuses(cap: OrdersCapability) -> list[str]:
    return [s.key for s in cap.statuses if "cancel" in s.key.lower() or "لغو" in s.label]


def _live_order_statuses(cap: OrdersCapability) -> list[str]:
    cancelled = set(_cancelled_statuses(cap))
    return [s.key for s in cap.statuses if s.key not in cancelled]


def request_terminal_statuses(cap: RequestCapability | OrdersCapability) -> list[str]:
    """Statuses no owner action leaves (the initial status never counts as terminal)."""
    left = {k for a in cap.owner_actions for k in a.from_statuses}
    return [s.key for s in cap.statuses if s.key not in left and s.key != cap.initial_status]


def _open_statuses(cap: RequestCapability) -> list[str]:
    terminal = set(request_terminal_statuses(cap))
    return [s.key for s in cap.statuses if s.key not in terminal]


def _status_labels(cap: Any) -> dict[str, str]:
    return {s.key: s.label for s in cap.statuses}


def _upcoming_items(cap: BookingCapability, data: Data) -> list[Row]:
    items = data.of(cap.resource)
    if cap.start_field is None:
        return items
    out = []
    for item in items:
        start = parse_datetime(item.get(cap.start_field))
        if start is not None and start >= data.now:
            out.append(item)
    return out


# --- orders -----------------------------------------------------------------------------------


def _top_products(cap: OrdersCapability, window: Window) -> Custom:
    def run(data: Data) -> list[dict[str, Any]]:
        cancelled = set(_cancelled_statuses(cap))
        dead_orders = {
            int(n)
            for r in data.of(cap.key)
            if r.get("_status") in cancelled and (n := to_number(r["_id"])) is not None
        }
        lines: list[Row] = []
        for r in data.of(f"{cap.key}.lines"):
            order_id = to_number(r.get("order_id"))
            if order_id is not None and int(order_id) in dead_orders:
                continue
            qty, price = to_number(r.get("qty")), to_number(r.get("unit_price"))
            lines.append({**r, "_amount": None if qty is None or price is None else qty * price})
        base = {"group_by": "title", "group_kind": "field"}
        top = evaluate(lines, _q(window, measure="sum", field="qty", top_n=TOP_PRODUCTS, **base), tz=data.tz)
        money = dict(evaluate(lines, _q(window, measure="sum", field="_amount", **base), tz=data.tz).groups)
        return [{"label": t, "value": q, "revenue": money.get(t, 0.0)} for t, q in top.groups]

    return run


def _orders() -> list[MetricDef]:
    def live(cap: OrdersCapability) -> list[str] | None:
        return _live_order_statuses(cap)

    return [
        MetricDef(
            "order_count", "تعداد سفارش‌ها", "scalar", None,
            lambda cap, w: _q(w, measure="count", status_in=live(cap)),
        ),
        MetricDef(
            "revenue", "درآمد", "scalar", TOMAN,
            lambda cap, w: _q(w, measure="sum", field="total", status_in=live(cap)),
        ),
        MetricDef(
            "average_order_value", "میانگین مبلغ سفارش", "scalar", TOMAN,
            lambda cap, w: _q(w, measure="avg", field="total", status_in=live(cap)),
        ),
        MetricDef(
            "orders_by_status", "سفارش‌ها به تفکیک وضعیت", "breakdown", None,
            lambda cap, w: _q(w, measure="count", group_kind="status"),
            labels=_status_labels,
        ),
        MetricDef(
            "orders_by_day", "سفارش‌ها در هر روز", "series", None,
            lambda cap, w: _q(w, measure="count", status_in=live(cap), group_kind="day", fill_gaps=True),
        ),
        MetricDef(
            "top_products", "پرفروش‌ترین محصولات", "table", None,
            lambda cap, w: _top_products(cap, w),
        ),
        MetricDef(
            "cancelled_orders", "سفارش‌های لغوشده", "scalar", None,
            lambda cap, w: _q(w, measure="count", status_in=_cancelled_statuses(cap)),
        ),
    ]  # fmt: skip


# --- booking ----------------------------------------------------------------------------------


def _cancellation_rate(cap: BookingCapability, window: Window) -> Custom:
    def run(data: Data) -> float | None:
        rows = data.of(cap.key)
        total = evaluate(rows, _q(window, measure="count"), tz=data.tz).value or 0.0
        cancelled = (
            evaluate(rows, _q(window, measure="count", status_in=["cancelled"]), tz=data.tz).value or 0.0
        )
        return None if total == 0 else cancelled / total * 100

    return run


def _capacity_utilization(cap: BookingCapability) -> Custom:
    def run(data: Data) -> float | None:
        confirmed: dict[int, int] = {}
        for r in data.of(cap.key):
            if r.get("_status") == "confirmed" and r.get("_item_id") is not None:
                confirmed[r["_item_id"]] = confirmed.get(r["_item_id"], 0) + 1
        total_capacity = used = 0.0
        for item in _upcoming_items(cap, data):
            if cap.capacity.mode == "fixed":
                capacity = to_number(cap.capacity.value)
            else:
                capacity = to_number(item.get(cap.capacity.field or ""))
            if capacity is None or capacity < 1:
                continue
            total_capacity += capacity
            used += min(confirmed.get(item["_id"], 0), capacity)
        return None if total_capacity == 0 else used / total_capacity * 100

    return run


def _booking() -> list[MetricDef]:
    return [
        MetricDef(
            "booking_count", "تعداد رزروها", "scalar", None,
            lambda cap, w: _q(w, measure="count", status_in=LIVE_BOOKING),
        ),
        MetricDef(
            "cancellation_count", "رزروهای لغوشده", "scalar", None,
            lambda cap, w: _q(w, measure="count", status_in=["cancelled"]),
        ),
        MetricDef(
            "cancellation_rate", "نرخ لغو", "scalar", PERCENT,
            lambda cap, w: _cancellation_rate(cap, w),
        ),
        MetricDef(
            "bookings_by_day", "رزروها در هر روز", "series", None,
            lambda cap, w: _q(w, measure="count", status_in=LIVE_BOOKING, group_kind="day", fill_gaps=True),
        ),
        MetricDef(
            "capacity_utilization", "درصد پرشدن ظرفیت", "scalar", PERCENT,
            lambda cap, w: _capacity_utilization(cap),
            windowed=False,
        ),
    ]  # fmt: skip


# --- events (booking preset) ------------------------------------------------------------------


def _event_count(cap: BookingCapability) -> Custom:
    return lambda data: float(len(_upcoming_items(cap, data)))


def _attendance_by_category(cap: BookingCapability, window: Window) -> Custom:
    def run(data: Data) -> list[tuple[str, float]]:
        category_of: dict[int, Any] = {
            i["_id"]: i.get(cap.category_field or "") for i in data.of(cap.resource)
        }
        rows = []
        for r in data.of(cap.key):
            category = category_of.get(r.get("_item_id"))
            rows.append({**r, "_category": category if category not in (None, "") else NO_CATEGORY})
        spec = _q(window, measure="count", status_in=["confirmed"], group_by="_category")
        groups = evaluate(rows, spec, tz=data.tz).groups
        return sorted(groups, key=lambda g: (-g[1], g[0]))

    return run


def _events() -> list[MetricDef]:
    return [
        MetricDef(
            "event_count", "رویدادهای پیش‌رو", "scalar", None,
            lambda cap, w: _event_count(cap),
            collection=lambda cap: cap.resource,
            windowed=False,
        ),
        MetricDef(
            "rsvp_count", "تعداد ثبت‌نام‌ها", "scalar", None,
            lambda cap, w: _q(w, measure="count", status_in=["confirmed"]),
        ),
        MetricDef(
            "rsvp_breakdown", "وضعیت ثبت‌نام‌ها", "breakdown", None,
            lambda cap, w: _q(w, measure="count", group_kind="status"),
            labels=lambda cap: RSVP_STATUS_LABELS,
        ),
        MetricDef(
            "attendance_by_category", "شرکت‌کنندگان به تفکیک دسته", "breakdown", None,
            lambda cap, w: _attendance_by_category(cap, w),
            applies=lambda cap: cap.category_field is not None,
        ),
        MetricDef(
            "rsvp_by_day", "ثبت‌نام‌ها در هر روز", "series", None,
            lambda cap, w: _q(w, measure="count", status_in=["confirmed"], group_kind="day", fill_gaps=True),
        ),
    ]  # fmt: skip


# --- request (forms) --------------------------------------------------------------------------


def _average_resolution_hours(cap: RequestCapability, window: Window) -> Custom:
    def run(data: Data) -> float | None:
        terminal = set(request_terminal_statuses(cap))
        rows = []
        for r in data.of(cap.key):
            if r.get("_status") in terminal:
                hours = (r["_updated_at"] - r["_created_at"]).total_seconds() / 3600
                rows.append({**r, "_hours": hours})
        spec = _q(window, measure="avg", field="_hours", time_field="_updated_at")
        return evaluate(rows, spec, tz=data.tz).value

    return run


def _requests() -> list[MetricDef]:
    return [
        MetricDef(
            "request_count", "تعداد درخواست‌ها", "scalar", None,
            lambda cap, w: _q(w, measure="count"),
        ),
        MetricDef(
            "open_requests", "درخواست‌های باز", "scalar", None,
            lambda cap, w: QuerySpec(measure="count", status_in=_open_statuses(cap)),
            windowed=False,
        ),
        MetricDef(
            "resolved_requests", "درخواست‌های ختم‌شده", "scalar", None,
            lambda cap, w: _q(
                w, measure="count", status_in=request_terminal_statuses(cap), time_field="_updated_at"
            ),
        ),
        MetricDef(
            "requests_by_status", "درخواست‌ها به تفکیک وضعیت", "breakdown", None,
            lambda cap, w: _q(w, measure="count", group_kind="status"),
            labels=_status_labels,
        ),
        MetricDef(
            "average_resolution_time_hours", "میانگین زمان رسیدگی", "scalar", HOURS,
            lambda cap, w: _average_resolution_hours(cap, w),
        ),
        MetricDef(
            "requests_by_day", "درخواست‌ها در هر روز", "series", None,
            lambda cap, w: _q(w, measure="count", group_kind="day", fill_gaps=True),
        ),
    ]  # fmt: skip


# --- catalog / info ---------------------------------------------------------------------------

_CATALOG = [
    MetricDef(
        "item_count",
        "تعداد آیتم‌ها",
        "scalar",
        None,
        lambda cap, w: QuerySpec(measure="count"),
        collection=lambda cap: cap.resource,
        windowed=False,
    ),
]

METRICS: dict[str, list[MetricDef]] = {
    "orders": _orders(),
    "booking": _booking(),
    "events": _events(),
    "forms": _requests(),
    "catalog": _CATALOG,
    "info": [],
}


def metrics_for(cap: AnyCapability) -> list[MetricDef]:
    return [m for m in METRICS[capability_id(cap)] if m.applies(cap)]


def metric_def(cap: AnyCapability, metric_id: str) -> MetricDef | None:
    return next((m for m in metrics_for(cap) if m.id == metric_id), None)


# --- evaluation -------------------------------------------------------------------------------


def _run(defn: MetricDef, cap: AnyCapability, data: Data, window: Window) -> Any:
    plan = defn.build(cap, window)
    if callable(plan):
        return plan(data)
    res = evaluate(data.of(defn.collection(cap)), plan, tz=data.tz)
    return res.value if defn.kind == "scalar" else res.groups


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _ordered(groups: list[tuple[str, float]], labels: dict[str, str] | None) -> list[tuple[str, float]]:
    if not labels:
        return groups
    by_key = dict(groups)
    ordered = [(labels[k], by_key[k]) for k in labels if k in by_key]
    return ordered + [(k, v) for k, v in groups if k not in labels]


def compute_metric(
    defn: MetricDef,
    cap: AnyCapability,
    data: Data,
    window: Window,
    previous_window: Window | None = None,
    *,
    id: str | None = None,
    label: str | None = None,
) -> MetricValue:
    """One ``MetricValue``. ``previous`` is set for windowed scalars when ``previous_window`` is."""
    raw = _run(defn, cap, data, window)
    out = MetricValue(id=id or defn.id, label=label or defn.label_fa, kind=defn.kind, unit=defn.unit)
    if defn.kind == "scalar":
        out.value = _round(raw)
        if defn.windowed and previous_window is not None:
            out.previous = _round(_run(defn, cap, data, previous_window))
    elif defn.kind == "table":
        out.rows = list(raw)
    else:
        groups = _ordered(list(raw), defn.labels(cap) if defn.labels else None)
        out.series = [SeriesPoint(label=name, value=value) for name, value in groups]
    return out
