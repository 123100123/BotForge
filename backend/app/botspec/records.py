"""Record data validation and coercion against FieldDefs (frozen contract, WP0).

One function serves the web data admin, runtime form input, and scenario seeds.

Canonical stored forms (what ``validate_record`` puts in ``cleaned``):
  text / long_text -> str, stripped
  integer          -> int
  decimal          -> float (finite)
  boolean          -> bool
  choice           -> str, exactly one of FieldDef.choices
  phone            -> str of ASCII digits, optional leading "+" ("00" prefix becomes "+")
  datetime         -> str, timezone-aware UTC ISO 8601 with seconds: "2026-10-06T14:30:00+00:00"
                      (naive datetimes are rejected: the caller must state the offset)
  missing optional -> None

Persian (U+06F0..U+06F9) and Arabic-Indic (U+0660..U+0669) digits are normalized to ASCII
before parsing numbers, phones and datetimes. Error messages are Persian.
"""

import math
import re
from datetime import UTC, datetime
from typing import Any

from app.botspec.models import FieldDef, FieldType

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_THOUSANDS = str.maketrans("", "", ",٬، _")
_PHONE_STRIP = str.maketrans("", "", " -()‌‏‎")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")
_TRUE = {"true", "1", "yes", "y", "بله", "بلی", "آره", "درست", "صحیح"}
_FALSE = {"false", "0", "no", "n", "خیر", "نه", "نادرست", "غلط"}


class RecordValueError(ValueError):
    """A value could not be coerced; ``str(exc)`` is a Persian message for the user."""


def normalize_digits(text: str) -> str:
    """Map Persian and Arabic-Indic digits to ASCII digits."""
    return text.translate(_DIGITS)


def to_utc_iso(dt: datetime) -> str:
    """Canonical datetime storage form. ``dt`` must be timezone-aware."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def coerce_value(field: FieldDef, value: Any) -> Any:
    """Coerce one non-empty value to the field's canonical form or raise RecordValueError."""
    label = field.label
    t = field.type
    if t in (FieldType.text, FieldType.long_text):
        if isinstance(value, bool | int | float | str):
            return str(value).strip()
        raise RecordValueError(f"«{label}» باید متن باشد.")

    if t == FieldType.integer:
        if isinstance(value, bool):
            raise RecordValueError(f"«{label}» باید یک عدد صحیح باشد.")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            s = normalize_digits(value).strip().translate(_THOUSANDS)
            if re.fullmatch(r"[+-]?\d+", s):
                return int(s)
        raise RecordValueError(f"«{label}» باید یک عدد صحیح باشد.")

    if t == FieldType.decimal:
        if isinstance(value, bool):
            raise RecordValueError(f"«{label}» باید یک عدد باشد.")
        if isinstance(value, int | float):
            number = float(value)
        elif isinstance(value, str):
            s = normalize_digits(value).strip().replace("٫", ".").translate(_THOUSANDS)
            if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", s):
                raise RecordValueError(f"«{label}» باید یک عدد باشد.")
            number = float(s)
        else:
            raise RecordValueError(f"«{label}» باید یک عدد باشد.")
        if not math.isfinite(number):
            raise RecordValueError(f"«{label}» باید یک عدد باشد.")
        return number

    if t == FieldType.boolean:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            s = normalize_digits(value).strip().lower()
            if s in _TRUE:
                return True
            if s in _FALSE:
                return False
        raise RecordValueError(f"«{label}» باید «بله» یا «خیر» باشد.")

    if t == FieldType.choice:
        if isinstance(value, str):
            s = value.strip()
            if s in (field.choices or []):
                return s
        options = "، ".join(field.choices or [])
        raise RecordValueError(f"«{label}» باید یکی از این گزینه‌ها باشد: {options}")

    if t == FieldType.phone:
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        if isinstance(value, str):
            s = normalize_digits(value).strip().translate(_PHONE_STRIP)
            if s.startswith("00"):
                s = "+" + s[2:]
            if _PHONE_RE.fullmatch(s):
                return s
        raise RecordValueError(f"«{label}» شمارهٔ تلفن معتبر نیست.")

    if t == FieldType.datetime:
        dt: datetime | None = None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(normalize_digits(value).strip())
            except ValueError:
                dt = None
        if dt is None:
            raise RecordValueError(f"«{label}» باید تاریخ و ساعت معتبر (ISO 8601) باشد.")
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise RecordValueError(f"«{label}» باید منطقهٔ زمانی داشته باشد.")
        return to_utc_iso(dt)

    raise RecordValueError(f"«{label}» نوع ناشناخته دارد.")  # pragma: no cover


def validate_record(fields: list[FieldDef], data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate and coerce ``data`` against ``fields``.

    Returns ``(cleaned, errors)``. ``cleaned`` holds every field key (None for an absent optional
    field); keys of ``data`` that are not fields are ignored and not copied, so callers that must
    preserve hidden legacy keys (removed fields) merge them back themselves. A missing value falls
    back to ``FieldDef.default``. ``errors`` are Persian messages; the record is valid iff empty.
    """
    cleaned: dict[str, Any] = {}
    errors: list[str] = []
    for field in fields:
        raw = data.get(field.key)
        if _is_empty(raw):
            raw = field.default
        if _is_empty(raw):
            if field.required:
                errors.append(f"«{field.label}» الزامی است.")
            cleaned[field.key] = None
            continue
        try:
            cleaned[field.key] = coerce_value(field, raw)
        except RecordValueError as exc:
            errors.append(str(exc))
    return cleaned, errors
