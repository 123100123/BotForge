"""Reader: type sniffing from the bytes, container guards, CSV decoding, bounded row iteration and value
normalisation (app/spreadsheets/reader.py)."""

import contextlib
import csv
import io
import time as clock
from datetime import date, datetime, time, timedelta

import pytest

from app.spreadsheets import reader
from app.spreadsheets.errors import (
    DAMAGED_MESSAGE,
    MACRO_MESSAGE,
    UNSUPPORTED_MESSAGE,
    EmptyWorkbook,
    FileTooLarge,
    UnsupportedFileType,
)
from app.spreadsheets.reader import iter_rows, iter_sheets, normalize_cell, parse_number, sniff
from tests.unit.spreadsheets.workbooks import csv_bytes, make_xlsx, rewrite_xlsx, sheet_xml, zip_bytes

SIMPLE = make_xlsx({"Sales": [["name", "amount"], ["ali", 12], ["reza", 15]]})


def rows_of(
    data: bytes, kind: str = "xlsx", sheet: str | None = None, **limits: int
) -> tuple[list, list, bool]:
    headers, rows = iter_rows(data, kind, sheet, **limits)  # type: ignore[arg-type]
    values = list(rows)
    return headers, values, rows.row_limit_hit


# --- Sniffing ------------------------------------------------------------------------------------


def test_the_type_comes_from_the_bytes_not_the_name() -> None:
    assert sniff(SIMPLE, "report.csv") == "xlsx"
    assert sniff(csv_bytes(["a,b", "1,2"]), "report.xlsx") == "csv"
    assert sniff(SIMPLE, "") == "xlsx"


@pytest.mark.parametrize(
    "parts",
    [
        {"xl/vbaProject.bin": b"\xd0\xcf\x11\xe0 fake vba"},
        {"xl/VBAProject.bin": b"case variants are the same OPC part"},
        {"xl/macrosheets/sheet1.xml": "<xm:macrosheet/>"},
        {"xl/intlmacrosheets/sheet1.xml": "<xm:macrosheet/>"},
    ],
)
def test_macro_parts_are_refused(parts: dict[str, bytes | str]) -> None:
    with pytest.raises(UnsupportedFileType) as error:
        sniff(rewrite_xlsx(SIMPLE, parts), "report.xlsx")
    assert error.value.status == 415 and error.value.code == "unsupported_file_type"
    assert error.value.message_fa == MACRO_MESSAGE


def test_a_macro_enabled_content_type_is_refused_even_without_a_vba_part() -> None:
    content_types = sheet_part(SIMPLE, "[Content_Types].xml").replace(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    )
    with pytest.raises(UnsupportedFileType) as error:
        sniff(rewrite_xlsx(SIMPLE, {"[Content_Types].xml": content_types}), "report.xlsx")
    assert error.value.message_fa == MACRO_MESSAGE


@pytest.mark.parametrize("name", ["report.xlsm", "REPORT.XLSM ", "t.xltm", "a.xlam", "b.xlsb"])
def test_macro_enabled_extensions_are_refused_whatever_the_bytes(name: str) -> None:
    with pytest.raises(UnsupportedFileType) as error:
        sniff(SIMPLE, name)
    assert error.value.message_fa == MACRO_MESSAGE


def sheet_part(data: bytes, name: str) -> str:
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(name).decode()


@pytest.mark.parametrize(
    "parts",
    [
        {"readme.txt": "not a workbook"},
        {"[Content_Types].xml": "<Types/>", "xl/workbook.bin": b"\x00xlsb"},  # xlsb: binary workbook
        {"xl/workbook.xml": "<workbook/>"},  # no content types
    ],
)
def test_a_zip_that_is_not_an_xlsx_workbook_is_refused(parts: dict[str, bytes | str]) -> None:
    with pytest.raises(UnsupportedFileType) as error:
        sniff(zip_bytes(parts), "data.xlsx")
    assert error.value.message_fa == UNSUPPORTED_MESSAGE


