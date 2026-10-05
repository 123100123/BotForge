"""Deterministic workbook inspection: column profiles, sample rows and a layout signature per file.

Pure: bytes in, ``WorkbookInspection`` out. No I/O, no clock, no randomness, so a file always gets the
same inspection (the analysis layer relies on that to recognise a layout it has seen before).

Per column: ``inferred_type`` is the type of at least 80% of the non-empty values (integers count
towards ``decimal`` too), else ``text``; ``empty`` when the column has no value. ``distinct`` stops
counting at ``DISTINCT_CAP``; ``sample`` holds the first five distinct values as text; ``min``/``max``
are given for numeric and datetime columns, ``mean`` for numeric ones, all over the values of the
inferred type only.

Signature: SHA-1 over the sheet name and the ordered column names, each passed through
``normalize_label`` (case, whitespace, digits, Arabic/Persian letter variants, ZWNJ), and the column
types. ``integer`` and ``decimal`` count as one type there ("number"), so a day on which a numeric
column happens to hold only whole numbers does not look like a new layout. ``column_signature`` is
the signature of one sheet; the workbook signature is the same formula over all its sheets, so for a
single-sheet file (every csv) the two are equal.

Size: an inspection is stored with the upload and listed fifty at a time, so ``fit_budget`` trims
sample rows, then samples, until the JSON is at most ``MAX_INSPECTION_BYTES`` (columns, types and
statistics are never trimmed).
"""

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from app.botspec.records import normalize_digits
from app.schemas.business import ColumnProfile, SheetProfile, WorkbookInspection
from app.spreadsheets.errors import EmptyWorkbook
from app.spreadsheets.reader import (
    DEFAULT_MAX_COLUMNS,
    DEFAULT_MAX_ROWS,
    Cell,
    SheetRows,
    display,
    iter_sheets,
    truncate,
)
from app.spreadsheets.storage import FileKind

__all__ = ["column_signature", "fit_budget", "inspect", "normalize_label", "workbook_signature"]

ColumnType = Literal["text", "integer", "decimal", "datetime", "boolean", "empty"]

DISTINCT_CAP = 10_000
SAMPLE_VALUES = 5
SAMPLE_ROWS = 10
MAX_SAMPLE_CHARS = 40
MAX_CELL_CHARS = 80
MAX_INSPECTION_BYTES = 256 * 1024
_DISTINCT_KEY_CHARS = 64  # longer strings are tracked by a 16-byte digest
_TRUE_KEY = ("bool", True)
_FALSE_KEY = ("bool", False)
_ISO_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{6})?(?:[+-]\d{2}:\d{2})?)?", re.ASCII)
_SIGNATURE_FAMILY = {"integer": "number", "decimal": "number"}
_LABEL_FOLD = str.maketrans(
    {
        "ي": "ی",  # Arabic yeh
        "ى": "ی",  # Arabic alef maksura
        "ك": "ک",  # Arabic kaf
        0x200C: " ",  # zero-width non-joiner: "تاریخ ثبت" written with or without it is one name
        # zero-width space and joiner, direction marks, Arabic letter mark, BOM, tatweel (kashida)
        **dict.fromkeys([0x200B, 0x200D, 0x200E, 0x200F, 0x061C, 0xFEFF, 0x0640]),
    }
)


def normalize_label(text: str) -> str:
    """The comparison form of a sheet or column name (used by the signature and schema matching)."""
    folded = normalize_digits(unicodedata.normalize("NFKC", text).translate(_LABEL_FOLD))
    return " ".join(folded.casefold().split())


def _layout(sheet: SheetProfile) -> list[Any]:
    family = _SIGNATURE_FAMILY.get
    columns = [[normalize_label(c.name), family(c.inferred_type, c.inferred_type)] for c in sheet.columns]
    return [normalize_label(sheet.name), columns]


