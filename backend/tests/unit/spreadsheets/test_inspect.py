"""Inspection: inferred types, statistics, samples, the layout signature and the size budget
(app/spreadsheets/inspect.py)."""

import csv
import io
from datetime import datetime

import pytest

from app.schemas.business import ColumnProfile, WorkbookInspection
from app.spreadsheets import inspect as inspect_module
from app.spreadsheets.errors import EmptyWorkbook
from app.spreadsheets.inspect import column_signature, fit_budget, inspect, normalize_label
from tests.unit.spreadsheets.workbooks import csv_bytes, make_xlsx


def columns(data: bytes, kind: str = "csv", **limits: int) -> dict[str, ColumnProfile]:
    result = inspect(data, kind, **limits)  # type: ignore[arg-type]
    return {c.name: c for c in result.sheets[0].columns}


def csv_of(header: list[str], rows: list[list[object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows([["" if v is None else v for v in row] for row in rows])
    return buffer.getvalue().encode()


def test_types_follow_an_80_percent_majority() -> None:
    data = csv_of(
        ["ints", "mostly_ints", "too_mixed", "money", "when", "paid", "notes", "nothing"],
        [
            [1, 1, 1, 1, "2026-10-01", "true", "a", None],
            [2, 2, 2, "2.5", "2026-10-02 10:00", "false", "b", None],
            [3, 3, 3, 3, "2026/10/03", "true", "c", None],
            [4, 4, "x", "4.25", "2026-10-04T08:30:00+03:30", "true", "d", None],
            [5, "n/a", "y", 5, "2026-10-05", "false", "e", None],
        ],
    )
    found = columns(data)
    assert {name: c.inferred_type for name, c in found.items()} == {
        "ints": "integer",
        "mostly_ints": "integer",  # 4 of 5 is exactly 80%
        "too_mixed": "text",  # 3 of 5
        "money": "decimal",
        "when": "datetime",
        "paid": "boolean",
        "notes": "text",
        "nothing": "empty",
    }


def test_statistics() -> None:
    data = csv_of(
        ["qty", "price", "when", "name"],
        [
            [3, "۱۲٫۵", "2026-10-05T10:00:00+03:30", "علی"],
            [1, 7, "2026-10-01", "رضا"],
            [2, "1,000.25", "2026-10-05T06:00:00Z", "علی"],
            ["x", None, None, None],
            [6, 0.5, "2026-10-03", "مینا"],
        ],
    )
    found = columns(data)
    qty, price, when, name = found["qty"], found["price"], found["when"], found["name"]
    assert (qty.inferred_type, qty.min, qty.max, qty.mean, qty.non_null) == ("integer", "1", "6", 3.0, 5)
    assert (price.inferred_type, price.min, price.max) == ("decimal", "0.5", "1000.25")
    assert price.mean == pytest.approx((12.5 + 7 + 1000.25 + 0.5) / 4)
    # 10:00+03:30 is 06:30 UTC, after 06:00Z; the original strings are reported
    assert (when.min, when.max, when.mean) == ("2026-10-01", "2026-10-05T10:00:00+03:30", None)
    assert (name.inferred_type, name.min, name.max, name.mean) == ("text", None, None, None)
    assert name.distinct == 3 and name.sample == ["علی", "رضا", "مینا"]


def test_samples_are_distinct_first_seen_and_short() -> None:
    long_value = "ب" * 100
    data = csv_of(["v"], [[x] for x in ["a", "a", "b", long_value, "c", "d", "e", "f"]])
    sample = columns(data)["v"].sample
    assert len(sample) == 5 and sample[:3] == ["a", "b", sample[2]]
    assert sample[2].endswith("…") and len(sample[2]) == inspect_module.MAX_SAMPLE_CHARS
    assert sample[3:] == ["c", "d"]


def test_distinct_tracking_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inspect_module, "DISTINCT_CAP", 3)
    data = csv_of(["v"], [[i] for i in range(10)])
    assert columns(data)["v"].distinct == 3


def test_booleans_and_numbers_stay_distinct_values() -> None:
    data = make_xlsx({"S": [["v"], [True], [1], [1.0], [False], [0]]})
    assert columns(data, "xlsx")["v"].distinct == 4  # True, 1 (== 1.0), False, 0


def test_sample_rows_are_the_first_ten_rows() -> None:
    data = csv_of(["n", "text"], [[i, "x" * 200] for i in range(15)])
    sheet = inspect(data, "csv").sheets[0]
    assert sheet.rows == 15 and len(sheet.sample_rows) == 10
    assert sheet.sample_rows[0]["n"] == 0
    assert len(sheet.sample_rows[0]["text"]) == inspect_module.MAX_CELL_CHARS


def test_persian_digits_are_numbers() -> None:
    data = csv_of(["مبلغ"], [["۱۲۰"], ["٣٤٥"], ["۱٬۰۰۰"]])
    column = columns(data)["مبلغ"]
    assert (column.inferred_type, column.min, column.max) == ("integer", "120", "1000")


def test_the_row_cap_is_reported() -> None:
    data = csv_of(["n"], [[i] for i in range(20)])
    result = inspect(data, "csv", max_rows=10)
    assert result.sheets[0].rows == 10 and result.row_limit_hit
    assert not inspect(data, "csv", max_rows=20).row_limit_hit


def _signature(header: list[str], rows: list[list[object]], sheet: str = "Sales") -> str:
    return inspect(make_xlsx({sheet: [header, *rows]}), "xlsx").signature


def test_the_signature_is_stable_for_the_same_layout() -> None:
    base = _signature(["name", "amount", "date"], [["ali", 10, "2026-10-01"], ["reza", 20, "2026-10-02"]])
    other_data = _signature(["name", "amount", "date"], [["mina", 99, "2026-11-30"]])
    assert base == other_data
    whole_vs_fraction = _signature(["name", "amount", "date"], [["mina", 9.5, "2026-11-30"]])
    assert base == whole_vs_fraction  # integer and decimal are one type for the signature


@pytest.mark.parametrize(
    ("header", "rows", "sheet"),
    [
        (["name", "total", "date"], [["ali", 10, "2026-10-01"]], "Sales"),  # renamed column
        (["amount", "name", "date"], [[10, "ali", "2026-10-01"]], "Sales"),  # reordered
        (["name", "amount", "date"], [["ali", 10, "2026-10-01"]], "Stock"),  # renamed sheet
        (["name", "amount", "date"], [["ali", "ten", "2026-10-01"]], "Sales"),  # amount became text
        (["name", "amount", "date", "note"], [["ali", 10, "2026-10-01", "x"]], "Sales"),  # new column
    ],
)
def test_the_signature_changes_with_the_layout(
    header: list[str], rows: list[list[object]], sheet: str
) -> None:
    base = _signature(["name", "amount", "date"], [["ali", 10, "2026-10-01"]])
    assert _signature(header, rows, sheet) != base


def test_cosmetic_name_differences_keep_the_signature() -> None:
    persian = _signature(["تاریخ ثبت", "مبلغ کل", "Note"], [["2026-10-01", 1, "x"]], "گزارش")
    variants = _signature(["تاريخ‌ثبت", " مبلغ  كل ", "NOTE"], [["2026-10-01", 2, "y"]], "گزارش")
    assert persian == variants
    assert normalize_label("مبلغ‌كل ۱۲") == normalize_label("مبلغ کل 12") == "مبلغ کل 12"


def test_column_signature_per_sheet() -> None:
    single = inspect(make_xlsx({"S": [["a"], [1]]}), "xlsx")
    assert single.signature == column_signature(single.sheets[0])  # same formula, one sheet
    multi = inspect(make_xlsx({"S": [["a"], [1]], "T": [["b"], ["x"]]}), "xlsx")
    assert column_signature(multi.sheets[0]) == single.signature
    assert multi.signature not in {column_signature(s) for s in multi.sheets}


def test_csv_is_one_sheet_named_csv() -> None:
    result = inspect(csv_of(["a"], [[1]]), "csv")
    assert [s.name for s in result.sheets] == ["csv"]
    assert result.signature == column_signature(result.sheets[0])


@pytest.mark.parametrize(
    "data",
    [
        csv_bytes(["a,b,c"]),  # a header and no rows
        csv_bytes(["   ", ""]),
        make_xlsx({"S": [], "T": [[None, None]]}),
        make_xlsx({"S": [["only", "a", "header"]]}),
    ],
)
def test_files_without_data_rows_are_empty(data: bytes) -> None:
    kind = "xlsx" if data.startswith(b"PK") else "csv"
    with pytest.raises(EmptyWorkbook) as error:
        inspect(data, kind)  # type: ignore[arg-type]
    assert error.value.status == 422 and error.value.code == "empty_workbook"


def test_a_header_only_sheet_is_kept_beside_a_sheet_with_data() -> None:
    result = inspect(make_xlsx({"Data": [["a"], [1]], "Template": [["x", "y"]]}), "xlsx")
    assert [(s.name, s.rows, [c.inferred_type for c in s.columns]) for s in result.sheets] == [
        ("Data", 1, ["integer"]),
        ("Template", 0, ["empty", "empty"]),
    ]


def test_inspection_is_deterministic() -> None:
    data = make_xlsx(
        {
            "A": [["n", "when", "t"], *[[i * 1.5, datetime(2026, 1, 1 + i), f"v{i % 3}"] for i in range(20)]],
            "B": [["k"], ["x"], ["y"]],
        }
    )
    assert inspect(data, "xlsx").model_dump() == inspect(data, "xlsx").model_dump()


def test_the_size_budget_trims_samples_but_keeps_the_layout() -> None:
    wide = [
        [f"column {i}" for i in range(60)],
        *[[f"{'value ' * 12}{r}-{i}" for i in range(60)] for r in range(10)],
    ]
    full = inspect(make_xlsx({"S": wide}), "xlsx")
    assert inspect_module._json_size(full) > 20_000
    trimmed = fit_budget(full, max_bytes=20_000)
    assert inspect_module._json_size(trimmed) <= 20_000
    assert trimmed.signature == full.signature
    assert [(c.name, c.inferred_type, c.distinct) for c in trimmed.sheets[0].columns] == [
        (c.name, c.inferred_type, c.distinct) for c in full.sheets[0].columns
    ]
    assert len(trimmed.sheets[0].sample_rows) < len(full.sheets[0].sample_rows)
    tiny = fit_budget(full, max_bytes=1)  # can't fit: everything trimmable is gone, the rest is kept
    assert tiny.sheets[0].sample_rows == [] and all(c.sample == [] for c in tiny.sheets[0].columns)
    assert isinstance(WorkbookInspection.model_validate(tiny.model_dump()), WorkbookInspection)