def test_a_truncated_workbook_is_refused_as_damaged() -> None:
    with pytest.raises(UnsupportedFileType) as error:
        sniff(SIMPLE[: len(SIMPLE) // 2], "data.xlsx")
    assert error.value.message_fa == DAMAGED_MESSAGE


def test_too_many_zip_entries_is_too_large() -> None:
    padding = {f"xl/media/pad{i}.txt": "x" for i in range(reader.MAX_ZIP_ENTRIES)}
    with pytest.raises(FileTooLarge) as error:
        sniff(rewrite_xlsx(SIMPLE, padding), "data.xlsx")
    assert error.value.status == 413 and error.value.code == "upload_too_large"


def test_the_declared_uncompressed_total_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    assert reader.MAX_UNCOMPRESSED_BYTES == 60 * 1024 * 1024
    monkeypatch.setattr(reader, "MAX_UNCOMPRESSED_BYTES", 1024 * 1024)
    bomb = rewrite_xlsx(SIMPLE, {"xl/media/zeros.bin": b"\x00" * (2 * 1024 * 1024)})
    assert len(bomb) < 64 * 1024  # small on the wire, large once inflated
    with pytest.raises(FileTooLarge):
        sniff(bomb, "data.xlsx")
    with pytest.raises(FileTooLarge):  # reading checks the container too, not only sniff
        list(iter_sheets(bomb, "xlsx"))


def test_xlsx_is_refused_when_expat_is_too_old(monkeypatch: pytest.MonkeyPatch) -> None:
    from pyexpat import version_info

    assert version_info >= (2, 4, 1)  # the deployment assumption: entity expansion limits exist
    monkeypatch.setattr(reader, "_EXPAT_SAFE", False)
    with pytest.raises(UnsupportedFileType):
        sniff(SIMPLE, "data.xlsx")


@pytest.mark.parametrize(
    "payload",
    [
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01",
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00",
        b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\x00",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00",  # legacy .xls / encrypted xlsx (OLE2)
        bytes(range(256)) * 4,
    ],
)
def test_binary_files_are_refused(payload: bytes) -> None:
    with pytest.raises(UnsupportedFileType):
        sniff(payload, "data.csv")


def test_csv_decoding_utf8_bom_and_windows_1256() -> None:
    bom = b"\xef\xbb\xbf" + csv_bytes(["نام,مبلغ", "علی,۱۰۰"])
    assert sniff(bom, "data.csv") == "csv"
    assert rows_of(bom, "csv")[:2] == (["نام", "مبلغ"], [["علی", 100]])
    # Old Windows exports: Windows-1256 has the Arabic yeh and no Persian digits.
    legacy = csv_bytes(["نام,مبلغ", "علي,100"], encoding="cp1256")
    assert sniff(legacy, "data.csv") == "csv"
    assert rows_of(legacy, "csv")[:2] == (["نام", "مبلغ"], [["علي", 100]])


def test_a_csv_wider_than_the_column_cap_is_refused() -> None:
    wide = csv_bytes([",".join(f"c{i}" for i in range(11)), ",".join("1" * 11)])
    with pytest.raises(UnsupportedFileType) as error:
        sniff(wide, "wide.csv", max_cols=10)
    assert "۱۰ ستون" in error.value.message_fa
    assert sniff(wide, "wide.csv", max_cols=11) == "csv"


def test_a_one_column_file_counts_as_csv_only_when_named_csv() -> None:
    data = csv_bytes(["name", "ali", "reza"])
    assert sniff(data, "names.csv") == "csv"
    assert rows_of(data, "csv")[:2] == (["name"], [["ali"], ["reza"]])
    with pytest.raises(UnsupportedFileType):
        sniff(data, "notes.txt")


def test_a_short_csv_with_a_title_line_is_still_read() -> None:
    data = csv_bytes(["گزارش فروش مهر", "نام,مبلغ", "علی,100", "رضا,200"])
    assert sniff(data, "report.txt") == "csv"
    headers, values, _ = rows_of(data, "csv")
    assert headers == ["گزارش فروش مهر"]  # the first non-empty row is the header, as specified
    assert values[0] == ["نام"]


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_other_delimiters(delimiter: str) -> None:
    data = csv_bytes([delimiter.join(["a", "b", "c"]), delimiter.join(["1", "2,5", "x"])])
    assert sniff(data, "d.csv") == "csv"
    assert rows_of(data, "csv")[:2] == (["a", "b", "c"], [[1, "2,5", "x"]])


def test_csv_sniffing_sees_a_bounded_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    original = csv.Sniffer.sniff

    def spy(self: csv.Sniffer, sample: str, delimiters: str | None = None) -> type[csv.Dialect]:
        seen.append(len(sample))
        return original(self, sample, delimiters)

    monkeypatch.setattr(csv.Sniffer, "sniff", spy)
    hostile = (',"a' * 400_000).encode()  # quadratic for the Sniffer's quote regexes
    started = clock.perf_counter()
    with contextlib.suppress(UnsupportedFileType):
        sniff(hostile, "x.csv")
    assert seen and max(seen) <= reader.SNIFF_SAMPLE_CHARS
    assert clock.perf_counter() - started < 10


# --- Rows ----------------------------------------------------------------------------------------


def test_header_is_the_first_non_empty_row_and_names_are_unique() -> None:
    data = make_xlsx(
        {
            "S": [
                [None, None],
                [],
                ["name", None, "name", " Total \n Amount ", None],
                ["ali", "x", "y", 5, "lost"],
            ]
        }
    )
    headers, values, _ = rows_of(data)
    assert headers == ["name", "col_2", "name_2", "Total Amount"]  # width ends at the last header
    assert values == [["ali", "x", "y", 5]]


def test_values_are_normalised() -> None:
    data = csv_bytes(
        [
            "persian,arabic,grouped,decimal,phone,card,flag,iso,slashed,jalali,blank",
            '۱۲۳,٤٥٦,"۱٬۲۵۰٬۰۰۰",۱۲٫۵,09121234567,6037991234567890,TRUE,'
            "2026-10-05,2026/10/05 14:30,1405/07/14, ",
        ]
    )
    headers, values, _ = rows_of(data, "csv")
    assert dict(zip(headers, values[0], strict=True)) == {
        "persian": 123,
        "arabic": 456,
        "grouped": 1250000,
        "decimal": 12.5,
        "phone": "09121234567",
        "card": "6037991234567890",
        "flag": True,
        "iso": "2026-10-05",
        "slashed": "2026-10-05T14:30:00",
        "jalali": "1405/07/14",
        "blank": None,
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (datetime(2026, 10, 5, 14, 30), "2026-10-05T14:30:00"),
        (datetime(2026, 10, 5), "2026-10-05"),
        (date(2026, 10, 5), "2026-10-05"),
        (time(9, 5), "09:05:00"),
        (timedelta(hours=26, minutes=5), "26:05:00"),
        (float("inf"), None),
        (float("nan"), None),
        (2**60, str(2**60)),
        ("  ", None),
        ("2026-13-45", "2026-13-45"),
        ("2026-10-05T10:00:00Z", "2026-10-05T10:00:00+00:00"),
        ("2026-10-05 10:00+03:30", "2026-10-05T10:00:00+03:30"),
        ("-1,234.5", -1234.5),
        ("1,23", "1,23"),
        ("007", "007"),
        ("0.5", 0.5),
        ("False", False),
        ("nan", "nan"),
        ("inf", "inf"),
        ("１２", "１２"),  # fullwidth digits are not read as numbers
    ],
)
def test_normalize_cell(raw: object, expected: object) -> None:
    assert normalize_cell(raw) == expected
    assert type(normalize_cell(raw)) is type(expected)


def test_parse_number_rejects_identifiers() -> None:
    assert parse_number("1234567890123456") is None  # 16 digits
    assert parse_number("123456789012345") == 123456789012345
    assert parse_number("+7") == 7


def test_formulas_are_never_evaluated() -> None:
    data = make_xlsx({"S": [["a", "b"], ["=1+1", '=HYPERLINK("http://example.com","x")']]})
    assert rows_of(data)[1] == []  # no cached results: the cells are empty, never computed or echoed


def test_the_row_cap_truncates_and_flags() -> None:
    data = make_xlsx({"S": [["n"], *[[i] for i in range(8)]]})
    _, values, hit = rows_of(data, max_rows=5)
    assert values == [[0], [1], [2], [3], [4]] and hit
    assert rows_of(data, max_rows=8)[2] is False


def test_a_huge_row_number_does_not_make_the_reader_spin() -> None:
    xml = sheet_xml(SIMPLE)
    xml = xml.replace(
        "</sheetData>", '<row r="999999999999"><c r="A999999999999"><v>1</v></c></row></sheetData>'
    )
    xml = xml.replace('<dimension ref="A1:B3" />', '<dimension ref="A1:XFD1048576" />')
    assert "999999999999" in xml and "XFD1048576" in xml  # both hostile numbers are in place
    bomb = rewrite_xlsx(SIMPLE, {"xl/worksheets/sheet1.xml": xml})
    started = clock.perf_counter()
    headers, values, hit = rows_of(bomb, max_rows=100)
    assert clock.perf_counter() - started < 10
    assert headers == ["name", "amount"] and len(values) == 2 and hit


def test_columns_beyond_the_cap_are_not_read() -> None:
    data = make_xlsx({"S": [[f"c{i}" for i in range(30)], list(range(30))]})
    headers, values, _ = rows_of(data, max_cols=10)
    assert headers == [f"c{i}" for i in range(10)] and values == [list(range(10))]


def test_blank_line_floods_stop_at_the_scan_limit() -> None:
    data = ("a,b\n1,2\n" + "\n" * 50_000 + "3,4\n").encode()
    _, values, hit = rows_of(data, "csv", max_rows=10)
    assert values == [[1, 2]] and hit  # the last row is past the scan limit: flagged, not read


def test_sheets_are_selected_by_name_and_a_missing_one_is_empty() -> None:
    data = make_xlsx({"One": [["a"], [1]], "Empty": [], "Two": [["b"], [2]]})
    assert [s.name for s in _consume(iter_sheets(data, "xlsx"))] == ["One", "Two"]
    assert rows_of(data, sheet="Two")[:2] == (["b"], [[2]])
    with pytest.raises(EmptyWorkbook):
        iter_rows(data, "xlsx", "Missing")


def test_closing_a_stream_early_releases_the_workbook() -> None:
    data = make_xlsx({"S": [["n"], *[[i] for i in range(50)]]})
    _, rows = iter_rows(data, "xlsx")
    assert next(rows) == [0]
    rows.close()
    rows.close()  # idempotent
    with pytest.raises(StopIteration):
        next(rows)


def test_a_damaged_sheet_fails_soft() -> None:
    broken = rewrite_xlsx(SIMPLE, {"xl/worksheets/sheet1.xml": "<worksheet><sheetData><row"})
    with pytest.raises(UnsupportedFileType) as error:
        rows_of(broken)
    assert error.value.message_fa == DAMAGED_MESSAGE


def _consume(sheets):  # type: ignore[no-untyped-def]
    found = []
    for sheet in sheets:
        list(sheet.rows)
        found.append(sheet)
    return found
