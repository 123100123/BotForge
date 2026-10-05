"""Authentication and ownership dependencies (roadmap: Security, Backend API).

``get_current_user`` authenticates the ``bf_session`` cookie against ``auth_sessions`` (see
``app/security/sessions.py``) and, for a state-changing method, applies the CSRF check
(``app/security/csrf.py``) before touching the database. Order and answers:

1. no session cookie: 401 ``auth_required``;
2. a method other than GET/HEAD/OPTIONS without ``X-BotForge-CSRF: 1`` or with a foreign ``Origin``:
   403 ``csrf_failed``;
3. a cookie that names no live session (unknown, malformed, expired, logged out): 401
   ``invalid_session``.

There is no other way in: no bearer tokens, no anonymous sessions.

``get_owned_bot``, ``get_owned_run`` and ``get_owned_revision`` load an entity only when its bot
belongs to the caller; anything else is a 404 with exactly the body of a missing entity, so ids of
other owners' objects cannot be probed.

Path parameter names matter: routes using these dependencies must name their placeholders
``{bot_id}``, ``{run_id}`` and ``{revision_id}``. Every dependency shares the request's single
``get_session`` (default dependency scope), so the returned objects belong to the endpoint's session.
"""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, Bot, Revision
from app.db.session import get_session
from app.security.accounts import CurrentUser
from app.security.csrf import SAFE_METHODS, csrf_ok
from app.security.sessions import SESSION_COOKIE, request_refresh, resolve_session

__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_owned_bot",
    "get_owned_revision",
    "get_owned_run",
]

AUTH_REQUIRED = ("auth_required", "برای ادامه وارد حساب کاربری خود شوید.")
INVALID_SESSION = ("invalid_session", "نشست شما نامعتبر است یا به پایان رسیده است. لطفاً دوباره وارد شوید.")
CSRF_FAILED = ("csrf_failed", "درخواست تأیید نشد. صفحه را دوباره بارگذاری کنید و دوباره تلاش کنید.")
BOT_NOT_FOUND = ("bot_not_found", "ربات پیدا نشد.")
RUN_NOT_FOUND = ("run_not_found", "اجرای ایجنت پیدا نشد.")
REVISION_NOT_FOUND = ("revision_not_found", "نسخه پیدا نشد.")


def http_error(status: int, error: tuple[str, str]) -> HTTPException:
    code, message = error
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def require_csrf(request: Request) -> None:
    """403 ``csrf_failed`` unless the request passes the CSRF check."""
    if not csrf_ok(request):
        raise http_error(403, CSRF_FAILED)


async def session_token(request: Request) -> str:
    """The session cookie of a request that passes the CSRF check (steps 1 and 2). Declared before
    ``get_session`` in ``get_current_user``, so these refusals come before any database work."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise http_error(401, AUTH_REQUIRED)
    if request.method not in SAFE_METHODS:
        require_csrf(request)
    return token


async def get_current_user(
    request: Request,
    token: str = Depends(session_token),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    """The signed-in caller (see the module docstring for the checks and their order)."""
    resolved = await resolve_session(session, token)
    user = None if resolved.user is None else CurrentUser(id=resolved.user.id, email=resolved.user.email)
    if resolved.wrote:
        await session.commit()  # a renewal or the purge of an expired session, whatever comes next
    if user is None:
        raise http_error(401, INVALID_SESSION)
    if resolved.renewed:
        request_refresh(request, token)
    return user


async def get_owned_bot(
    bot_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Bot:
    """The caller's bot ``bot_id``. Another owner's bot is a 404 identical to a missing one."""
    stmt = select(Bot).where(Bot.id == bot_id, Bot.owner_id == user.id)
    bot = (await session.execute(stmt)).scalar_one_or_none()
    if bot is None:
        raise http_error(404, BOT_NOT_FOUND)
    return bot


async def get_owned_run(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentRun:
    """Agent run ``run_id`` if its bot belongs to the caller, else a 404 identical to a missing run.

    The run's bot is loaded into the same session, so ``await session.get(Bot, run.bot_id)`` does
    not query again.
    """
    stmt = (
        select(AgentRun, Bot)
        .join(Bot, Bot.id == AgentRun.bot_id)
        .where(AgentRun.id == run_id, Bot.owner_id == user.id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise http_error(404, RUN_NOT_FOUND)
    return row[0]


async def get_owned_revision(
    revision_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Revision:
    """Revision ``revision_id`` if its bot belongs to the caller, else a 404 identical to a missing one.

    The revision's bot is loaded into the same session, so ``await session.get(Bot,
    revision.bot_id)`` does not query again.
    """
    stmt = (
        select(Revision, Bot)
        .join(Bot, Bot.id == Revision.bot_id)
        .where(Revision.id == revision_id, Bot.owner_id == user.id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise http_error(404, REVISION_NOT_FOUND)
    return row[0]
