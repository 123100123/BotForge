"""Persian rendering of numbers, datetimes and record field values (WP1).

Pure functions; no clock reads. Datetimes are rendered as Jalali (Solar Hijri) dates in the bot's
timezone. The Gregorian -> Jalali conversion is the standard "jalaali" break-table algorithm,
valid for Jalali years 1..3177 (checked against ``jdatetime`` for every day of 1900-2150).
"""

from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.botspec.models import FieldDef, FieldType
from app.botspec.records import normalize_digits

DEFAULT_TZ = "Asia/Tehran"
EMPTY_VALUE = "—"
THOUSANDS_SEP = "٬"  # U+066C ARABIC THOUSANDS SEPARATOR
DECIMAL_SEP = "٫"  # U+066B ARABIC DECIMAL SEPARATOR

_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)  # fmt: skip
# Indexed by datetime.weekday(): Monday == 0.
WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")

_BREAKS = (
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
    1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178,
)  # fmt: skip


def to_persian_digits(text: str | int) -> str:
    """Replace ASCII digits with Persian digits."""
    return str(text).translate(_TO_PERSIAN)


def to_ascii_digits(text: str) -> str:
    """Replace Persian and Arabic-Indic digits with ASCII digits (for parsing user input)."""
    return normalize_digits(text)


def format_int(value: int) -> str:
    """``12345 -> "۱۲٬۳۴۵"``."""
    sign = "-" if value < 0 else ""
    return sign + to_persian_digits(f"{abs(value):,}".replace(",", THOUSANDS_SEP))


def format_decimal(value: float, max_places: int = 2) -> str:
    """Up to ``max_places`` decimals, trailing zeros dropped: ``1234.5 -> "۱٬۲۳۴٫۵"``."""
    if float(value).is_integer():
        return format_int(int(value))
    sign = "-" if value < 0 else ""
    text = f"{abs(value):,.{max_places}f}".rstrip("0").rstrip(".")
    text = text.replace(",", "\x00").replace(".", DECIMAL_SEP).replace("\x00", THOUSANDS_SEP)
    return sign + to_persian_digits(text)


# --- Jalali calendar -------------------------------------------------------------------------


def _farvardin_first_march_day(jy: int) -> int:
    """Day of March (Gregorian year jy + 621) on which 1 Farvardin of Jalali year ``jy`` falls."""
    if not _BREAKS[0] <= jy < _BREAKS[-1]:
        raise ValueError(f"Jalali year {jy} out of supported range")
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += (jump // 33) * 8 + (jump % 33) // 4
        jp = jm
    n = jy - jp
    leap_j += (n // 33) * 8 + ((n % 33) + 3) // 4
    if jump % 33 == 4 and jump - n == 4:
        leap_j += 1
    leap_g = gy // 4 - ((gy // 100 + 1) * 3) // 4 - 150
    return 20 + leap_j - leap_g


def gregorian_to_jalali(d: date) -> tuple[int, int, int]:
    """Return ``(year, month, day)`` in the Jalali calendar."""
    jy = d.year - 621
    start = date(d.year, 3, _farvardin_first_march_day(jy))
    if d < start:
        jy -= 1
        start = date(d.year - 1, 3, _farvardin_first_march_day(jy))
    k = (d - start).days
    if k < 186:
        return jy, 1 + k // 31, k % 31 + 1
    k -= 186
    return jy, 7 + k // 30, k % 30 + 1


# --- datetimes -------------------------------------------------------------------------------


@lru_cache(maxsize=32)
def get_tz(name: str | None) -> ZoneInfo:
    """ZoneInfo for ``name``; falls back to Asia/Tehran for an unknown or empty name."""
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def parse_datetime(value: Any) -> datetime | None:
    """Parse a stored datetime (UTC ISO string or aware datetime); None if absent or invalid.

    A naive value is interpreted as UTC (stored values are always UTC).
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(normalize_digits(value.strip()))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def to_local(value: datetime, tz: str | None = DEFAULT_TZ) -> datetime:
    return value.astimezone(get_tz(tz))


def format_jalali_date(value: datetime | date, tz: str | None = DEFAULT_TZ) -> str:
    """``"۱۲ مهر ۱۴۰۵"`` (converted to ``tz`` first when given a datetime)."""
    d = to_local(value, tz).date() if isinstance(value, datetime) else value
    jy, jm, jd = gregorian_to_jalali(d)
    return f"{to_persian_digits(jd)} {JALALI_MONTHS[jm - 1]} {to_persian_digits(jy)}"


def format_time(value: datetime, tz: str | None = DEFAULT_TZ) -> str:
    """``"۱۸:۳۰"`` in ``tz``."""
    return to_persian_digits(to_local(value, tz).strftime("%H:%M"))


def format_datetime(value: datetime | str, tz: str | None = DEFAULT_TZ) -> str:
    """``"یکشنبه ۱۲ مهر ۱۴۰۵، ساعت ۱۸:۳۰"`` in ``tz``. Unparseable input is returned as text."""
    dt = parse_datetime(value)
    if dt is None:
        return str(value)
    local = to_local(dt, tz)
    return f"{WEEKDAYS[local.weekday()]} {format_jalali_date(local.date())}، ساعت {format_time(local, tz)}"


# --- record fields ---------------------------------------------------------------------------


def format_field_value(field: FieldDef, value: Any, tz: str | None = DEFAULT_TZ) -> str:
    """Render one stored record value for users. Never raises; falls back to ``str(value)``.

    boolean -> بله/خیر; choice/text -> as is; integer/decimal -> Persian digits with separators;
    datetime -> Jalali date and time in ``tz``; phone -> as stored (ASCII, so Telegram links it);
    missing -> "—".
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return EMPTY_VALUE
    t = field.type
    try:
        if t == FieldType.boolean:
            if isinstance(value, bool):
                return "بله" if value else "خیر"
            return str(value)
        if t == FieldType.integer and isinstance(value, int | float) and not isinstance(value, bool):
            return format_int(int(value)) if float(value).is_integer() else format_decimal(float(value))
        if t == FieldType.decimal and isinstance(value, int | float) and not isinstance(value, bool):
            return format_decimal(float(value))
        if t == FieldType.datetime:
            return format_datetime(value, tz)
    except (ValueError, OverflowError):
        return str(value)
    return str(value)
