"""Spreadsheet uploads: ``PUT /uploads/bots/{bot_id}?filename=`` (raw body), ``GET /bots/{bot_id}/uploads``
and ``GET /bots/{bot_id}/uploads/{upload_id}``.

The upload body is the file itself, not multipart (``python-multipart`` is not in the production image).
SECURITY, in order:

1. ``get_owned_bot`` resolves first: session cookie (401), the CSRF check for this PUT (403), the
   session (401), the bot's owner (404, the body of a missing bot). Nothing of the body is read before
   that, so an anonymous or cross-site caller cannot make the server buffer anything.
2. ``app.security.body_limit`` exempts ``/uploads/`` from the global 1 MiB cap because this route
   enforces its own: a declared ``Content-Length`` over ``UPLOAD_MAX_BYTES`` is refused unread, and the
   streamed body is cut off at ``UPLOAD_MAX_BYTES + 1`` bytes (413 ``upload_too_large``).
3. At most ``MAX_UPLOADS_IN_FLIGHT`` uploads are received or processed at once in this process (503
   ``uploads_busy`` beyond that), and receiving one may take at most ``UPLOAD_READ_TIMEOUT_SECONDS``
   (408), so slow or parallel senders cannot hold unbounded memory.
4. The ``Content-Type`` header and the file name are advisory: the service decides the type from the
   bytes, stores the file under a server-generated key, and keeps the name only as a sanitised label.

Errors use the standard envelope with Persian messages (``app.spreadsheets.errors``).
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.deps import CurrentUser, get_current_user, get_owned_bot
from app.config import get_settings
from app.db.models import Bot
from app.db.session import get_session
from app.schemas.business import UploadOut
from app.spreadsheets import service
from app.spreadsheets.errors import FileTooLarge, SpreadsheetError, UploadsBusy, too_large_message

log = logging.getLogger(__name__)

router = APIRouter(tags=["uploads"])

MAX_UPLOADS_IN_FLIGHT = 4
UPLOAD_READ_TIMEOUT_SECONDS = 120
MAX_FILENAME_PARAM = 1024
UPLOAD_NOT_FOUND = {"code": "upload_not_found", "message": "فایل پیدا نشد."}
UPLOAD_TIMEOUT = {"code": "upload_timeout", "message": "ارسال فایل بیش از حد طول کشید. دوباره تلاش کنید."}
UPLOAD_INCOMPLETE = {"code": "upload_incomplete", "message": "ارسال فایل کامل نشد. دوباره تلاش کنید."}


class _InFlight:
    """Process-wide count of uploads being received or processed. Only touched on the event loop
    thread, so a plain counter is enough."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.count = 0

    def __enter__(self) -> None:
        if self.count >= self.limit:
            raise UploadsBusy()
        self.count += 1

    def __exit__(self, *exc_info: object) -> None:
        self.count -= 1


IN_FLIGHT = _InFlight(MAX_UPLOADS_IN_FLIGHT)


def _http_error(exc: SpreadsheetError) -> HTTPException:
    headers = {"Retry-After": "5"} if isinstance(exc, UploadsBusy) else None
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message_fa}, headers=headers)


async def _read_body(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > max_bytes:
        raise FileTooLarge(too_large_message(max_bytes))
    chunks: list[bytes] = []
    total = 0
    try:
        async with asyncio.timeout(UPLOAD_READ_TIMEOUT_SECONDS):
            async for chunk in request.stream():
                total += len(chunk)
                if total > max_bytes:
                    raise FileTooLarge(too_large_message(max_bytes))
                chunks.append(chunk)
    except TimeoutError:
        raise HTTPException(408, detail=UPLOAD_TIMEOUT) from None
    except ClientDisconnect:
        raise HTTPException(400, detail=UPLOAD_INCOMPLETE) from None
    return b"".join(chunks)


@router.put("/uploads/bots/{bot_id}", response_model=UploadOut, status_code=201)
async def upload_spreadsheet(
    request: Request,
    bot: Bot = Depends(get_owned_bot),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    filename: str = Query("", max_length=MAX_FILENAME_PARAM),
) -> UploadOut:
    """Upload one xlsx or csv file as the raw request body; the file name travels in ``filename``."""
    settings = get_settings()
    try:
        with IN_FLIGHT:
            data = await _read_body(request, settings.UPLOAD_MAX_BYTES)
            upload = await service.ingest(
                session, bot, data, filename, source="web", uploaded_by=str(user.id), settings=settings
            )
    except SpreadsheetError as exc:
        log.info("bot %s: upload refused (%s)", bot.id, exc.code)  # never the file name or content
        raise _http_error(exc) from None
    await session.commit()
    return upload


@router.get("/bots/{bot_id}/uploads", response_model=list[UploadOut])
async def list_uploads(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> list[UploadOut]:
    """The bot's latest uploads (at most fifty), newest first."""
    return await service.list_uploads(session, bot.id)


@router.get("/bots/{bot_id}/uploads/{upload_id}", response_model=UploadOut)
async def read_upload(
    upload_id: uuid.UUID, bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> UploadOut:
    """One upload of the bot; another bot's upload is a 404 like a missing one."""
    row = await service.get_upload(session, bot.id, upload_id)
    if row is None:
        raise HTTPException(404, detail=UPLOAD_NOT_FOUND)
    return service.to_upload_out(row)
