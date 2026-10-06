"""Telegram documents into the spreadsheet service (Business OS, Telegram groups & documents).

``handle_document`` is the Telegram counterpart of the web upload (``PUT /uploads/bots/{bot_id}``):
``app.api.webhook`` calls it only for a staff member or manager of a bot whose
``spreadsheet_intelligence`` module is on, and it returns the one Persian reply for the sender.

Order and limits:

1. a declared ``file_size`` over ``UPLOAD_MAX_BYTES`` is refused before anything is downloaded;
2. at most ``app.api.uploads.MAX_UPLOADS_IN_FLIGHT`` files are received or processed at once in this
   process, counted together with web uploads (the one process-wide ``IN_FLIGHT`` counter);
3. ``getFile``, then the download through the Telegram client, cut off past ``UPLOAD_MAX_BYTES``
   while streaming, with a wall-clock timeout (``client.download_file``);
4. ``spreadsheets.service.ingest`` with source ``telegram`` and the sender's Telegram id as
   ``uploaded_by``: the type is decided from the bytes, the file stored under a server-generated key;
   committed, so the file is kept whatever the analysis does;
5. when the analysis runner exists (``app.spreadsheets.run.run_for_upload``, built by W2-PROF) it is
   run with no LLM client (live Telegram traffic makes no LLM calls): the reply summarises the scalar
   metrics and the anomaly count of a matching profile, or lists the missing columns of a changed
   layout. Without a runner, or when no profile matches (``None``), the reply acknowledges the file.

Errors: a ``SpreadsheetError`` answers with its Persian ``message_fa``; a failed download with one
generic line. Nothing logged here contains the file name, its content or the token: bot ids, upload
ids, error codes and Telegram method names only.
"""

import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.uploads import IN_FLIGHT
from app.config import Settings
from app.db.models import Bot
from app.integrations.telegram.adapter import TelegramDocument
from app.integrations.telegram.client import TelegramApi, TelegramError, TelegramFileTooLarge
from app.runtime.formatting import format_decimal, format_int
from app.schemas.business import AnalysisRunOut, UploadOut
from app.spreadsheets.errors import SpreadsheetError, too_large_message
from app.spreadsheets.service import get_upload, ingest

log = logging.getLogger(__name__)

RUN_MODULE = "app.spreadsheets.run"

RECEIVED = "فایل دریافت و ذخیره شد ✅"
DOWNLOAD_FAILED = "دریافت فایل از تلگرام ممکن نشد. لطفاً دوباره بفرستید."
ANALYSIS_FAILED = "تحلیل خودکار این فایل انجام نشد؛ نتیجه را در پنل وب ببینید."
ANALYSED = "فایل «{name}» تحلیل شد ✅"
NO_METRICS = "برای این فایل شاخص عددی تعریف نشده است."
ANOMALIES = "موارد غیرعادی: {count}"
SCHEMA_CHANGED = "ساختار فایل «{name}» با الگوی قبلی فرق دارد و تحلیل نشد."
MISSING_COLUMNS = "ستون‌های جاافتاده: {columns}"
NEW_COLUMNS = "ستون‌های جدید: {columns}"
MORE_COLUMNS = " و {count} ستون دیگر"
MAX_SUMMARY_METRICS = 4  # header + up to 4 metrics + anomalies: at most six lines
MAX_LISTED_COLUMNS = 10
MAX_LABEL_CHARS = 40

Runner = Callable[..., Awaitable[Any]]


async def handle_document(
    session: AsyncSession,
    bot: Bot,
    actor_id: str,
    document: TelegramDocument,
    telegram: TelegramApi,
    settings: Settings,
) -> str:
    """Download, store and (when possible) analyse ``document`` sent by ``actor_id``; the Persian reply.

    The caller has authorised the sender (staff or manager, module on). Commits the upload. Raises
    only what the database raises (the webhook logs it without content and rolls back)."""
    bot_id = bot.id  # read before a commit or rollback can expire the ORM object
    max_bytes = settings.UPLOAD_MAX_BYTES
    if document.file_size is not None and document.file_size > max_bytes:
        return too_large_message(max_bytes)
    try:
        with IN_FLIGHT:
            try:
                file_path = await telegram.get_file(document.file_id)
                data = await telegram.download_file(file_path, max_bytes)
            except TelegramFileTooLarge:
                return too_large_message(max_bytes)
            except TelegramError as exc:
                log.warning("bot %s: Telegram document download failed (%s)", bot_id, exc.method)
                return DOWNLOAD_FAILED
            upload = await ingest(
                session,
                bot,
                data,
                document.file_name or "",
                source="telegram",
                uploaded_by=actor_id,
                settings=settings,
            )
            await session.commit()  # the file is kept whatever the analysis does
            return await _analyse(session, bot, bot_id, upload, actor_id)
    except SpreadsheetError as exc:
        log.info("bot %s: Telegram document refused (%s)", bot_id, exc.code)  # never the name or content
        return exc.message_fa


