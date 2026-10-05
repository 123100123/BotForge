"""The parts of the spreadsheet service and its errors that need no database: display names, error
codes and Persian messages, the parser thread (app/spreadsheets/{service,errors}.py)."""

import threading

import pytest

from app.spreadsheets.errors import (
    EmptyWorkbook,
    FileTooLarge,
    StorageUnavailable,
    StoredFileMissing,
    UnsupportedFileType,
    UploadsBusy,
    size_label,
    too_large_message,
)
from app.spreadsheets.service import MAX_DISPLAY_NAME, display_filename, run_parser


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("فروش مهر.xlsx", "فروش مهر.xlsx"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\ali\\Desktop\\report.csv", "report.csv"),
        ("/tmp/x/../report.xlsx", "report.xlsx"),
        ("invoice\u202excod.xlsx", "invoicexcod.xlsx"),  # RLO would display it reversed
        ("a\x00b\nc\td.csv", "a b c d.csv"),  # control characters become spaces
        ("  my   file .csv  ", "my file .csv"),
        ("..", ""),
        ("", ""),
        (None, ""),
        ("می‌خواهم.csv", "می‌خواهم.csv"),  # ZWNJ is part of Persian spelling
    ],
)
def test_display_filename(raw: str | None, expected: str) -> None:
    assert display_filename(raw) == expected


def test_long_names_are_shortened_keeping_the_extension() -> None:
    name = display_filename("ب" * 300 + ".xlsx")
    assert len(name) == MAX_DISPLAY_NAME and name.endswith(".xlsx")
    assert len(display_filename("x" * 300)) == MAX_DISPLAY_NAME


def test_error_codes_statuses_and_messages() -> None:
    assert size_label(5 * 1024 * 1024) == "۵ مگابایت"
    assert size_label(1536 * 1024) == "۱٫۵ مگابایت"
    assert size_label(2048) == "۲ کیلوبایت"
    assert too_large_message(5 * 1024 * 1024) == "حجم فایل بیش از حد مجاز است (حداکثر ۵ مگابایت)."
    expected = {
        FileTooLarge: (413, "upload_too_large"),
        UnsupportedFileType: (415, "unsupported_file_type"),
        EmptyWorkbook: (422, "empty_workbook"),
        UploadsBusy: (503, "uploads_busy"),
        StorageUnavailable: (503, "storage_unavailable"),
        StoredFileMissing: (404, "upload_file_missing"),
    }
    for cls, (status, code) in expected.items():
        error = cls()
        assert (error.status, error.code, str(error)) == (status, code, code)  # str() never has content
        assert error.message_fa


async def test_parsing_runs_on_one_dedicated_thread() -> None:
    names = {await run_parser(lambda: threading.current_thread().name) for _ in range(3)}
    assert len(names) == 1 and next(iter(names)).startswith("spreadsheet-parse")
    assert threading.current_thread().name not in names
