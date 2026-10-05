"""Login sessions (table ``auth_sessions``) and the ``bf_session`` cookie.

The cookie value is ``secrets.token_urlsafe(32)``: 32 random bytes, 43 URL-safe characters. The
database stores only its SHA-256 hex digest, so a leaked table cannot be replayed as cookies.

A session lives ``AUTH_SESSION_TTL_HOURS`` (default 168) after it was last renewed. Renewal slides
the expiry when a request arrives at least ``RENEW_AFTER`` (one hour) after the previous renewal, at
most once an hour per session; ``SessionCookieRefresh`` then re-sends the cookie with a fresh
``Max-Age`` so the browser keeps it as long as the server does. An expired session is rejected and
deleted when it is next presented; ``purge_expired_sessions`` also removes a user's expired sessions
at login. Login always creates a new session (rotation); logout and password resets delete them.

Cookie attributes: ``HttpOnly``, ``SameSite=Lax``, ``Path=/``, ``Max-Age`` = the TTL, and ``Secure``
unless ``AUTH_COOKIE_SECURE`` is false (plain-http local development only). No ``Domain``: the cookie
is host-only.
"""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.db.models import AuthSession, User

SESSION_COOKIE = "bf_session"
TOKEN_BYTES = 32
RENEW_AFTER = timedelta(hours=1)
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)
_REFRESH_STATE_KEY = "bf_session_refresh"


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_digest(token: str) -> str:
    """The stored form of a cookie token (SHA-256, hex)."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def well_formed(token: str) -> bool:
    """Whether ``token`` has the shape of a token this module issues (checked before any lookup)."""
    return _TOKEN_SHAPE.fullmatch(token) is not None


def session_ttl() -> timedelta:
    return timedelta(hours=get_settings().AUTH_SESSION_TTL_HOURS)


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


async def create_session(db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None) -> str:
    """A new session for ``user_id``; returns the cookie token (the caller commits)."""
    now = _now(now)
    token = new_token()
    db.add(
        AuthSession(
            user_id=user_id,
            token_hash=token_digest(token),
            created_at=now,
            expires_at=now + session_ttl(),
            last_seen_at=now,
        )
    )
    await db.flush()
    return token


@dataclass(frozen=True)
class Resolved:
    user: User | None  # None: no live session for the token
    renewed: bool = False  # the expiry was extended; the cookie should be re-sent
    wrote: bool = False  # a renewal or a purge is pending in ``db``; the caller commits it


async def resolve_session(db: AsyncSession, token: str, *, now: datetime | None = None) -> Resolved:
    """The user behind a cookie token, renewing the session when due. Expired sessions are deleted."""
    if not well_formed(token):
        return Resolved(None)
    now = _now(now)
    row = (
        await db.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .where(AuthSession.token_hash == token_digest(token))
        )
    ).first()
    if row is None:
        return Resolved(None)
    auth_session, user = row
    if auth_session.expires_at <= now:
        await db.execute(delete(AuthSession).where(AuthSession.id == auth_session.id))
        return Resolved(None, wrote=True)
    if now - auth_session.last_seen_at < RENEW_AFTER:
        return Resolved(user)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == auth_session.id)
        .values(last_seen_at=now, expires_at=now + session_ttl())
        .execution_options(synchronize_session=False)
    )
    return Resolved(user, renewed=True, wrote=True)


async def delete_session(db: AsyncSession, token: str) -> None:
    """End the session of ``token``, if there is one (the caller commits)."""
    if well_formed(token):
        await db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(token)))


async def delete_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> int:
    """End every session of ``user_id``; returns how many there were (the caller commits)."""
    result = await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    return result.rowcount or 0  # type: ignore[attr-defined]


async def purge_expired_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> None:
    """Delete the expired sessions of ``user_id`` (the caller commits)."""
    await db.execute(
        delete(AuthSession).where(AuthSession.user_id == user_id, AuthSession.expires_at <= _now(now))
    )


# --------------------------------------------------------------------------- cookie


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(session_ttl().total_seconds()),
        path="/",
        secure=get_settings().AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=get_settings().AUTH_COOKIE_SECURE, httponly=True, samesite="lax"
    )


def _sets_session_cookie(name: bytes, value: bytes) -> bool:
    return name.lower() == b"set-cookie" and value.startswith(SESSION_COOKIE.encode() + b"=")


def request_refresh(request: Request, token: str) -> None:
    """Ask ``SessionCookieRefresh`` to re-send the cookie (after a renewal) on this response."""
    setattr(request.state, _REFRESH_STATE_KEY, token)


class SessionCookieRefresh:
    """Adds the renewed session cookie to the response of a request whose session was renewed.

    A middleware rather than a header set by the dependency, because FastAPI drops a dependency's
    headers when the endpoint returns a ``Response`` itself (204 deletes, the SSE stream)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                token = (scope.get("state") or {}).get(_REFRESH_STATE_KEY)
                headers = list(message.get("headers", []))
                if token and not any(_sets_session_cookie(k, v) for k, v in headers):
                    carrier = Response()
                    set_session_cookie(carrier, token)
                    headers += [(k, v) for k, v in carrier.raw_headers if k == b"set-cookie"]
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cookie)
