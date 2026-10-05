"""Evaluator and period edge cases (pure, no store)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.reporting.periods import period_bounds
from app.runtime.aggregate import QuerySpec, evaluate, rows_from_records, to_number
from app.runtime.store import Record

TEHRAN = ZoneInfo("Asia/Tehran")


def at(day: int, hour: int = 6, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


def row(created: datetime, **kw: object) -> dict:
    return {"_created_at": created, "_status": kw.pop("status", None), **kw}


def test_empty_rows() -> None:
    assert evaluate([], QuerySpec(measure="count"), tz=TEHRAN).value == 0
    assert evaluate([], QuerySpec(measure="sum", field="x"), tz=TEHRAN).value == 0
    for m in ("avg", "min", "max"):
        assert evaluate([], QuerySpec(measure=m, field="x"), tz=TEHRAN).value is None  # type: ignore[arg-type]
    res = evaluate([], QuerySpec(measure="count", group_kind="status"), tz=TEHRAN)
    assert res.groups == [] and res.count == 0


def test_tolerant_numbers() -> None:
    assert to_number("۱٬۲۳۴") == 1234
    assert to_number("12,500") == 12500
    assert to_number("۳٫۵") == 3.5
    assert to_number("abc") is None and to_number(None) is None and to_number(float("nan")) is None
    rows = [{"v": 10}, {"v": "۲۰"}, {"v": None}, {"v": "x"}, {}]
    spec = QuerySpec(measure="avg", field="v")
    assert evaluate(rows, spec, tz=TEHRAN).value == 15
    assert evaluate(rows, QuerySpec(measure="sum", field="v"), tz=TEHRAN).value == 30
    assert evaluate(rows, QuerySpec(measure="max", field="v"), tz=TEHRAN).value == 20
    assert evaluate(rows, QuerySpec(measure="count", field="v"), tz=TEHRAN).value == 3  # non-empty values


def test_filters_and_time_range() -> None:
    rows = [
        row(at(1), status="a", kind="x"),
        row(at(2), status="b", kind="x"),
        row(at(3), status="a", kind="y"),
        {"_status": "a", "kind": "x"},  # no readable time
    ]
    assert evaluate(rows, QuerySpec(measure="count", status_in=["a"]), tz=TEHRAN).value == 3
    assert evaluate(rows, QuerySpec(measure="count", equals={"kind": "x"}), tz=TEHRAN).value == 3
    spec = QuerySpec(measure="count", since=at(2), until=at(3))  # since inclusive, until exclusive
    assert evaluate(rows, spec, tz=TEHRAN).value == 1
    assert evaluate(rows, QuerySpec(measure="count", equals={"n": 5}), tz=TEHRAN).value == 0
    assert evaluate([{"n": "۵"}], QuerySpec(measure="count", equals={"n": 5}), tz=TEHRAN).value == 1


def test_group_by_field_status_and_top_n() -> None:
    rows = [
        row(at(1), status="new", title="A", qty=1),
        row(at(1), status="new", title="B", qty=5),
        row(at(1), status="done", title="A", qty="۴"),
        row(at(1), status="done", title=None, qty=2),
    ]
    by_status = evaluate(rows, QuerySpec(measure="count", group_kind="status"), tz=TEHRAN)
    assert by_status.groups == [("done", 2), ("new", 2)]
    top = evaluate(rows, QuerySpec(measure="sum", field="qty", group_by="title", top_n=2), tz=TEHRAN)
    assert top.groups == [("A", 5), ("B", 5)]  # desc, ties by label
    top1 = evaluate(rows, QuerySpec(measure="sum", field="qty", group_by="title", top_n=1), tz=TEHRAN)
    assert top1.groups == [("A", 5)]
    assert top1.value == 12
    missing = evaluate(rows, QuerySpec(measure="count", group_by="title"), tz=TEHRAN)
    assert ("—", 1) in missing.groups


def test_day_buckets_use_timezone_and_jalali_labels() -> None:
    # 21:00 UTC on 4 Oct is 00:30 on 5 Oct in Tehran (UTC+3:30): the next Jalali day.
    rows = [row(at(4, 21)), row(at(5, 6)), row(at(5, 7)), row(at(7, 6))]
    res = evaluate(rows, QuerySpec(measure="count", group_kind="day"), tz=TEHRAN)
    assert res.groups == [("۱۳ مهر", 3), ("۱۵ مهر", 1)]
    utc = evaluate(rows, QuerySpec(measure="count", group_kind="day"), tz=UTC)
    assert utc.groups[0] == ("۱۲ مهر", 1)


def test_fill_gaps_and_week_buckets() -> None:
    rows = [row(at(1)), row(at(5))]
    spec = QuerySpec(measure="count", group_kind="day", fill_gaps=True, since=at(1, 0), until=at(7, 0))
    res = evaluate(rows, spec, tz=TEHRAN)
    assert [v for _, v in res.groups] == [1, 0, 0, 0, 1, 0, 0]  # 1..7 Oct, Tehran days
    # Saturday-start weeks: 2026-10-03 is a Saturday; the 1st and 2nd belong to the week of 26 Sep.
    weeks = evaluate(
        [row(at(1)), row(at(2)), row(at(3)), row(at(9))],
        QuerySpec(measure="count", group_kind="week"),
        tz=TEHRAN,
    )
    assert weeks.groups == [("هفتهٔ ۴ مهر", 2), ("هفتهٔ ۱۱ مهر", 2)]


def test_rows_from_records_flattens() -> None:
    now = at(1)
    rec = Record(id=7, collection="c", data={"total": 5, "_id": "spoof"}, status="new", actor_id="a",
                 item_id=3, created_at=now, updated_at=now)  # fmt: skip
    (r,) = rows_from_records([rec])
    assert r["total"] == 5 and r["_id"] == 7 and r["_status"] == "new"
    assert r["_actor_id"] == "a" and r["_item_id"] == 3 and r["_created_at"] == now


NOW = datetime(2026, 10, 6, 8, 30, tzinfo=UTC)  # Tuesday 14 Mehr 1405, 12:00 in Tehran


def local(d: datetime | None) -> str:
    assert d is not None
    return d.astimezone(TEHRAN).strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize(
    ("period", "since", "until", "prev_since", "prev_until"),
    [
        ("today", "2026-10-06 00:00", "2026-10-06 12:00", "2026-10-05 00:00", "2026-10-05 12:00"),
        ("yesterday", "2026-10-05 00:00", "2026-10-06 00:00", "2026-10-04 00:00", "2026-10-05 00:00"),
        ("7d", "2026-09-30 00:00", "2026-10-06 12:00", "2026-09-23 00:00", "2026-09-29 12:00"),
        ("this_week", "2026-10-03 00:00", "2026-10-06 12:00", "2026-09-26 00:00", "2026-09-29 12:00"),
        ("last_week", "2026-09-26 00:00", "2026-10-03 00:00", "2026-09-19 00:00", "2026-09-26 00:00"),
        ("this_month", "2026-09-23 00:00", "2026-10-06 12:00", "2026-08-23 00:00", "2026-09-05 12:00"),
    ],
)
def test_period_bounds(period: str, since: str, until: str, prev_since: str, prev_until: str) -> None:
    got = period_bounds(period, NOW, TEHRAN)  # type: ignore[arg-type]
    assert [local(got[0]), local(got[1]), local(got[2]), local(got[3])] == [
        since,
        until,
        prev_since,
        prev_until,
    ]


def test_period_bounds_30d_and_all() -> None:
    since, until, prev_since, prev_until = period_bounds("30d", NOW, "Asia/Tehran")
    assert since is not None and prev_since is not None and prev_until is not None
    assert until - since == timedelta(days=29, hours=8, minutes=30) + timedelta(hours=3, minutes=30)
    assert prev_since == since - timedelta(days=30) and prev_until <= since
    assert period_bounds("all", NOW, TEHRAN) == (None, NOW, None, None)