def _digest(layouts: list[Any]) -> str:
    payload = json.dumps(layouts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8", "surrogatepass"), usedforsecurity=False).hexdigest()


def column_signature(sheet: SheetProfile) -> str:
    """The layout signature of one sheet (sheet name, ordered column names, column types)."""
    return _digest([_layout(sheet)])


def workbook_signature(sheets: Sequence[SheetProfile]) -> str:
    """The layout signature of a whole file: ``column_signature``'s formula over all its sheets."""
    return _digest([_layout(sheet) for sheet in sheets])


def _moment(text: str) -> datetime | None:
    """A normalised ISO string as a naive UTC-comparable datetime, or None if it is not one."""
    if not _ISO_SHAPE.fullmatch(text):
        return None
    try:
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is not None:
            moment = moment.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, OverflowError):
        return None
    return moment


def _distinct_key(value: Cell) -> object:
    if value is True:
        return _TRUE_KEY  # True == 1 in a set; a boolean column must not merge with a numeric one
    if value is False:
        return _FALSE_KEY
    if isinstance(value, str) and len(value) > _DISTINCT_KEY_CHARS:
        return hashlib.blake2b(value.encode("utf-8", "surrogatepass"), digest_size=16).digest()
    return value


def _number_text(value: int | float) -> str:
    return repr(value) if isinstance(value, float) else str(value)


def _finite_mean(total: float, count: int) -> float | None:
    mean = total / count
    return mean if math.isfinite(mean) else None  # huge floats can overflow the running total


class _Column:
    """Running statistics of one column; memory stays bounded by ``DISTINCT_CAP``."""

    __slots__ = (
        "bool_count",
        "distinct",
        "dt_count",
        "dt_max",
        "dt_min",
        "float_count",
        "float_total",
        "int_count",
        "int_max",
        "int_min",
        "int_total",
        "non_null",
        "num_max",
        "num_min",
        "sample",
    )

    def __init__(self) -> None:
        self.non_null = self.bool_count = self.dt_count = self.int_count = self.float_count = 0
        self.int_total = 0
        self.float_total = 0.0
        self.int_min: int | None = None
        self.int_max: int | None = None
        self.num_min: int | float | None = None
        self.num_max: int | float | None = None
        self.dt_min: tuple[datetime, str] | None = None
        self.dt_max: tuple[datetime, str] | None = None
        self.distinct: set[object] = set()
        self.sample: list[str] = []

    def add(self, value: Cell) -> None:
        if value is None:
            return
        self.non_null += 1
        key = _distinct_key(value)
        if len(self.distinct) < DISTINCT_CAP and key not in self.distinct:
            self.distinct.add(key)
            if len(self.sample) < SAMPLE_VALUES:
                self.sample.append(truncate(display(value), MAX_SAMPLE_CHARS))
        if isinstance(value, bool):
            self.bool_count += 1
        elif isinstance(value, int):
            self.int_count += 1
            self.int_total += value
            if self.int_min is None or value < self.int_min:
                self.int_min = value
            if self.int_max is None or value > self.int_max:
                self.int_max = value
            self._number(value)
        elif isinstance(value, float):
            self.float_count += 1
            self.float_total += value
            self._number(value)
        else:
            moment = _moment(value)
            if moment is not None:
                self.dt_count += 1
                if self.dt_min is None or moment < self.dt_min[0]:
                    self.dt_min = (moment, value)
                if self.dt_max is None or moment > self.dt_max[0]:
                    self.dt_max = (moment, value)

    def _number(self, value: int | float) -> None:
        if self.num_min is None or value < self.num_min:
            self.num_min = value
        if self.num_max is None or value > self.num_max:
            self.num_max = value

    def inferred_type(self) -> ColumnType:
        total = self.non_null
        if total == 0:
            return "empty"
        candidates: tuple[tuple[ColumnType, int], ...] = (
            ("integer", self.int_count),
            ("decimal", self.int_count + self.float_count),
            ("datetime", self.dt_count),
            ("boolean", self.bool_count),
        )
        for kind, count in candidates:
            if 5 * count >= 4 * total:  # at least 80%, in exact integer arithmetic
                return kind
        return "text"

    def profile(self, name: str) -> ColumnProfile:
        kind = self.inferred_type()
        low = high = None
        mean = None
        if kind == "integer" and self.int_min is not None and self.int_max is not None:
            low, high = str(self.int_min), str(self.int_max)
            mean = _finite_mean(self.int_total, self.int_count)
        elif kind == "decimal" and self.num_min is not None and self.num_max is not None:
            low, high = _number_text(self.num_min), _number_text(self.num_max)
            mean = _finite_mean(self.int_total + self.float_total, self.int_count + self.float_count)
        elif kind == "datetime" and self.dt_min is not None and self.dt_max is not None:
            low, high = self.dt_min[1], self.dt_max[1]
        return ColumnProfile(
            name=name,
            inferred_type=kind,
            non_null=self.non_null,
            distinct=len(self.distinct),
            sample=list(self.sample),
            min=low,
            max=high,
            mean=mean,
        )