def _runner() -> Runner | None:
    """``run_for_upload`` of the analysis package, or ``None`` while it does not exist."""
    try:
        from app.spreadsheets.run import run_for_upload  # type: ignore[import-not-found,unused-ignore]
    except ImportError as exc:
        if exc.name != RUN_MODULE:  # the module exists but is broken: worth a line in the log
            log.warning("%s could not be imported (%s: %s)", RUN_MODULE, type(exc).__name__, exc.name)
        return None
    return run_for_upload  # type: ignore[no-any-return,unused-ignore]


async def _analyse(
    session: AsyncSession, bot: Bot, bot_id: uuid.UUID, upload: UploadOut, actor_id: str
) -> str:
    runner = _runner()
    if runner is None:
        return RECEIVED
    row = await get_upload(session, bot_id, upload.id)
    if row is None:  # pragma: no cover - committed just above
        return RECEIVED
    try:
        result = await runner(session, bot, row, submitted_by=actor_id)
        await session.commit()
    except SpreadsheetError as exc:
        await session.rollback()
        log.info("bot %s: analysis of upload %s refused (%s)", bot_id, upload.id, exc.code)
        return f"{RECEIVED}\n{exc.message_fa}"
    except Exception:
        log.exception("bot %s: analysis of upload %s failed", bot_id, upload.id)
        await session.rollback()
        return f"{RECEIVED}\n{ANALYSIS_FAILED}"
    return run_reply(result, upload.filename)


def _short(text: str, limit: int = MAX_LABEL_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _columns(names: list[str]) -> str:
    shown = "، ".join(_short(n) for n in names[:MAX_LISTED_COLUMNS])
    rest = len(names) - MAX_LISTED_COLUMNS
    return shown + (MORE_COLUMNS.format(count=format_int(rest)) if rest > 0 else "")


def run_reply(result: object, filename: str) -> str:
    """The Persian reply for a run result: ``None`` (no matching profile) acknowledges the file;
    ``ok`` summarises scalar metrics and the anomaly count (three to six lines); ``schema_changed``
    lists the missing (and new) columns; anything else acknowledges the file and says the analysis
    did not run."""
    if result is None:
        return RECEIVED
    try:
        run = AnalysisRunOut.model_validate(result)
    except ValidationError:
        log.warning("the analysis runner returned an unexpected result")
        return RECEIVED
    name = _short(run.filename or filename)
    if run.status == "schema_changed":
        lines = [SCHEMA_CHANGED.format(name=name)]
        if run.schema_diff is not None and run.schema_diff.missing:
            lines.append(MISSING_COLUMNS.format(columns=_columns(run.schema_diff.missing)))
        if run.schema_diff is not None and run.schema_diff.new:
            lines.append(NEW_COLUMNS.format(columns=_columns(run.schema_diff.new)))
        return "\n".join(lines)
    if run.status != "ok":
        return f"{RECEIVED}\n{ANALYSIS_FAILED}"
    lines = [ANALYSED.format(name=name)]
    scalars = [
        m for m in run.metrics if m.kind == "scalar" and m.value is not None and math.isfinite(m.value)
    ]
    for metric in scalars[:MAX_SUMMARY_METRICS]:
        unit = f" {_short(metric.unit, 12)}" if metric.unit else ""
        lines.append(f"• {_short(metric.label)}: {format_decimal(metric.value or 0.0, 2)}{unit}")
    if not scalars:
        lines.append(NO_METRICS)
    lines.append(ANOMALIES.format(count=format_int(len(run.anomalies))))
    return "\n".join(lines)
