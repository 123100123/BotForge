"""Authentication and ownership dependencies (roadmap: Security, Backend API).

``get_current_user`` verifies the Supabase access token sent as ``Authorization: Bearer <jwt>``
(see ``app/security/auth.py``). ``get_owned_bot``, ``get_owned_run`` and ``get_owned_revision`` load
an entity only when its bot belongs to the caller; anything else is a 404 with exactly the body of a
missing entity, so ids of other owners' objects cannot be probed.

Path parameter names matter: routes using these dependencies must name their placeholders
``{bot_id}``, ``{run_id}`` and ``{revision_id}``. Every dependency shares the request's single
``get_session`` (default dependency scope), so the returned objects belong to the endpoint's session.
Endpoint tests may still replace these functions through ``app.dependency_overrides``.
"""

import logging
import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, Bot, Revision
from app.db.session import get_session
from app.security.auth import AuthUnavailable, CurrentUser, InvalidToken, JwtVerifier, get_verifier

__all__ = [
    "CurrentUser",
    "bearer_scheme",
    "get_current_user",
    "get_owned_bot",
    "get_owned_revision",
    "get_owned_run",
]

log = logging.getLogger(__name__)

# auto_error=False: every failure gets the project's error body instead of FastAPI's default.
bearer_scheme = HTTPBearer(auto_error=False, description="Supabase access token")

AUTH_REQUIRED = ("auth_required", "برای ادامه وارد حساب کاربری خود شوید.")
INVALID_TOKEN = ("invalid_token", "نشست شما نامعتبر است یا به پایان رسیده است. لطفاً دوباره وارد شوید.")
AUTH_UNAVAILABLE = (
    "auth_unavailable",
    "سرویس ورود در حال حاضر در دسترس نیست. لطفاً کمی بعد دوباره تلاش کنید.",
)
BOT_NOT_FOUND = ("bot_not_found", "ربات پیدا نشد.")
RUN_NOT_FOUND = ("run_not_found", "اجرای ایجنت پیدا نشد.")
REVISION_NOT_FOUND = ("revision_not_found", "نسخه پیدا نشد.")


def _unauthorized(error: tuple[str, str]) -> HTTPException:
    code, message = error
    return HTTPException(
        status_code=401,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _not_found(error: tuple[str, str]) -> HTTPException:
    code, message = error
    return HTTPException(status_code=404, detail={"code": code, "message": message})


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: JwtVerifier = Depends(get_verifier),
) -> CurrentUser:
    """The verified caller. 401 without a valid token; 503 when verification is not possible."""
    if credentials is None:  # no Authorization header, or a scheme other than Bearer
        raise _unauthorized(AUTH_REQUIRED)
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidToken as exc:
        log.debug("access token rejected: %s", exc)
        raise _unauthorized(INVALID_TOKEN) from None
    except AuthUnavailable as exc:
        log.debug("access token not verifiable: %s", exc)
        code, message = AUTH_UNAVAILABLE
        raise HTTPException(status_code=503, detail={"code": code, "message": message}) from None


async def get_owned_bot(
    bot_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Bot:
    """The caller's bot ``bot_id``. Another owner's bot is a 404 identical to a missing one."""
    stmt = select(Bot).where(Bot.id == bot_id, Bot.owner_id == user.id)
    bot = (await session.execute(stmt)).scalar_one_or_none()
    if bot is None:
        raise _not_found(BOT_NOT_FOUND)
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
        raise _not_found(RUN_NOT_FOUND)
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
        raise _not_found(REVISION_NOT_FOUND)
    return row[0]
