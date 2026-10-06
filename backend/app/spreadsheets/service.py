"""Spreadsheet ingestion and reads: the one entry point for uploaded files (the web upload today,
Telegram documents next) and what the analysis layer reads back.

``ingest`` checks the size, sniffs the type from the bytes, inspects the workbook, stores the bytes
under a server-generated key and adds the ``uploaded_files`` row (flushed; the CALLER commits, and a
failed flush removes the stored file again). A commit that fails afterwards leaves an unreferenced
file behind; files are only ever reached through their row.

The CPU-bound part (sniffing, inspection, SHA-256, and an analysis run's metrics through
``compute_on_rows``) runs on one dedicated worker thread (``PARSE_WORKERS``): the event loop, which also
serves every bot's webhook, stays responsive, and at most one workbook is parsed at a time, which bounds
the memory a parse can take (an xlsx may inflate to ``reader.MAX_UNCOMPRESSED_BYTES``). Callers that
receive files from the network should also bound how many they hold in memory at once
(``app.api.uploads`` caps uploads in flight).
"""

import asyncio
import hashlib
import logging
import unicodedata
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Bot, UploadedFileRow
from app.schemas.business import UploadOut, WorkbookInspection
from app.spreadsheets.errors import (
    EmptyWorkbook,
    FileTooLarge,
    StorageUnavailable,
    StoredFileMissing,
    too_large_message,
)
from app.spreadsheets.inspect import inspect
from app.spreadsheets.reader import (
    DEFAULT_MAX_COLUMNS,
    DEFAULT_MAX_ROWS,
    INVISIBLE_CHARS,
    Cell,
    iter_rows,
    sniff,
)
from app.spreadsheets.storage import FileKind, FileStorage, get_storage, key_kind, new_key

log = logging.getLogger(__name__)

UploadSource = Literal["web", "telegram"]
UPLOAD_SOURCES: tuple[UploadSource, ...] = ("web", "telegram")
CONTENT_TYPES: dict[FileKind, str] = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}
MAX_DISPLAY_NAME = 120
LIST_LIMIT = 50
PARSE_WORKERS = 1

_PARSER = ThreadPoolExecutor(max_workers=PARSE_WORKERS, thread_name_prefix="spreadsheet-parse")


async def run_parser[T](func: Callable[..., T], *args: object) -> T:
    """Run ``func(*args)`` on the dedicated parser thread. If the caller is cancelled while the call
    is still queued it never runs; once running it finishes, and the next call waits for it."""
    return await asyncio.wrap_future(_PARSER.submit(func, *args))


def display_filename(name: str | None) -> str:
    """A safe display name from a client-supplied file name: the last path segment, control and bidi
    characters removed, whitespace collapsed, leading and trailing dots and spaces stripped, at most
    ``MAX_DISPLAY_NAME`` characters (the extension is kept when shortening). Display only: it never
    becomes a path. May be empty."""
    text = unicodedata.normalize("NFC", name or "").replace("\\", "/").rsplit("/", 1)[-1]
    text = " ".join(text.translate(INVISIBLE_CHARS).split()).strip(" .")
    if len(text) <= MAX_DISPLAY_NAME:
        return text
    stem, dot, extension = text.rpartition(".")
    if dot and stem and 0 < len(extension) <= 10:
        return stem[: MAX_DISPLAY_NAME - len(extension) - 1].rstrip(" .") + "." + extension
    return text[:MAX_DISPLAY_NAME].rstrip(" .")


def _analyse(
    data: bytes, filename: str, max_rows: int, max_cols: int
) -> tuple[FileKind, WorkbookInspection, str]:
    kind = sniff(data, filename, max_cols=max_cols)
    inspection = inspect(data, kind, max_rows=max_rows, max_cols=max_cols)
    return kind, inspection, hashlib.sha256(data).hexdigest()


async def _discard(storage: FileStorage, key: str) -> None:
    try:
        await storage.delete(key)
    except Exception:
        log.exception("could not remove stored upload after a failed insert")


