"""Jalali input helpers (runtime/jalali.py, U7): Jalali -> Gregorian, typed dates and times."""

from datetime import date, timedelta

import pytest

from app.runtime import jalali
from app.runtime.formatting import gregorian_to_jalali


def test_round_trip_every_day_1900_to_2150() -> None:
    d, end = date(1900, 1, 1), date(2150, 12, 31)
    previous = gregorian_to_jalali(d - timedelta(days=1))
    while d <= end:
        j = gregorian_to_jalali(d)
        assert jalali.jalali_to_gregorian(*j) == d, (d, j)
        # consecutive days are consecutive Jalali days (month and year boundaries included)
        py, pm, pd = previous
        if j[2] == 1:
            assert pd == jalali.month_days(py, pm), (d, previous, j)
            assert (j[0], j[1]) == ((py, pm + 1) if pm < 12 else (py + 1, 1)), (d, previous, j)
        else:
            assert j == (py, pm, pd + 1), (d, previous, j)
        previous = j
        d += timedelta(days=1)


@pytest.mark.parametrize(
    ("jalali_date", "gregorian"),
    [
        ((1399, 12, 30), date(2021, 3, 20)),  # leap Esfand
        ((1400, 1, 1), date(2021, 3, 21)),
        ((1403, 12, 30), date(2025, 3, 20)),  # leap Esfand
        ((1404, 1, 1), date(2025, 3, 21)),
        ((1404, 12, 29), date(2026, 3, 20)),  # 1404 is not leap
        ((1405, 1, 1), date(2026, 3, 21)),
        ((1405, 6, 31), date(2026, 9, 22)),  # last 31-day month ...
        ((1405, 7, 1), date(2026, 9, 23)),  # ... then 30-day months
        ((1405, 7, 20), date(2026, 10, 12)),
        ((1402, 12, 10), date(2024, 2, 29)),  # a Gregorian leap day
        ((1378, 10, 11), date(2000, 1, 1)),
    ],
)
def test_known_dates(jalali_date: tuple[int, int, int], gregorian: date) -> None:
    assert jalali.jalali_to_gregorian(*jalali_date) == gregorian
    assert gregorian_to_jalali(gregorian) == jalali_date


def test_leap_years_and_month_lengths() -> None:
    assert [y for y in range(1395, 1412) if jalali.is_leap(y)] == [1395, 1399, 1403, 1408]
    assert [jalali.month_days(1403, m) for m in range(1, 13)] == [31] * 6 + [30] * 6
    assert jalali.month_days(1404, 12) == 29
    for bad in ((1404, 12, 30), (1405, 7, 31), (1405, 0, 1), (1405, 13, 1), (1405, 1, 0)):
        with pytest.raises(ValueError):
            jalali.jalali_to_gregorian(*bad)


TODAY = date(2026, 10, 4)  # 12 Mehr 1405


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("۱۴۰۵/۷/۲۰", date(2026, 10, 12)),
        ("1405-07-20", date(2026, 10, 12)),
        ("١٤٠٥/٧/٢٠", date(2026, 10, 12)),  # Arabic-Indic digits
        (" 1405 / 7 / 20 ", date(2026, 10, 12)),
        ("1405.7.20", date(2026, 10, 12)),
        ("۷/۲۰", date(2026, 10, 12)),  # no year: this Jalali year
        ("2026-10-12", date(2026, 10, 12)),  # a Gregorian year
        ("1403/12/30", date(2025, 3, 20)),
        ("1404/12/30", None),  # not a leap year
        ("1405/13/1", None),
        ("1405/7/31", None),
        ("2026-02-30", None),
        ("فردا", None),
        ("", None),
        ("20", None),
        ("05/7/20", None),  # a two-digit year is ambiguous
        ("1800/1/1", date(1800, 1, 1)),  # four digits from 1700 up: Gregorian
        ("1600/1/1", None),  # Jalali, outside the supported years
    ],
)
def test_parse_date(text: str, expected: date | None) -> None:
    assert jalali.parse_date(text, TODAY) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("۱۸:۳۰", (18, 30)),
        ("18:30", (18, 30)),
        ("8", (8, 0)),
        ("۰۸.۰۵", (8, 5)),
        ("23:59", (23, 59)),
        ("0:00", (0, 0)),
        ("24:00", None),
        ("18:60", None),
        ("18:30:00", None),
        ("ساعت ۶", None),
        ("", None),
    ],
)
def test_parse_time(text: str, expected: tuple[int, int] | None) -> None:
    assert jalali.parse_time(text) == expected


def test_labels() -> None:
    assert jalali.weekday_day_month(date(2026, 10, 11)) == "یکشنبه ۱۹ مهر"
    assert jalali.day_month(date(2026, 10, 12)) == "۲۰ مهر"
    assert jalali.full_date(date(2026, 10, 12)) == "دوشنبه ۲۰ مهر ۱۴۰۵"
    assert jalali.hhmm(8, 0) == "۰۸:۰۰"