def _sample_cell(value: Cell) -> Cell:
    return truncate(value, MAX_CELL_CHARS) if isinstance(value, str) else value


def _profile_sheet(sheet: SheetRows) -> SheetProfile:
    columns = [_Column() for _ in sheet.headers]
    sample_rows: list[dict[str, Any]] = []
    for row in sheet.rows:
        for column, value in zip(columns, row, strict=True):
            column.add(value)
        if len(sample_rows) < SAMPLE_ROWS:
            sample_rows.append({h: _sample_cell(v) for h, v in zip(sheet.headers, row, strict=True)})
    return SheetProfile(
        name=sheet.name,
        rows=sheet.rows.rows_read,
        columns=[column.profile(header) for column, header in zip(columns, sheet.headers, strict=True)],
        sample_rows=sample_rows,
    )


def _json_size(inspection: WorkbookInspection) -> int:
    return len(inspection.model_dump_json().encode("utf-8", "surrogatepass"))


def _trimmed(inspection: WorkbookInspection, rows_kept: int, samples_kept: int) -> WorkbookInspection:
    sheets = [
        sheet.model_copy(
            update={
                "sample_rows": sheet.sample_rows[:rows_kept],
                "columns": [c.model_copy(update={"sample": c.sample[:samples_kept]}) for c in sheet.columns],
            }
        )
        for sheet in inspection.sheets
    ]
    return inspection.model_copy(update={"sheets": sheets})


def fit_budget(inspection: WorkbookInspection, max_bytes: int = MAX_INSPECTION_BYTES) -> WorkbookInspection:
    """``inspection`` trimmed until its JSON is at most ``max_bytes``: sample rows to three, then none,
    then column samples to one, then none. Columns, types, statistics and the signature are kept, so
    the result can still exceed the budget for a very wide workbook (about 300 KB at the limits)."""
    if _json_size(inspection) <= max_bytes:
        return inspection
    trimmed = inspection
    for rows_kept, samples_kept in ((3, SAMPLE_VALUES), (0, SAMPLE_VALUES), (0, 1), (0, 0)):
        trimmed = _trimmed(inspection, rows_kept, samples_kept)
        if _json_size(trimmed) <= max_bytes:
            break
    return trimmed


def inspect(
    data: bytes, kind: FileKind, *, max_rows: int = DEFAULT_MAX_ROWS, max_cols: int = DEFAULT_MAX_COLUMNS
) -> WorkbookInspection:
    """The inspection of a sniffed file (``reader.sniff``). ``EmptyWorkbook`` when no sheet has a data
    row; the other ``SpreadsheetError`` subclasses come from reading the file."""
    sheets: list[SheetProfile] = []
    row_limit_hit = False
    for sheet in iter_sheets(data, kind, max_rows=max_rows, max_cols=max_cols):
        sheets.append(_profile_sheet(sheet))
        row_limit_hit = row_limit_hit or sheet.rows.row_limit_hit
    if not any(sheet.rows for sheet in sheets):
        raise EmptyWorkbook()
    inspection = WorkbookInspection(
        sheets=sheets, signature=workbook_signature(sheets), row_limit_hit=row_limit_hit
    )
    return fit_budget(inspection)
