"""Reporting service: per-capability reports and the Overview, over any ``Store``.

Rows are loaded once per collection (newest ``MAX_ROWS`` records) and every metric is evaluated in
Python by ``runtime.aggregate``. No LLM, no clock reads (``now`` is passed in), no database access
of its own: the caller supplies the store.
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import (
    AnyCapability,
    BookingCapability,
    BotSpec,
    OrdersCapability,
    RequestCapability,
)
from app.reporting.metrics import (
    Data,
    Window,
    capability_id,
    collections_for,
    compute_metric,
    metric_def,
    metrics_for,
)
from app.reporting.periods import period_bounds
from app.runtime.aggregate import MAX_ROWS, Row, rows_from_records
from app.runtime.formatting import get_tz, parse_datetime, to_persian_digits
from app.runtime.store import Store
from app.schemas.business import ActivityItem, CapabilityReportOut, MetricValue, OverviewOut, Period

ACTIVITY_LIMIT = 10
NAME_KEYS = ("name", "full_name", "customer_name", "نام")
SOMEONE = "مشتری"

# Overview KPIs per capability id, in display order.
KPI_METRICS: dict[str, list[str]] = {
    "orders": ["order_count", "revenue"],
    "booking": ["booking_count"],
    "events": ["event_count", "rsvp_count"],
    "forms": ["open_requests"],
}

OverviewSource = Callable[[uuid.UUID, AsyncSession], Awaitable[list[MetricValue]]]
_overview_sources: list[OverviewSource] = []


def register_overview_source(fn: OverviewSource) -> OverviewSource:
    """Let another module add KPIs to the Overview (``async fn(bot_id, session) -> [MetricValue]``).
    The API layer collects them with ``collect_overview_sources`` and passes them as ``extra_kpis``."""
    if fn not in _overview_sources:
        _overview_sources.append(fn)
    return fn


async def collect_overview_sources(bot_id: uuid.UUID, session: AsyncSession) -> list[MetricValue]:
    out: list[MetricValue] = []
    for fn in list(_overview_sources):
        out.extend(await fn(bot_id, session))
    return out


# --- loading ----------------------------------------------------------------------------------


async def load_data(store: Store, spec: BotSpec, collections: Iterable[str], now: datetime) -> Data:
    rows: dict[str, list[Row]] = {}
    for name in dict.fromkeys(collections):
        records = await store.list_records(name, order_by="-id", limit=MAX_ROWS)
        rows[name] = rows_from_records(reversed(records))  # oldest first
    return Data(rows=rows, tz=get_tz(spec.bot.timezone), now=now)


def _windows(period: Period, now: datetime, spec: BotSpec) -> tuple[Window, Window | None]:
    since, until, prev_since, prev_until = period_bounds(period, now, get_tz(spec.bot.timezone))
    previous = None if prev_since is None or prev_until is None else (prev_since, prev_until)
    return (since, until), previous


# --- capability report ------------------------------------------------------------------------


async def capability_report(
    store: Store, spec: BotSpec, cap: AnyCapability, period: Period, now: datetime
) -> CapabilityReportOut:
    window, previous = _windows(period, now, spec)
    data = await load_data(store, spec, collections_for(cap), now)
    metrics = [compute_metric(m, cap, data, window, previous) for m in metrics_for(cap)]
    return CapabilityReportOut(
        capability_key=cap.key,
        capability_id=capability_id(cap),
        label=cap.title,
        period=period,
        since=window[0] or _earliest(data, cap) or window[1],
        until=window[1],
        metrics=metrics,
    )


def _earliest(data: Data, cap: AnyCapability) -> datetime | None:
    times = [t for r in data.of(cap.key) if (t := parse_datetime(r.get("_created_at"))) is not None]
    return min(times) if times else None


# --- overview ---------------------------------------------------------------------------------


def _enabled(spec: BotSpec) -> list[AnyCapability]:
    return [c for c in spec.capabilities if c.enabled]


def _customers(caps: list[AnyCapability], data: Data, window: Window) -> float:
    actors: set[str] = set()
    for cap in caps:
        if isinstance(cap, OrdersCapability | BookingCapability | RequestCapability):
            for r in data.of(cap.key):
                at = parse_datetime(r.get("_created_at"))
                if r.get("_actor_id") is None or at is None:
                    continue
                if (window[0] is None or at >= window[0]) and (window[1] is None or at < window[1]):
                    actors.add(r["_actor_id"])
    return float(len(actors))


async def overview(
    store: Store,
    spec: BotSpec,
    period: Period,
    now: datetime,
    *,
    extra_kpis: list[MetricValue] | None = None,
) -> OverviewOut:
    caps = _enabled(spec)
    window, previous = _windows(period, now, spec)
    wanted: list[str] = []
    for cap in caps:
        wanted += collections_for(cap)
    data = await load_data(store, spec, wanted, now)

    kinds: dict[str, int] = {}
    for cap in caps:
        kinds[capability_id(cap)] = kinds.get(capability_id(cap), 0) + 1

    kpis: list[MetricValue] = []
    for cap in caps:
        cid = capability_id(cap)
        crowded = kinds[cid] > 1  # two capabilities of one kind: tell them apart
        for metric_id in KPI_METRICS.get(cid, []):
            defn = metric_def(cap, metric_id)
            if defn is None:
                continue
            kpis.append(
                compute_metric(
                    defn,
                    cap,
                    data,
                    window,
                    previous,
                    id=f"{cap.key}.{metric_id}" if crowded else None,
                    label=f"{cap.title}: {defn.label_fa}" if crowded else None,
                )
            )
    if any(isinstance(c, OrdersCapability | BookingCapability | RequestCapability) for c in caps):
        kpis.append(
            MetricValue(
                id="customers",
                label="مشتریان",
                kind="scalar",
                value=_customers(caps, data, window),
                previous=None if previous is None else _customers(caps, data, previous),
            )
        )
    kpis.extend(extra_kpis or [])
    return OverviewOut(
        period=period,
        kpis=kpis,
        activity=_activity(caps, spec, data),
        enabled_capabilities=list(dict.fromkeys(capability_id(c) for c in caps)),
    )


# --- activity ---------------------------------------------------------------------------------


def _titles(spec: BotSpec, data: Data, resource: str | None) -> dict[int, str]:
    res = spec.resource(resource) if resource else None
    if res is None:
        return {}
    return {
        r["_id"]: str(r[res.title_field])
        for r in data.of(res.key)
        if r.get(res.title_field) not in (None, "")
    }


def _who(row: Row) -> str:
    for key in NAME_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return SOMEONE


def _sentence(cap: AnyCapability, row: Row, titles: dict[int, str]) -> tuple[str, str]:
    number = to_persian_digits(row["_id"])
    if isinstance(cap, OrdersCapability):
        return f"سفارش #{number} ثبت شد", "order"
    if isinstance(cap, BookingCapability):
        who, title = _who(row), titles.get(row.get("_item_id") or -1, cap.title)
        status = row.get("_status")
        if status == "cancelled":
            return f"{who} ثبت‌نام «{title}» را لغو کرد", "booking"
        if status == "waitlisted":
            return f"{who} در لیست انتظار «{title}» قرار گرفت", "booking"
        if cap.preset == "events":
            return f"{who} در {title} ثبت‌نام کرد", "booking"
        return f"{who} برای {title} رزرو کرد", "booking"
    return f"درخواست «{cap.title}» #{number} ثبت شد", "request"


def _activity(caps: list[AnyCapability], spec: BotSpec, data: Data) -> list[ActivityItem]:
    entries: list[tuple[datetime, int, AnyCapability, Row]] = []
    for cap in caps:
        if not isinstance(cap, OrdersCapability | BookingCapability | RequestCapability):
            continue
        for row in data.of(cap.key)[-ACTIVITY_LIMIT:]:
            at = parse_datetime(row.get("_created_at"))
            if at is not None:
                entries.append((at, row["_id"], cap, row))
    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
    out: list[ActivityItem] = []
    title_cache: dict[str, dict[int, str]] = {}
    for at, _, cap, row in entries[:ACTIVITY_LIMIT]:
        resource = cap.resource if isinstance(cap, BookingCapability) else None
        if resource and resource not in title_cache:
            title_cache[resource] = _titles(spec, data, resource)
        text, kind = _sentence(cap, row, title_cache.get(resource or "", {}))
        out.append(ActivityItem(at=at, text=text, kind=kind))
    return out
