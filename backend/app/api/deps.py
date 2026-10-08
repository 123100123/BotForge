"""Authentication and ownership dependencies (roadmap: Security, Backend API).

``get_current_user`` authenticates the caller with the provider that ``AUTH_PROVIDER`` names
(``app/config.py``). Each provider accepts only its own credential.

``local`` (the default; the self-hosted stack) authenticates the ``bf_session`` cookie against
``auth_sessions`` (see ``app/security/sessions.py``) and, for a state-changing method, applies the
CSRF check (``app/security/csrf.py``) before touching the database. An ``Authorization`` header is
ignored. Order and answers:

1. no session cookie: 401 ``auth_required``;
2. a method other than GET/HEAD/OPTIONS without ``X-BotForge-CSRF: 1`` or with a foreign ``Origin``:
   403 ``csrf_failed``;
3. a cookie that names no live session (unknown, malformed, expired, logged out): 401
   ``invalid_session``.

``supabase`` (the hosted deployment) authenticates the Supabase access token sent as
``Authorization: Bearer <jwt>`` with ``app/security/supabase_auth.py``, before touching the
database. Cookies are ignored entirely (a ``bf_session`` cookie authenticates nothing), and there is
no CSRF check: a browser never attaches a bearer token on its own, so a cross-site page has no
ambient credential to ride on. Order and answers (each 401 carries ``WWW-Authenticate: Bearer``):

1. no ``Authorization`` header with the ``Bearer`` scheme and a token: 401 ``auth_required``;
2. a token that fails verification (malformed, bad signature, expired, wrong audience or issuer, a
   subject that is not a user id, an anonymous session): 401 ``invalid_token``;
3. tokens cannot be verified (no key setup configured, or no signing key could be loaded): 503
   ``auth_unavailable``. The service fails closed; it never accepts an unverified token.

The caller is then the ``users`` row whose id is the token's ``sub``, created on first sight
(``app.security.accounts.ensure_external_user``), so ``bots.owner_id`` keeps its foreign key. That id
is the whole identity, never the email.

There is no other way in: no anonymous sessions, and no provider's credential counts in the other
mode.

``get_owned_bot``, ``get_owned_run`` and ``get_owned_revision`` load an entity only when its bot
belongs to the caller; anything else is a 404 with exactly the body of a missing entity, so ids of
other owners' objects cannot be probed.

Path parameter names matter: routes using these dependencies must name their placeholders
``{bot_id}``, ``{run_id}`` and ``{revision_id}``. Every dependency shares the request's single
``get_session`` (default dependency scope), so the returned objects belong to the endpoint's session.
"""

import logging
import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import AgentRun, Bot, Revision
from app.db.session import get_session
from app.security.accounts import CurrentUser, ensure_external_user
from app.security.csrf import SAFE_METHODS, csrf_ok
from app.security.sessions import SESSION_COOKIE, request_refresh, resolve_session
from app.security.supabase_auth import AuthUnavailable, InvalidToken, SupabaseUser, verifier_from_settings

__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_owned_bot",
    "get_owned_revision",
    "get_owned_run",
]

log = logging.getLogger(__name__)

AUTH_REQUIRED = ("auth_required", "برای ادامه وارد حساب کاربری خود شوید.")
INVALID_SESSION = ("invalid_session", "نشست شما نامعتبر است یا به پایان رسیده است. لطفاً دوباره وارد شوید.")
INVALID_TOKEN = ("invalid_token", "نشست شما نامعتبر است یا به پایان رسیده است. لطفاً دوباره وارد شوید.")
AUTH_UNAVAILABLE = (
    "auth_unavailable",
    "سرویس ورود در حال حاضر در دسترس نیست. لطفاً کمی بعد دوباره تلاش کنید.",
)
CSRF_FAILED = ("csrf_failed", "درخواست تأیید نشد. صفحه را دوباره بارگذاری کنید و دوباره تلاش کنید.")
BOT_NOT_FOUND = ("bot_not_found", "ربات پیدا نشد.")
RUN_NOT_FOUND = ("run_not_found", "اجرای ایجنت پیدا نشد.")
REVISION_NOT_FOUND = ("revision_not_found", "نسخه پیدا نشد.")

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def http_error(status: int, error: tuple[str, str]) -> HTTPException:
    code, message = error
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _bearer_unauthorized(error: tuple[str, str]) -> HTTPException:
    code, message = error
    return HTTPException(status_code=401, detail={"code": code, "message": message}, headers=BEARER_CHALLENGE)


def require_csrf(request: Request) -> None:
    """403 ``csrf_failed`` unless the request passes the CSRF check."""
    if not csrf_ok(request):
        raise http_error(403, CSRF_FAILED)


async def session_token(request: Request) -> str:
    """The session cookie of a request that passes the CSRF check (local steps 1 and 2)."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise http_error(401, AUTH_REQUIRED)
    if request.method not in SAFE_METHODS:
        require_csrf(request)
    return token


async def bearer_identity(request: Request) -> SupabaseUser:
    """The verified identity of the request's ``Authorization: Bearer`` token (supabase steps 1 to
    3). The log line of a refusal names the reason only, never token material."""
    scheme, token = get_authorization_scheme_param(request.headers.get("Authorization"))
    if scheme.lower() != "bearer" or not token:
        raise _bearer_unauthorized(AUTH_REQUIRED)
    try:
        return await verifier_from_settings().verify(token)
    except InvalidToken as exc:
        log.debug("access token rejected: %s", exc)
        raise _bearer_unauthorized(INVALID_TOKEN) from None
    except AuthUnavailable as exc:
        log.debug("access token not verifiable: %s", exc)
        raise http_error(503, AUTH_UNAVAILABLE) from None


async def request_credential(request: Request) -> str | SupabaseUser:
    """The request's credential for the configured provider: a session cookie token (local) or a
    verified token identity (supabase). Every refusal that needs no database happens here, and it is
    declared before ``get_session`` in ``get_current_user``, so these refusals (and a JWKS fetch)
    come before any database work."""
    if get_settings().AUTH_PROVIDER == "supabase":
        return await bearer_identity(request)
    return await session_token(request)


async def get_current_user(
    request: Request,
    credential: str | SupabaseUser = Depends(request_credential),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    """The signed-in caller (see the module docstring for the checks and their order)."""
    if isinstance(credential, SupabaseUser):
        account = await ensure_external_user(session, credential.id, credential.email)
        if account.wrote:
            await session.commit()  # the row exists for the endpoint's foreign keys; its locks are released
        return CurrentUser(id=account.id, email=account.email)
    token = credential
    resolved = await resolve_session(session, token)
    user = None if resolved.user is None else CurrentUser(id=resolved.user.id, email=resolved.user.email)
    if resolved.wrote:
        await session.commit()  # a renewal or the purge of an expired session, whatever comes next
    if user is None:
        raise http_error(401, INVALID_SESSION)
    if resolved.refresh_max_age is not None:  # renewed: re-send the cookie for what is left of it
        request_refresh(request, token, resolved.refresh_max_age)
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