async def ingest(
    session: AsyncSession,
    bot: Bot,
    data: bytes,
    filename: str,
    *,
    source: UploadSource,
    uploaded_by: str | None,
    settings: Settings,
    storage: FileStorage | None = None,
) -> UploadOut:
    """Validate, inspect and store one uploaded file of ``bot`` (see the module docstring).

    Raises ``FileTooLarge`` (over ``UPLOAD_MAX_BYTES``, or a zip that would inflate past the limits),
    ``UnsupportedFileType`` (not xlsx/csv by its bytes, macro-enabled, damaged, too many columns) or
    ``EmptyWorkbook`` (no data row). The caller authorises the upload and commits."""
    if source not in UPLOAD_SOURCES:
        raise ValueError(f"unknown upload source {source!r}")
    bot_id = bot.id  # read before anything can expire the ORM object
    if len(data) > settings.UPLOAD_MAX_BYTES:
        raise FileTooLarge(too_large_message(settings.UPLOAD_MAX_BYTES))
    if not data:
        raise EmptyWorkbook()
    name = display_filename(filename)
    kind, inspection, digest = await run_parser(
        _analyse, data, name, settings.SPREADSHEET_MAX_ROWS, settings.SPREADSHEET_MAX_COLUMNS
    )
    store = storage if storage is not None else get_storage(settings)
    key = new_key(bot_id, kind)
    try:
        await store.put(key, data)
    except OSError:
        log.exception("bot %s: could not write an upload to file storage", bot_id)
        raise StorageUnavailable() from None
    row = UploadedFileRow(
        id=uuid.uuid4(),
        bot_id=bot_id,
        filename=name or f"spreadsheet.{kind}",
        content_type=CONTENT_TYPES[kind],
        size=len(data),
        sha256=digest,
        storage_key=key,
        source=source,
        uploaded_by=uploaded_by,
        inspection=inspection.model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    try:
        await session.flush()
    except Exception:
        await _discard(store, key)
        raise
    log.info("bot %s: stored %s upload %s (%d bytes, %s)", bot_id, kind, row.id, len(data), source)
    return _upload_out(row, inspection)


def _stored_inspection(raw: object, upload_id: uuid.UUID) -> WorkbookInspection:
    try:
        return WorkbookInspection.model_validate(raw)
    except ValidationError:
        log.warning("upload %s: stored inspection is not valid; serving an empty one", upload_id)
        return WorkbookInspection(sheets=[], signature="", row_limit_hit=False)


def _upload_out(row: UploadedFileRow, inspection: WorkbookInspection) -> UploadOut:
    return UploadOut(
        id=row.id,
        filename=row.filename,
        size=row.size,
        content_type=row.content_type,
        sha256=row.sha256,
        created_at=row.created_at,
        inspection=inspection,
    )


def to_upload_out(row: UploadedFileRow) -> UploadOut:
    return _upload_out(row, _stored_inspection(row.inspection, row.id))


async def list_uploads(
    session: AsyncSession, bot_id: uuid.UUID, *, limit: int = LIST_LIMIT
) -> list[UploadOut]:
    """The bot's latest uploads, newest first."""
    stmt = (
        select(UploadedFileRow)
        .where(UploadedFileRow.bot_id == bot_id)
        .order_by(UploadedFileRow.created_at.desc(), UploadedFileRow.id.desc())
        .limit(limit)
    )
    return [to_upload_out(row) for row in (await session.execute(stmt)).scalars()]


async def get_upload(
    session: AsyncSession, bot_id: uuid.UUID, upload_id: uuid.UUID
) -> UploadedFileRow | None:
    """Upload ``upload_id`` if it belongs to ``bot_id`` (the caller has checked the bot's owner)."""
    stmt = select(UploadedFileRow).where(UploadedFileRow.id == upload_id, UploadedFileRow.bot_id == bot_id)
    return (await session.execute(stmt)).scalar_one_or_none()


def _load(
    data: bytes, kind: FileKind, sheet: str | None, max_rows: int, max_cols: int
) -> tuple[list[str], list[list[Cell]]]:
    headers, rows = iter_rows(data, kind, sheet, max_rows=max_rows, max_cols=max_cols)
    try:
        return headers, list(rows)
    finally:
        rows.close()


async def load_rows(
    storage: FileStorage,
    row: UploadedFileRow,
    *,
    sheet: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cols: int = DEFAULT_MAX_COLUMNS,
) -> tuple[list[str], list[list[Cell]]]:
    """(headers, rows) of a stored upload's sheet ``sheet`` (its name in the inspection; default the
    first), normalised exactly as the inspection saw them. Pass the same limits the upload was
    inspected with (``SPREADSHEET_MAX_ROWS``/``SPREADSHEET_MAX_COLUMNS``). ``StoredFileMissing`` if
    the bytes are gone; ``EmptyWorkbook`` if the sheet does not exist."""
    kind = key_kind(row.storage_key)
    try:
        data = await storage.get(row.storage_key)
    except FileNotFoundError:
        raise StoredFileMissing() from None
    return await run_parser(_load, data, kind, sheet, max_rows, max_cols)


def _load_and_compute[T](
    data: bytes,
    kind: FileKind,
    sheet: str | None,
    max_rows: int,
    max_cols: int,
    compute: Callable[[list[str], list[list[Cell]]], T],
) -> T:
    headers, rows = _load(data, kind, sheet, max_rows, max_cols)
    return compute(headers, rows)


async def compute_on_rows[T](
    storage: FileStorage,
    row: UploadedFileRow,
    compute: Callable[[list[str], list[list[Cell]]], T],
    *,
    sheet: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cols: int = DEFAULT_MAX_COLUMNS,
) -> T:
    """``compute(headers, rows)`` over the sheet ``load_rows`` would return, in ONE job on the parser
    thread (same arguments and errors as ``load_rows``). SECURITY: an analysis run over a large sheet is
    seconds of CPU; here it never blocks the event loop (which serves every bot's webhook), and the
    loaded rows exist only inside the running job, so concurrent runs queue with just their file bytes
    instead of each holding a parsed sheet."""
    kind = key_kind(row.storage_key)
    try:
        data = await storage.get(row.storage_key)
    except FileNotFoundError:
        raise StoredFileMissing() from None
    return await run_parser(_load_and_compute, data, kind, sheet, max_rows, max_cols, compute)
