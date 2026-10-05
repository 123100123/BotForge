"""Request body size limit (roadmap: Security, abuse limits).

FastAPI reads and JSON-parses a request body BEFORE it resolves any dependency, authentication
included. Without a limit, an anonymous client can make the single backend process, which also
serves every bot's webhook, buffer and parse an arbitrarily large body on any route that takes one.

``BodyLimitMiddleware`` applies Starlette's ``RequestBodyLimitMiddleware`` to every path except the
Telegram webhook and the spreadsheet upload: a declared ``Content-Length`` over the limit gets a 413
without the body being read, and a streamed body is cut off as soon as it passes the limit. The
webhook is exempt because it checks its secret header first and only then reads the body under its
own limit (``app.api.webhook``), so an unauthenticated caller learns nothing from the size of what it
sent. The upload (``app.api.uploads``) is exempt because files may exceed 1 MiB: it authenticates the
owner and checks CSRF first, then reads the raw body under its own cap (``UPLOAD_MAX_BYTES``).

Only routes that read ``request.stream()`` under their own cap, after authentication, may live under
an exempt prefix: a JSON route there would be parsed before authentication with no limit at all.
"""

from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_BODY_BYTES = 1024 * 1024
EXEMPT_PREFIXES = (
    "/tg/",  # the webhook limits its body itself, after the secret check
    "/uploads/",  # the raw-body upload route enforces its own cap (UPLOAD_MAX_BYTES), after auth + CSRF
)


class BodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int = MAX_BODY_BYTES,
        exempt_prefixes: tuple[str, ...] = EXEMPT_PREFIXES,
    ) -> None:
        self.app = app
        self.limited = RequestBodyLimitMiddleware(app, max_body_size=max_body_bytes)
        self.exempt_prefixes = exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not scope["path"].startswith(self.exempt_prefixes):
            await self.limited(scope, receive, send)
        else:
            await self.app(scope, receive, send)
