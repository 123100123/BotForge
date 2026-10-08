"""Jalali (Solar Hijri) dates for input: Jalali -> Gregorian, typed date and time parsing, short
picker labels (U7, the Telegram event form). Pure functions, no clock reads, no new dependency.

Gregorian -> Jalali is ``formatting.gregorian_to_jalali`` (the "jalaali" break-table algorithm,
checked against ``jdatetime``). The inverse here is built on it instead of a second algorithm: the
first day of a Jalali year is found among March 19..22 of Gregorian year ``jy + 621`` by converting
those four days forward, so both directions always agree (round-trip tests cover 1900-2150 day by
day, month and year boundaries and leap years).

Typed input (``parse_date``): Persian, Arabic-Indic or Latin digits; separators ``/ - . ٫`` or
spaces. ``Y/M/D`` with a four-digit year is Jalali when the year is below 1700 and Gregorian
otherwise (``2026-10-12``); ``M/D`` means that day in the Jalali year of ``today``. Calendar-invalid
dates (``1404/12/30``: 1404 is not a leap year) are None.
"""

import re
from datetime import date, timedelta
from functools import cache

from app.botspec.records import normalize_digits
from app.runtime.formatting import JALALI_MONTHS, WEEKDAYS, gregorian_to_jalali, to_persian_digits

MIN_JALALI_YEAR = 1300
MAX_JALALI_YEAR = 1500
GREGORIAN_FROM = 1700  # a typed four-digit year at or above this is Gregorian

_SEPARATORS = re.compile(r"[\s/\-.٫,،]+")
_TIME = re.compile(r"^(\d{1,2})(?:\s*[:.٫]\s*(\d{1,2}))?$")


@cache
def farvardin_first(jy: int) -> date:
    """The Gregorian date of 1 Farvardin of Jalali year ``jy``."""
    gy = jy + 621
    for day in (19, 20, 21, 22):
        d = date(gy, 3, day)
        if gregorian_to_jalali(d) == (jy, 1, 1):
            return d
    raise ValueError(f"Jalali year {jy} out of supported range")  # pragma: no cover


def is_leap(jy: int) -> bool:
    """Whether Jalali year ``jy`` has 366 days (Esfand has 30 days)."""
    return (farvardin_first(jy + 1) - farvardin_first(jy)).days == 366


def month_days(jy: int, jm: int) -> int:
    """Days in Jalali month ``jm`` (1..12) of year ``jy``."""
    if not 1 <= jm <= 12:
        raise ValueError(f"Jalali month {jm} out of range")
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap(jy) else 29


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    """The Gregorian date of Jalali ``jy/jm/jd``; ValueError for a date that does not exist."""
    if not 1 <= jd <= month_days(jy, jm):
        raise ValueError(f"Jalali day {jy}/{jm}/{jd} does not exist")
    offset = (jm - 1) * 31 if jm <= 7 else 186 + (jm - 7) * 30
    return farvardin_first(jy) + timedelta(days=offset + jd - 1)


def parse_date(text: str, today: date) -> date | None:
    """A typed date (module docstring), or None when it is not a valid date."""
    parts = [p for p in _SEPARATORS.split(normalize_digits(text).strip()) if p]
    if not parts or not all(p.isascii() and p.isdigit() for p in parts):
        return None
    numbers = [int(p) for p in parts]
    if len(parts) == 2:
        jy = gregorian_to_jalali(today)[0]
        jm, jd = numbers
    elif len(parts) == 3 and len(parts[0]) == 4:
        year, month, day = numbers
        if year >= GREGORIAN_FROM:
            try:
                return date(year, month, day)
            except ValueError:
                return None
        jy, jm, jd = year, month, day
    else:
        return None
    if not MIN_JALALI_YEAR <= jy <= MAX_JALALI_YEAR:
        return None
    try:
        return jalali_to_gregorian(jy, jm, jd)
    except ValueError:
        return None


def parse_time(text: str) -> tuple[int, int] | None:
    """``"۱۸:۳۰"``, ``"18.30"``, ``"9"`` -> ``(hour, minute)``; None when not a valid 24-hour time."""
    m = _TIME.fullmatch(normalize_digits(text).strip())
    if m is None or not (m.group(1).isascii() and (m.group(2) or "0").isascii()):
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def day_month(d: date) -> str:
    """``"۱۹ مهر"``."""
    _, jm, jd = gregorian_to_jalali(d)
    return f"{to_persian_digits(jd)} {JALALI_MONTHS[jm - 1]}"


def weekday_day_month(d: date) -> str:
    """``"یکشنبه ۱۹ مهر"`` (the date picker's button label)."""
    return f"{WEEKDAYS[d.weekday()]} {day_month(d)}"


def full_date(d: date) -> str:
    """``"یکشنبه ۱۹ مهر ۱۴۰۵"``."""
    jy, _, _ = gregorian_to_jalali(d)
    return f"{weekday_day_month(d)} {to_persian_digits(jy)}"


def hhmm(hour: int, minute: int) -> str:
    """``(8, 0) -> "۰۸:۰۰"``."""
    return to_persian_digits(f"{hour:02d}:{minute:02d}")
