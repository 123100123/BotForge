"""One deterministic aggregation vocabulary (Business OS reporting).

A ``QuerySpec`` says what to compute over a list of row dicts: a ``measure`` (count, sum, avg, min,
max of a field), optional grouping (a field, the record status, or day / week buckets), filters
(``status_in``, ``equals``, a time range) and ``top_n``. ``evaluate`` is pure and deterministic; it
never reads the clock and never touches a database. Rows come from ``Store.list_records`` via
``rows_from_records`` (callers cap the load at ``MAX_ROWS``; SQL push-down is the documented scaling
boundary) or, later, from spreadsheet rows.

Row shape: ``record.data`` flattened, plus the system keys ``_id``, ``_status``, ``_created_at``,
``_updated_at``, ``_actor_id`` and ``_item_id``.

Conventions:
- numbers are coerced tolerantly (ASCII or Persian digits, thousands separators; ``None`` and
  garbage are skipped, never raise);
- the time range is ``since`` inclusive, ``until`` exclusive, on ``time_field``; a row whose time
  cannot be read is excluded when either bound is set;
- day and week buckets are computed in the given timezone and labelled with Jalali dates; a week
  starts on Saturday and is labelled by its first day;
- ``groups`` are ordered by label (chronologically for day / week); with ``top_n`` they are sorted by
  value descending (ties by label) and truncated;
- ``sum`` over no values is 0; ``avg`` / ``min`` / ``max`` over no values are ``None``.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Literal

from pydantic import BaseModel

from app.botspec.records import normalize_digits
from app.runtime.formatting import (
    EMPTY_VALUE,
    JALALI_MONTHS,
    get_tz,
    gregorian_to_jalali,
    parse_datetime,
    to_persian_digits,
)
from app.runtime.store import Record

MAX_ROWS = 20000  # callers load at most this many rows per collection

Row = dict[str, Any]
Scalar = str | int | float | bool

_THOUSANDS = str.maketrans("", "", ",٬  ")


class QuerySpec(BaseModel):
    measure: Literal["count", "sum", "avg", "min", "max"]
    field: str | None = None  # the measured field; count without a field counts rows
    group_by: str | None = None  # a field name (group_kind "field") or the time field for day / week
    group_kind: Literal["field", "status", "day", "week"] | None = None  # None + group_by = "field"
    status_in: list[str] | None = None
    equals: dict[str, Scalar] | None = None
    since: datetime | None = None
    until: datetime | None = None
    time_field: str = "_created_at"
    top_n: int | None = None
    fill_gaps: bool = False  # day / week groups: add empty buckets between since and until


class AggResult(BaseModel):
    value: float | None
    groups: list[tuple[str, float]]
    count: int  # rows that passed the filters


def rows_from_records(records: Iterable[Record]) -> list[Row]:
    out: list[Row] = []
    for r in records:
        row: Row = dict(r.data)
        row.update(
            _id=r.id,
            _status=r.status,
            _created_at=r.created_at,
            _updated_at=r.updated_at,
            _actor_id=r.actor_id,
            _item_id=r.item_id,
        )
        out.append(row)
    return out


def to_number(value: Any) -> float | None:
    """Tolerant numeric coercion; ``None`` for anything that is not a finite number."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        s = normalize_digits(value).strip().translate(_THOUSANDS).replace("٫", ".")
        try:
            number = float(s)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _tz(tz: str | tzinfo | None) -> tzinfo:
    return tz if isinstance(tz, tzinfo) else get_tz(tz)


# --- time buckets -----------------------------------------------------------------------------


def week_start(d: date) -> date:
    """The Saturday on or before ``d`` (Python weekday: Monday == 0, Saturday == 5)."""
    return d - timedelta(days=(d.weekday() + 2) % 7)


def day_label(d: date, *, with_year: bool = False) -> str:
    jy, jm, jd = gregorian_to_jalali(d)
    text = f"{to_persian_digits(jd)} {JALALI_MONTHS[jm - 1]}"
    return f"{text} {to_persian_digits(jy)}" if with_year else text


