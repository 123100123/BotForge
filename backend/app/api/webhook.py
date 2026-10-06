"""The shared Telegram webhook: ``POST /tg/{bot_id}`` (public; authenticated by the secret header).

Order of checks: unknown bot -> 404; secret mismatch -> 403 (``verify_webhook_secret``, constant
time); body over 1 MiB -> 413. After that the answer is ALWAYS 200: Telegram retries anything else,
and a poison update must not be replayed forever. Internal errors are logged with the bot id and
update id only (never the update content, which holds user messages) and the transaction is rolled
back.

Processing: record ``(bot_id, update_id)`` in ``tg_updates`` and commit at once (a duplicate delivery
stops here); ``my_chat_member`` (the bot was added to, promoted in, restricted in or removed from a
group, supergroup or channel) upserts ``bot_chats`` and stops (``_record_chat_member``); a document
in a private chat goes to ``_receive_document`` and stops; owner deep link ``/start owner_<code>``
(single use, and only while no owner is linked); staff deep link ``/start staff_<code>`` in a
private chat (multi-use; ``_join_staff``): on the bot's current code the sender becomes staff, is
told so and then gets the normal start, on any other code one generic reply and nothing else; the
fixed "not ready" reply when the bot has no active revision (for a button press in a group: only
the toast, nothing is posted to the group); otherwise ``dispatch``. Owner linking, joining as
staff, group membership and documents are handled before the active-revision check because none
needs a revision.

Documents (SECURITY): only a staff member or manager (the owner is one) may send a file, and only
while the bot's ``spreadsheet_intelligence`` module is on. Everyone else gets one fixed line and
nothing is downloaded; the role and the owner link are read fresh from the database (the role is
never taken from the update). The download itself, its size cap and the ingestion are
``app.spreadsheets.telegram_ingest.handle_document``.

Everything after the HTTP checks is ``process_update``, which the poller (``TELEGRAM_MODE=polling``,
``app.integrations.telegram.poller``) calls for every update it fetches, so both modes share one
path. It stays in this module so the webhook tests' patches of its names cover both.
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

from app.capabilities.registry import get_capability
from app.capabilities.service import load_module_rows, module_enabled
from app.config import get_settings
from app.db.models import Bot, BotChatRow, TgUpdate
from app.db.session import get_session
from app.integrations.telegram import texts
from app.integrations.telegram.adapter import ParsedUpdate, parse_update
from app.integrations.telegram.client import TelegramProvider, get_telegram_provider
from app.integrations.telegram.onboarding import armed_owner_code
from app.roles import TEAM_ROLES
from app.roles.service import (
    STAFF_JOINED,
    STAFF_LINK_INVALID,
    get_role,
    redeem_staff_code,
    staff_code_from_payload,
)
from app.runtime.pg_store import advisory_lock
from app.security.crypto import verify_webhook_secret
from app.services.dispatch import answer_callback, client_for_bot, dispatch, reply_plain
from app.services.specs import load_active_spec
from app.spreadsheets.reader import INVISIBLE_CHARS
from app.spreadsheets.telegram_ingest import handle_document

log = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])

MAX_BODY_BYTES = 1024 * 1024
OWNER_PAYLOAD_PREFIX = "owner_"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Groups (my_chat_member): the chats bot_chats records, and the bot statuses that make one usable.
CHAT_KINDS = frozenset({"group", "supergroup", "channel"})
ACTIVE_MEMBER_STATUSES = frozenset({"member", "administrator"})
MAX_CHAT_TITLE_CHARS = 255  # Telegram allows 128

# Documents: who may send them is decided here; the replies to everyone else.
SPREADSHEET_MODULE = "spreadsheet_intelligence"
DOCUMENT_NOT_ALLOWED = "ارسال فایل برای شما فعال نیست"
DOCUMENT_MODULE_OFF = "قابلیت تحلیل فایل فعال نیست"


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

    update = _decode(body)
    if update is not None:
        await process_update(session, bot, update, telegram)
    return {"ok": True}


async def process_update(
    session: AsyncSession, bot: Bot, update: dict[str, Any], telegram: TelegramProvider
) -> None:
    """Handle one authenticated, parsed Telegram update for ``bot``: dedupe, conversion, the owner
    link, the "not ready" reply, dispatch and delivery. The one path for both ways updates arrive:
    the webhook above (after its secret and body-size checks) and the poller (polling mode, after
    getUpdates with the bot's own token).

    Never raises an ``Exception``: a failure is logged with the bot id and update id only (never the
    content) and the transaction rolled back, so a poison update is dropped instead of replayed.
    Cancellation (``BaseException``) propagates.
    """
    bot_id = bot.id  # read before anything can expire the ORM object
    update_id = update.get("update_id")
    try:
        await _process(session, bot, update, telegram)
    except Exception:
        log.exception("telegram update processing failed (bot %s, update %s)", bot_id, update_id)
        try:
            await session.rollback()
        except Exception:
            log.exception("rollback failed (bot %s)", bot_id)


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

    if "my_chat_member" in update:
        await _record_chat_member(session, bot, update["my_chat_member"])
        return

    parsed = parse_update(str(bot.id), update, owner_actor_id=bot.owner_actor_id, now=datetime.now(UTC))
    if parsed is None:
        return

    if parsed.document is not None:
        await _receive_document(session, bot, parsed, telegram)
        return

    if parsed.start_payload is not None and parsed.start_payload.startswith(OWNER_PAYLOAD_PREFIX):
        await _link_owner(session, bot, parsed, telegram)
        return
    staff_code = staff_code_from_payload(parsed.start_payload)
    if (
        staff_code is not None
        and parsed.event.chat_type == "private"
        and not await _join_staff(session, bot, parsed, staff_code, telegram)
    ):
        return  # not joined: the generic reply was the whole answer
    # (joined: the normal start follows, welcome and the menu, now with the staff items)

    active = await load_active_spec(session, bot)
    if active is None:
        if parsed.event.chat_type == "group":  # nothing is ever posted to a group from here
            await answer_callback(session, bot, parsed.origin, texts.NOT_READY, telegram=telegram)
            return
        await reply_plain(
            session, bot, parsed.origin.chat_id, texts.NOT_READY, telegram=telegram, origin=parsed.origin
        )
        return
    _, spec = active
    await dispatch(session, bot, spec, parsed.event, telegram=telegram, origin=parsed.origin)


def _chat_title(raw: Any, chat_id: int) -> str:
    """A group's title as a display label (shown only in the owner's web app): control characters
    become spaces, invisible marks and bidi overrides are removed (``reader.INVISIBLE_CHARS``, the
    rule for every label; ZWNJ stays), whitespace is collapsed, the length capped; the chat id when
    nothing is left."""
    title = raw if isinstance(raw, str) else ""
    return " ".join(title.translate(INVISIBLE_CHARS).split())[:MAX_CHAT_TITLE_CHARS] or str(chat_id)


async def _record_chat_member(session: AsyncSession, bot: Bot, member: Any) -> None:
    """``my_chat_member``: this bot's own membership of a group, supergroup or channel changed.

    Upserts the chat into ``bot_chats``: active while the bot is a member or an administrator,
    inactive once it is restricted, has left or was removed. Private chats (a user blocking the bot),
    malformed updates and an update about another account than this bot change nothing. The update
    is authenticated (webhook secret, or polled with the bot's own token); the title is user content
    and is stored only as a label."""
    if not isinstance(member, dict):
        return
    chat, new = member.get("chat"), member.get("new_chat_member")
    if not isinstance(chat, dict) or not isinstance(new, dict):
        return
    kind, chat_id, status = chat.get("type"), chat.get("id"), new.get("status")
    if kind not in CHAT_KINDS or type(chat_id) is not int or not isinstance(status, str):
        return
    subject = new.get("user")
    subject_id = subject.get("id") if isinstance(subject, dict) else None
    if bot.tg_bot_id is not None and subject_id != bot.tg_bot_id:
        return
    active = status in ACTIVE_MEMBER_STATUSES
    title = _chat_title(chat.get("title"), chat_id)
    stmt = pg_insert(BotChatRow).values(bot_id=bot.id, chat_id=chat_id, title=title, kind=kind, active=active)
    stmt = stmt.on_conflict_do_update(
        index_elements=[BotChatRow.bot_id, BotChatRow.chat_id],
        set_={"title": stmt.excluded.title, "kind": stmt.excluded.kind, "active": stmt.excluded.active},
    )
    await session.execute(stmt)
    await session.commit()
    log.info("bot %s: %s %s recorded as %s", bot.id, kind, chat_id, "active" if active else "inactive")


async def _spreadsheets_enabled(session: AsyncSession, bot: Bot) -> bool:
    """Whether the bot's ``spreadsheet_intelligence`` module is on (``bot_modules``, else the registry
    default), exactly as the Capability Center reports it."""
    cap = get_capability(SPREADSHEET_MODULE)
    return cap is not None and module_enabled(cap, await load_module_rows(session, bot))


async def _receive_document(
    session: AsyncSession, bot: Bot, parsed: ParsedUpdate, telegram: TelegramProvider
) -> None:
    """A document in a private chat (module docstring, "Documents"): one reply in every case.

    The owner link and the sender's stored role are read fresh (the role in the event is never
    trusted); a customer is refused before the module state is even looked at, so the reply says
    nothing about the bot's configuration. The read transaction ends before the download, which
    takes no lock and may take up to a minute."""
    document = parsed.document
    if document is None:  # pragma: no cover - the caller checked
        return
    actor_id = parsed.event.actor.id
    bot_id = bot.id
    fresh = await session.get(Bot, bot_id, populate_existing=True) or bot
    is_owner = fresh.owner_actor_id is not None and actor_id == fresh.owner_actor_id
    role = "manager" if is_owner else await get_role(session, bot_id, "live", actor_id)
    if role not in TEAM_ROLES:
        text = DOCUMENT_NOT_ALLOWED
    elif not await _spreadsheets_enabled(session, fresh):
        text = DOCUMENT_MODULE_OFF
    else:
        client = client_for_bot(fresh, telegram)
        if client is None:  # no usable token: nothing can be downloaded, nor answered (logged)
            return
        await session.commit()  # ends the read transaction before the network transfer
        text = await handle_document(session, fresh, actor_id, document, client, get_settings())
        current = await session.get(Bot, bot_id, populate_existing=True)  # a rollback expires objects
        if current is None:
            return
        fresh = current
    await reply_plain(session, fresh, parsed.origin.chat_id, text, telegram=telegram, origin=parsed.origin)


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


async def _join_staff(
    session: AsyncSession, bot: Bot, parsed: ParsedUpdate, code: str, telegram: TelegramProvider
) -> bool:
    """``/start staff_<code>``: make the sender staff of the live bot when ``code`` is its current
    staff code (``roles.service.redeem_staff_code``: checked in constant time under the bot's lock,
    idempotent, a manager stays a manager) and confirm it; True when joined.

    Any other code (wrong, rotated, revoked, empty) changes nothing and gets one generic reply,
    whatever the reason. The code is never logged or echoed. The role is committed before any
    reply, so the start that follows (``dispatch``, which reads the role under the same lock)
    already shows the staff menu.
    """
    actor = parsed.event.actor
    joined = await redeem_staff_code(session, bot, actor.id, code, display_name=actor.display_name)
    await session.commit()  # also releases the lock
    text = STAFF_JOINED if joined else STAFF_LINK_INVALID
    await reply_plain(session, bot, parsed.origin.chat_id, text, telegram=telegram, origin=parsed.origin)
    return joined


def _same_code(given: str, expected: str) -> bool:
    """Constant-time comparison. A payload that cannot be encoded (a lone surrogate) never matches."""
    try:
        return secrets.compare_digest(given.encode(), expected.encode())
    except UnicodeError:
        return False
