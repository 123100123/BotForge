"""Owner accounts: sign up, log in, log out (cookie sessions; see ``app/security/``).

* ``POST /auth/signup`` ``{email, password}``: 201 ``{"user": {id, email}}`` and a new session cookie.
  403 ``signup_disabled`` when ``AUTH_ALLOW_SIGNUP`` is false; 422 ``invalid_email``; 422
  ``weak_password`` (fewer than 10 or more than 256 characters); 409 ``email_taken``.
* ``POST /auth/login`` ``{email, password}``: 200 ``{"user": {id, email}}`` and a new session cookie
  (a login never reuses a session). Every wrong email or password is the same 401
  ``invalid_credentials``, after the same password-hashing work.
* ``POST /auth/logout``: 204; deletes the session of the cookie (if any) and clears the cookie.
  Idempotent.

All three require the CSRF header (``X-BotForge-CSRF: 1``) and an allowed ``Origin`` when one is
sent (403 ``csrf_failed``), checked before anything else. Signup and login are rate limited per client
address, login also per email (429 ``rate_limited`` with ``Retry-After``; see
``app/security/rate_limit.py``). The session cookie the request carried, if any, is deleted when a
signup or login replaces it.

These routes are the own login (``AUTH_PROVIDER=local``). With ``AUTH_PROVIDER=supabase`` the web app
signs in through Supabase Auth, so all three answer 404 ``local_auth_disabled`` before any other check
(no CSRF, rate limit or database work), and no session cookie is ever issued. ``GET /me``
(``app/api/bots.py``) works in both modes.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import http_error, require_csrf
from app.config import get_settings
from app.db.models import User
from app.db.session import get_session
from app.security.accounts import (
    EmailTaken,
    InvalidEmail,
    WeakPassword,
    authenticate,
    create_user,
    normalize_email,
)
from app.security.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.security.rate_limit import AuthRateLimits, client_address
from app.security.sessions import (
    SESSION_COOKIE,
    clear_session_cookie,
    create_session,
    delete_session,
    new_session_lifetime,
    purge_expired_sessions,
    set_session_cookie,
)

LOCAL_AUTH_DISABLED = (
    "local_auth_disabled",
    "ورود و ثبت‌نام در این سرویس از طریق برنامهٔ وب و با Supabase انجام می‌شود.",
)


async def require_local_auth() -> None:
    """404 ``local_auth_disabled`` unless the own login is the configured provider (module docstring).
    The router's first dependency, so it runs before the CSRF check and everything else."""
    if get_settings().AUTH_PROVIDER != "local":
        raise http_error(404, LOCAL_AUTH_DISABLED)


router = APIRouter(
    prefix="/auth", tags=["auth"], dependencies=[Depends(require_local_auth), Depends(require_csrf)]
)

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

EMAIL_TAKEN = ("email_taken", "این ایمیل قبلاً ثبت شده است. وارد شوید یا ایمیل دیگری وارد کنید.")
WEAK_PASSWORD = (
    "weak_password",
    f"رمز عبور باید دست‌کم {MIN_PASSWORD_LENGTH} و حداکثر {MAX_PASSWORD_LENGTH} نویسه باشد.".translate(
        _FA_DIGITS
    ),
)
INVALID_EMAIL = ("invalid_email", "ایمیل واردشده معتبر نیست.")
SIGNUP_DISABLED = ("signup_disabled", "ثبت‌نام در این سرویس بسته است.")
INVALID_CREDENTIALS = ("invalid_credentials", "ایمیل یا رمز عبور نادرست است.")
RATE_LIMITED = (
    "rate_limited",
    "تعداد تلاش‌ها بیش از حد مجاز است. لطفاً چند دقیقه بعد دوباره تلاش کنید.",
)
NO_STORE = {"Cache-Control": "no-store"}


class Credentials(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str


class AuthOut(BaseModel):
    user: UserOut


def get_auth_rate_limits(request: Request) -> AuthRateLimits:
    """The app's login and signup limits (created with the app; see ``app.main.create_app``)."""
    limits = getattr(request.app.state, "auth_rate_limits", None)
    if limits is None:
        limits = request.app.state.auth_rate_limits = AuthRateLimits()
    return limits


def require_signup_enabled() -> None:
    if not get_settings().AUTH_ALLOW_SIGNUP:
        raise http_error(403, SIGNUP_DISABLED)


def _rate_limited(retry_after: int) -> HTTPException:
    code, message = RATE_LIMITED
    return HTTPException(
        status_code=429, detail={"code": code, "message": message}, headers={"Retry-After": str(retry_after)}
    )


async def _new_session(db: AsyncSession, request: Request, response: Response, user: User) -> AuthOut:
    """Replace the request's session (if any) with a new one for ``user``, commit, set the cookie."""
    previous = request.cookies.get(SESSION_COOKIE)
    if previous:
        await delete_session(db, previous)
    token = await create_session(db, user.id)
    out = AuthOut(user=UserOut(id=user.id, email=user.email))
    await db.commit()  # before responding: get_session's own commit runs after the response
    set_session_cookie(response, token, new_session_lifetime())  # the new session's whole life
    response.headers.update(NO_STORE)
    return out


@router.post(
    "/signup", response_model=AuthOut, status_code=201, dependencies=[Depends(require_signup_enabled)]
)
async def signup(
    body: Credentials,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    limits: AuthRateLimits = Depends(get_auth_rate_limits),
) -> AuthOut:
    wait = limits.allow_signup(client_address(request))
    if wait is not None:
        raise _rate_limited(wait)
    try:
        user = await create_user(session, body.email, body.password)
    except InvalidEmail:
        raise http_error(422, INVALID_EMAIL) from None
    except WeakPassword:
        raise http_error(422, WEAK_PASSWORD) from None
    except EmailTaken:
        raise http_error(409, EMAIL_TAKEN) from None
    return await _new_session(session, request, response, user)


@router.post("/login", response_model=AuthOut)
async def login(
    body: Credentials,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    limits: AuthRateLimits = Depends(get_auth_rate_limits),
) -> AuthOut:
    wait = limits.allow_login(client_address(request), normalize_email(body.email))
    if wait is not None:
        raise _rate_limited(wait)
    user = await authenticate(session, body.email, body.password)
    if user is None:
        raise http_error(401, INVALID_CREDENTIALS)
    await purge_expired_sessions(session, user.id)
    return await _new_session(session, request, response, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await delete_session(session, token)
        await session.commit()
    response = Response(status_code=204, headers=NO_STORE)
    clear_session_cookie(response)
    return response
