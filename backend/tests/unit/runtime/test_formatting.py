from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.botspec.models import FieldDef, FieldType
from app.runtime import formatting as f


def fd(type_: str, **kw: object) -> FieldDef:
    return FieldDef(key="k", label="برچسب", type=FieldType(type_), **kw)  # type: ignore[arg-type]


def test_persian_digits_round_trip() -> None:
    assert f.to_persian_digits("0123456789 abc") == "۰۱۲۳۴۵۶۷۸۹ abc"
    assert f.to_persian_digits(2026) == "۲۰۲۶"
    assert f.to_ascii_digits("۰۹۱۲ ٣٤٥") == "0912 345"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "۰"), (7, "۷"), (999, "۹۹۹"), (1000, "۱٬۰۰۰"), (1234567, "۱٬۲۳۴٬۵۶۷"), (-25000, "-۲۵٬۰۰۰")],
)
def test_format_int(value: int, expected: str) -> None:
    assert f.format_int(value) == expected


def test_format_decimal() -> None:
    assert f.format_decimal(1234.5) == "۱٬۲۳۴٫۵"
    assert f.format_decimal(2.0) == "۲"
    assert f.format_decimal(0.126) == "۰٫۱۳"  # two places max
    assert f.format_decimal(1234567.25) == "۱٬۲۳۴٬۵۶۷٫۲۵"
    assert f.format_decimal(-3.75) == "-۳٫۷۵"


@pytest.mark.parametrize(
    ("greg", "jalali"),
    [
        (date(2026, 3, 21), (1405, 1, 1)),  # Nowruz 1405
        (date(2026, 3, 20), (1404, 12, 29)),
        (date(2025, 3, 20), (1403, 12, 30)),  # 1403 is a leap year
        (date(2026, 10, 4), (1405, 7, 12)),
        (date(2026, 9, 22), (1405, 6, 31)),
        (date(2026, 9, 23), (1405, 7, 1)),
        (date(2000, 1, 1), (1378, 10, 11)),
        (date(1979, 2, 11), (1357, 11, 22)),
    ],
)
def test_gregorian_to_jalali(greg: date, jalali: tuple[int, int, int]) -> None:
    assert f.gregorian_to_jalali(greg) == jalali


def test_jalali_is_monotonic_over_years() -> None:
    d = date(2020, 1, 1)
    prev = f.gregorian_to_jalali(d)
    for _ in range(366 * 8):
        d += timedelta(days=1)
        cur = f.gregorian_to_jalali(d)
        assert cur > prev
        assert 1 <= cur[1] <= 12 and 1 <= cur[2] <= (31 if cur[1] <= 6 else 30)
        prev = cur


def test_datetime_rendering_in_bot_timezone() -> None:
    # 20:45 UTC on Sunday 4 Oct 2026 is 00:15 on Monday 13 Mehr 1405 in Tehran (UTC+03:30)
    dt = datetime(2026, 10, 4, 20, 45, tzinfo=UTC)
    assert f.format_datetime(dt) == "دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۰۰:۱۵"
    assert f.format_datetime(dt.isoformat()) == "دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۰۰:۱۵"
    assert f.format_datetime(dt, "UTC") == "یکشنبه ۱۲ مهر ۱۴۰۵، ساعت ۲۰:۴۵"
    plus2 = timezone(timedelta(hours=2))
    assert f.format_datetime(dt.astimezone(plus2)) == "دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۰۰:۱۵"
    assert f.format_jalali_date(dt) == "۱۳ مهر ۱۴۰۵"
    assert f.format_time(dt) == "۰۰:۱۵"


def test_unknown_timezone_falls_back_to_tehran() -> None:
    dt = datetime(2026, 10, 4, 20, 45, tzinfo=UTC)
    assert f.format_datetime(dt, "Mars/Olympus") == f.format_datetime(dt, "Asia/Tehran")


def test_parse_datetime() -> None:
    assert f.parse_datetime("2026-10-04T08:00:00+00:00") == datetime(2026, 10, 4, 8, tzinfo=UTC)
    assert f.parse_datetime("2026-10-04T08:00:00") == datetime(2026, 10, 4, 8, tzinfo=UTC)  # naive = UTC
    assert f.parse_datetime("nonsense") is None
    assert f.parse_datetime(None) is None
    assert f.parse_datetime(12) is None


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (fd("boolean"), True, "بله"),
        (fd("boolean"), False, "خیر"),
        (fd("choice", choices=["کوچک", "بزرگ"]), "بزرگ", "بزرگ"),
        (fd("integer"), 1500000, "۱٬۵۰۰٬۰۰۰"),
        (fd("integer"), 3.0, "۳"),
        (fd("decimal"), 2.5, "۲٫۵"),
        (fd("decimal"), 4, "۴"),
        (fd("text"), "سلام 123", "سلام 123"),
        (fd("long_text"), "خط۱\nخط۲", "خط۱\nخط۲"),
        (fd("phone"), "+989121234567", "+989121234567"),
        (fd("datetime"), "2026-03-20T20:30:00+00:00", "شنبه ۱ فروردین ۱۴۰۵، ساعت ۰۰:۰۰"),
        (fd("datetime"), "bad value", "bad value"),
        (fd("text"), None, "—"),
        (fd("integer"), "", "—"),
        (fd("integer"), "legacy", "legacy"),
        (fd("boolean"), "maybe", "maybe"),
    ],
)
def test_format_field_value(field: FieldDef, value: object, expected: str) -> None:
    assert f.format_field_value(field, value) == expected
