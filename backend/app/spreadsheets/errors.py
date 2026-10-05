"""Errors of the spreadsheet package (upload, reading, inspection).

Every error carries a stable ``code``, a Persian ``message_fa`` for the owner and the HTTP ``status`` the
upload API answers with (``app.api.uploads`` turns them into the standard error envelope). The Telegram
document path can reply with ``message_fa`` as is. ``str(error)`` is the code only, so logging an error
never logs file content.
"""

from app.runtime.formatting import format_decimal

UNSUPPORTED_MESSAGE = "فقط فایل‌های xlsx و csv پشتیبانی می‌شوند."
MACRO_MESSAGE = (
    "فایل‌های اکسل دارای ماکرو (مانند xlsm) پشتیبانی نمی‌شوند. "
    "فایل را با قالب xlsx ذخیره کنید و دوباره بفرستید."
)
DAMAGED_MESSAGE = "فایل خوانده نشد؛ ممکن است خراب باشد. فقط فایل‌های xlsx و csv پشتیبانی می‌شوند."
UNPACKED_TOO_LARGE_MESSAGE = "حجم داده‌های این فایل اکسل پس از باز شدن بیش از حد مجاز است."
TOO_COMPLEX_MESSAGE = "ساختار این فایل اکسل بیش از حد بزرگ یا پیچیده است و پردازش نمی‌شود."
EMPTY_MESSAGE = "فایل هیچ ردیف داده‌ای ندارد."
BUSY_MESSAGE = "سرور در حال پردازش فایل‌های دیگر است. چند لحظه دیگر دوباره تلاش کنید."
STORAGE_MESSAGE = "ذخیرهٔ فایل روی سرور ممکن نشد. کمی بعد دوباره تلاش کنید."
MISSING_FILE_MESSAGE = "فایل این بارگذاری روی سرور پیدا نشد."


def size_label(max_bytes: int) -> str:
    """``5 MiB -> "۵ مگابایت"``; below one megabyte in kilobytes."""
    if max_bytes >= 1024 * 1024:
        return f"{format_decimal(max_bytes / (1024 * 1024), 1)} مگابایت"
    return f"{format_decimal(max(max_bytes / 1024, 1), 0)} کیلوبایت"


def too_large_message(max_bytes: int) -> str:
    return f"حجم فایل بیش از حد مجاز است (حداکثر {size_label(max_bytes)})."


def too_many_columns_message(max_cols: int) -> str:
    return f"فایل بیش از {format_decimal(max_cols, 0)} ستون دارد و پشتیبانی نمی‌شود."


class SpreadsheetError(Exception):
    """Base class: ``code`` (stable, English) and ``message_fa`` (shown to the owner)."""

    status = 400

    def __init__(self, code: str, message_fa: str) -> None:
        super().__init__(code)
        self.code = code
        self.message_fa = message_fa


class FileTooLarge(SpreadsheetError):
    """The upload, or what its zip container would unpack to, is over a limit."""

    status = 413

    def __init__(self, message_fa: str = UNPACKED_TOO_LARGE_MESSAGE) -> None:
        super().__init__("upload_too_large", message_fa)


class UnsupportedFileType(SpreadsheetError):
    """Not an xlsx or csv file (judged from the bytes), macro-enabled, damaged, or too wide."""

    status = 415

    def __init__(self, message_fa: str = UNSUPPORTED_MESSAGE) -> None:
        super().__init__("unsupported_file_type", message_fa)


class EmptyWorkbook(SpreadsheetError):
    """The file holds no data row (nothing at all, or a header without rows)."""

    status = 422

    def __init__(self, message_fa: str = EMPTY_MESSAGE) -> None:
        super().__init__("empty_workbook", message_fa)


class UploadsBusy(SpreadsheetError):
    """Too many uploads are being received or processed at once (a process-wide cap)."""

    status = 503

    def __init__(self, message_fa: str = BUSY_MESSAGE) -> None:
        super().__init__("uploads_busy", message_fa)


class StorageUnavailable(SpreadsheetError):
    """The file could not be written to file storage (a server-side problem, logged)."""

    status = 503

    def __init__(self, message_fa: str = STORAGE_MESSAGE) -> None:
        super().__init__("storage_unavailable", message_fa)


class StoredFileMissing(SpreadsheetError):
    """An upload row whose bytes are no longer in file storage."""

    status = 404

    def __init__(self, message_fa: str = MISSING_FILE_MESSAGE) -> None:
        super().__init__("upload_file_missing", message_fa)
