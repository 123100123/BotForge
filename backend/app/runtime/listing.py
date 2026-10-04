"""Shared helpers for engines that list resource records (catalog, booking) (WP1).

- ``load_items``: records of a resource, filtered by an upcoming-only datetime field against
  ``event.now`` and sorted by a field (None values last, ties in creation order).
- ``paginate`` / ``nav_row``: fixed-size pages (``PAGE_SIZE`` = 8), 0-based page numbers in
  callback args, clamped when out of range.
- ``record_title`` / ``detail_lines``: rendering through ``formatting.format_field_value``.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.botspec.models import AnyCapability, FieldDef, Resource
from app.runtime import formatting
from app.runtime.callbacks import ACT_LIST
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx
from app.runtime.store import Record
from app.runtime.texts import common

PAGE_SIZE = 8
MAX_BUTTON_LABEL = 60


def field_of(resource: Resource, key: str | None) -> FieldDef | None:
    if key is None:
        return None
    return next((f for f in resource.fields if f.key == key), None)


def is_past(record: Record, field_key: str, now: datetime) -> bool:
    """True if the record's datetime ``field_key`` is before ``now`` (missing/invalid -> False)."""
    dt = formatting.parse_datetime(record.data.get(field_key))
    return dt is not None and dt < now


def _sort_value(value: Any) -> tuple[int, Any]:
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, int | float):
        return (1, float(value))
    return (2, str(value))  # strings (incl. UTC ISO datetimes, which sort chronologically)


def sort_records(records: list[Record], field_key: str | None, desc: bool = False) -> list[Record]:
    """Stable sort by ``field_key`` (None/missing values always last); no key -> id order
    (reversed when ``desc``)."""
    base = sorted(records, key=lambda r: r.id)
    if field_key is None:
        return list(reversed(base)) if desc else base
    present = [r for r in base if r.data.get(field_key) is not None]
    missing = [r for r in base if r.data.get(field_key) is None]
    # reverse=True keeps sort stability, so ties stay in creation order either way
    present.sort(key=lambda r: _sort_value(r.data.get(field_key)), reverse=desc)
    return present + missing


async def load_items(
    ctx: Ctx,
    resource: Resource,
    *,
    upcoming_only_field: str | None = None,
    sort_field: str | None = None,
    sort_desc: bool = False,
) -> list[Record]:
    records = await ctx.store.list_records(resource.key)
    if upcoming_only_field:
        records = [r for r in records if not is_past(r, upcoming_only_field, ctx.now)]
    return sort_records(records, sort_field, sort_desc)


def paginate(items: Sequence[Any], page: int | None, size: int = PAGE_SIZE) -> tuple[list[Any], int, int]:
    """Return ``(items_on_page, page, page_count)``; ``page`` is 0-based and clamped."""
    pages = max(1, -(-len(items) // size))
    p = min(max(page or 0, 0), pages - 1)
    return list(items[p * size : (p + 1) * size]), p, pages


def page_of(items: Sequence[Record], record_id: int, size: int = PAGE_SIZE) -> int:
    """0-based page on which ``record_id`` appears (0 if absent)."""
    for i, r in enumerate(items):
        if r.id == record_id:
            return i // size
    return 0


def page_indicator(page: int, pages: int) -> str:
    return common.PAGE_INDICATOR.replace("{page}", formatting.to_persian_digits(page + 1)).replace(
        "{pages}", formatting.to_persian_digits(pages)
    )


def nav_row(cap: AnyCapability, page: int, pages: int, action: str = ACT_LIST) -> list[Button]:
    """``[قبلی] [بعدی]`` for multi-page lists (empty list when there is a single page)."""
    row: list[Button] = []
    if page > 0:
        row.append(Ctx.button(common.PREVIOUS, cap, action, page - 1))
    if page < pages - 1:
        row.append(Ctx.button(common.NEXT, cap, action, page + 1))
    return row


def truncate(label: str, limit: int = MAX_BUTTON_LABEL) -> str:
    return label if len(label) <= limit else label[: limit - 1].rstrip() + "…"


def record_title(ctx: Ctx, resource: Resource, record: Record) -> str:
    """The record's ``title_field`` rendered, or ``#<id>`` (Persian digits) when it is empty."""
    field = field_of(resource, resource.title_field)
    value = record.data.get(resource.title_field)
    if field is None or value is None or value == "":
        return "#" + formatting.to_persian_digits(record.id)
    return ctx.fmt(field, value)


def detail_lines(ctx: Ctx, resource: Resource, record: Record, keys: Sequence[str]) -> str:
    """``"label: value"`` per key (keys not on the resource are skipped)."""
    lines = []
    for key in keys:
        field = field_of(resource, key)
        if field is not None:
            lines.append(f"{field.label}: {ctx.fmt(field, record.data.get(key))}")
    return "\n".join(lines)