def _bucket_date(value: Any, kind: str, tz: tzinfo) -> date | None:
    dt = parse_datetime(value)
    if dt is None:
        return None
    d = dt.astimezone(tz).date()
    return week_start(d) if kind == "week" else d


def _bucket_label(d: date, kind: str, with_year: bool) -> str:
    text = day_label(d, with_year=with_year)
    return f"هفتهٔ {text}" if kind == "week" else text


# --- evaluation -------------------------------------------------------------------------------


def _eq(actual: Any, expected: Scalar) -> bool:
    if actual is None:
        return False
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual == expected
    a, e = to_number(actual), to_number(expected)
    if a is not None and e is not None:
        return a == e
    return str(actual) == str(expected)


def _passes(row: Row, spec: QuerySpec, since: datetime | None, until: datetime | None) -> bool:
    if spec.status_in is not None and row.get("_status") not in spec.status_in:
        return False
    if spec.equals:
        for key, expected in spec.equals.items():
            if not _eq(row.get(key), expected):
                return False
    if since is not None or until is not None:
        at = parse_datetime(row.get(spec.time_field))
        if at is None:
            return False
        if since is not None and at < since:
            return False
        if until is not None and at >= until:
            return False
    return True


def _measure(rows: Sequence[Row], measure: str, field: str | None) -> float | None:
    if measure == "count":
        if field is None:
            return float(len(rows))
        return float(sum(1 for r in rows if r.get(field) not in (None, "")))
    values = [n for r in rows if (n := to_number(r.get(field) if field else None)) is not None]
    if measure == "sum":
        return float(math.fsum(values))
    if not values:
        return None
    if measure == "avg":
        return math.fsum(values) / len(values)
    return min(values) if measure == "min" else max(values)


def _field_label(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return EMPTY_VALUE
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def evaluate(rows: Iterable[Row], spec: QuerySpec, *, tz: str | tzinfo | None = None) -> AggResult:
    zone = _tz(tz)
    since = parse_datetime(spec.since) if spec.since else None
    until = parse_datetime(spec.until) if spec.until else None
    kept = [r for r in rows if _passes(r, spec, since, until)]
    value = _measure(kept, spec.measure, spec.field)

    kind = spec.group_kind or ("field" if spec.group_by else None)
    if kind is None:
        return AggResult(value=value, groups=[], count=len(kept))

    groups: list[tuple[str, float]] = []
    if kind in ("day", "week"):
        source = spec.group_by or spec.time_field
        buckets: dict[date, list[Row]] = defaultdict(list)
        for r in kept:
            b = _bucket_date(r.get(source), kind, zone)
            if b is not None:
                buckets[b].append(r)
        if spec.fill_gaps and since is not None:
            last = None
            if until is not None:
                last = _bucket_date(until - timedelta(microseconds=1), kind, zone)
            elif buckets:
                last = max(buckets)
            cursor = _bucket_date(since, kind, zone)
            step = timedelta(days=7 if kind == "week" else 1)
            while cursor is not None and last is not None and cursor <= last:
                buckets.setdefault(cursor, [])
                cursor += step
        with_year = len({gregorian_to_jalali(d)[0] for d in buckets}) > 1
        for d in sorted(buckets):
            v = _measure(buckets[d], spec.measure, spec.field)
            if v is None:
                if buckets[d]:  # avg / min / max over a bucket with rows but no numbers
                    continue
                v = 0.0
            groups.append((_bucket_label(d, kind, with_year), v))
    else:
        by: dict[str, list[Row]] = defaultdict(list)
        for r in kept:
            raw = r.get("_status") if kind == "status" else r.get(spec.group_by or "")
            by[_field_label(raw)].append(r)
        for label in sorted(by):
            v = _measure(by[label], spec.measure, spec.field)
            if v is not None:
                groups.append((label, v))

    if spec.top_n is not None:
        groups = sorted(groups, key=lambda g: (-g[1], g[0]))[: max(spec.top_n, 0)]
    return AggResult(value=value, groups=groups, count=len(kept))
