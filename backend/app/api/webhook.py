"""The shared Telegram webhook: ``POST /tg/{bot_id}`` (public; authenticated by the secret header).

Order of checks: unknown bot -> 404; secret mismatch -> 403 (``verify_webhook_secret``, constant
time); body over 1 MiB -> 413. After that the answer is ALWAYS 200: Telegram retries anything else,
and a poison update must not be replayed forever. Internal errors are logged with the bot id and
update id only (never the update content, which holds user messages) and the transaction is rolled
back.

Processing: record ``(bot_id, update_id)`` in ``tg_updates`` and commit at once (a duplicate delivery
stops here); owner deep link ``/start owner_<code>`` (single use, and only while no owner is
linked); the fixed "not ready" reply when the bot has no active revision; otherwise ``dispatch``.
Owner linking is handled before the active-revision check because linking needs no revision.
"""

import json
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, TgUpdate
from app.db.session import get_session
from app.integrations.telegram import texts
from app.integrations.telegram.adapter import ParsedUpdate, parse_update
from app.integrations.telegram.client import TelegramProvider, get_telegram_provider
from app.integrations.telegram.onboarding import armed_owner_code
from app.runtime.pg_store import advisory_lock
from app.security.crypto import verify_webhook_secret
from app.services.dispatch import dispatch, reply_plain
from app.services.specs import load_active_spec

log = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])

MAX_BODY_BYTES = 1024 * 1024
OWNER_PAYLOAD_PREFIX = "owner_"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _error(413, "body_too_large", "حجم درخواست بیش از حد مجاز است.")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise _error(413, "body_too_large", "حجم درخواست بیش از حد مجاز است.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/tg/{bot_id}")
async def telegram_webhook(
    bot_id: str,
    request: Request,
    secret: str | None = Header(None, alias=SECRET_HEADER),
    session: AsyncSession = Depends(get_session),
    telegram: TelegramProvider = Depends(get_telegram_provider),
) -> dict[str, bool]:
    try:
        bot_uuid = uuid.UUID(bot_id)
    except ValueError:
        raise _error(404, "bot_not_found", "ربات پیدا نشد.") from None
    bot = await session.get(Bot, bot_uuid)
    if bot is None:
        raise _error(404, "bot_not_found", "ربات پیدا نشد.")
    if not verify_webhook_secret(bot.tg_webhook_secret, secret):
        raise _error(403, "forbidden", "دسترسی مجاز نیست.")
    body = await _read_body(request)

    update_id: Any = None
    try:
        update = _decode(body)
        update_id = update.get("update_id") if update is not None else None
        if update is not None:
            await _process(session, bot, update, telegram)
    except Exception:
        log.exception("webhook processing failed (bot %s, update %s)", bot_uuid, update_id)
        try:
            await session.rollback()
        except Exception:
            log.exception("rollback failed (bot %s)", bot_uuid)
    return {"ok": True}


def _decode(body: bytes) -> dict[str, Any] | None:
    try:
        update = json.loads(body)
    except ValueError:
        return None
    return update if isinstance(update, dict) else None


async def _process(
    session: AsyncSession, bot: Bot, update: dict[str, Any], telegram: TelegramProvider
) -> None:
    update_id = update.get("update_id")
    if not isinstance(update_id, int) or isinstance(update_id, bool):
        return
    inserted = await session.execute(
        pg_insert(TgUpdate)
        .values(bot_id=bot.id, update_id=update_id)
        .on_conflict_do_nothing()
        .returning(TgUpdate.update_id)
    )
    is_new = inserted.first() is not None
    await session.commit()  # the dedupe record is durable before any work happens
    if not is_new:
        return

    parsed = parse_update(str(bot.id), update, owner_actor_id=bot.owner_actor_id, now=datetime.now(UTC))
    if parsed is None:
        return

    if parsed.start_payload is not None and parsed.start_payload.startswith(OWNER_PAYLOAD_PREFIX):
        await _link_owner(session, bot, parsed, telegram)
        return

    active = await load_active_spec(session, bot)
    if active is None:
        await reply_plain(
            session, bot, parsed.origin.chat_id, texts.NOT_READY, telegram=telegram, origin=parsed.origin
        )
        return
    _, spec = active
    await dispatch(session, bot, spec, parsed.event, telegram=telegram, origin=parsed.origin)


async def _link_owner(
    session: AsyncSession, bot: Bot, parsed: ParsedUpdate, telegram: TelegramProvider
) -> None:
    """``/start owner_<code>``: record the sender as the bot owner and consume the code.

    Single use, and nothing is re-armed here: a rotated code would sit valid in the Settings page
    (and in any screenshot or screen share of it), letting whoever copies it silently replace the
    owner. A code is accepted only while no owner is linked (``armed_owner_code``), so it can
    establish an owner but never replace one. A new code exists only after the authenticated owner
    reconnects the token (``connect`` unlinks the owner and arms a fresh code), so every change of
    owner follows an action in the web app.

    The code is checked under the bot's lock against the row read under it, and the write is a
    compare-and-set on that same code: ``connect`` and ``disconnect`` rewrite the owner columns
    without the lock, and a code they revoked after the read must not link anyone.
    """
    code = (parsed.start_payload or "")[len(OWNER_PAYLOAD_PREFIX) :]
    await advisory_lock(session, bot.id)
    fresh = await session.get(Bot, bot.id, populate_existing=True) or bot
    expected = armed_owner_code(fresh)
    linked = False
    if expected is not None and _same_code(code, expected):
        consumed = await session.execute(
            update(Bot)
            .where(Bot.id == fresh.id, Bot.owner_actor_id.is_(None), Bot.owner_link_code == expected)
            .values(owner_actor_id=parsed.event.actor.id, owner_link_code=None)  # consumed: single use
            .returning(Bot.id)
            .execution_options(synchronize_session=False)
        )
        linked = consumed.first() is not None
    await session.commit()  # also releases the lock
    text = texts.OWNER_LINKED if linked else texts.OWNER_LINK_INVALID
    await reply_plain(session, fresh, parsed.origin.chat_id, text, telegram=telegram, origin=parsed.origin)


def _same_code(given: str, expected: str) -> bool:
    """Constant-time comparison. A payload that cannot be encoded (a lone surrogate) never matches."""
    try:
        return secrets.compare_digest(given.encode(), expected.encode())
    except UnicodeError:
        return False
