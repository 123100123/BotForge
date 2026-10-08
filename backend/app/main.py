"""FastAPI application factory.

Every module in ``app/api/`` that exposes a ``router`` attribute is included automatically (except
``deps``), so later work packages add routers without editing this file.

Errors use one body shape: ``{"error": {"code", "message"}}``. Route code raises
``HTTPException(status, detail={"code": ..., "message": <Persian>})``.
"""

import asyncio
import contextlib
import importlib
import logging
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import app.api as api_package
from app.agent.events import default_bus
from app.agent.repository import SqlAgentRepository
from app.config import get_settings
from app.db.session import DatabaseNotConfigured, database_configured, dispose_engine, get_sessionmaker
from app.integrations.telegram import poller as telegram_poller
from app.notifications import ticker as notification_ticker
from app.security import supabase_auth
from app.security.body_limit import BodyLimitMiddleware
from app.security.cors import ALLOWED_REQUEST_HEADERS, allowed_origin_regex, allowed_origins
from app.security.rate_limit import AuthRateLimits
from app.security.redact import install_log_redaction
from app.security.sessions import SessionCookieRefresh

log = logging.getLogger(__name__)

_HTTP_MESSAGES = {
    400: "درخواست نامعتبر است.",
    401: "ورود لازم است.",
    403: "دسترسی مجاز نیست.",
    404: "مورد درخواستی پیدا نشد.",
    405: "این روش درخواست مجاز نیست.",
    409: "درخواست با وضعیت فعلی سازگار نیست.",
    413: "حجم درخواست بیش از حد مجاز است.",
    422: "اطلاعات ارسال‌شده نامعتبر است.",
}


def _error(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def _internal_error() -> JSONResponse:
    """The answer to an unhandled exception. It never carries exception details."""
    return _error(500, "internal_error", "خطای داخلی سرور رخ داد.")


class InternalErrorMiddleware:
    """Sends the generic 500 answer for an unhandled exception from inside the CORS layer.

    Starlette runs the ``Exception`` handler in ``ServerErrorMiddleware``, which wraps every
    middleware added in ``create_app``, CORS included, so that 500 answer had no CORS headers and a
    browser showed an opaque CORS error instead of the JSON body. Added directly inside CORS, this
    sends the same body through CORS and re-raises. The outer middleware then sees that the response
    has started: it does not answer again, but still runs the handler, which logs the exception, and
    the server still sees the exception, as before. An exception raised after the response has
    started (a broken event stream) cannot get an answer of its own and is only re-raised.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def send_and_track(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_and_track)
        except Exception:
            if not response_started:
                await _internal_error()(scope, receive, send)
            raise


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            return _error(
                exc.status_code, detail["code"], detail["message"], detail.get("details"), exc.headers
            )
        message = _HTTP_MESSAGES.get(exc.status_code, "خطایی رخ داد.")
        return _error(exc.status_code, f"http_{exc.status_code}", message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": [str(p) for p in e["loc"]], "type": e["type"]} for e in exc.errors()]
        return _error(422, "validation_error", _HTTP_MESSAGES[422], details)

    @app.exception_handler(DatabaseNotConfigured)
    async def _no_db(_: Request, exc: DatabaseNotConfigured) -> JSONResponse:
        return _error(503, "database_unavailable", "پایگاه داده در دسترس نیست.")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return _internal_error()


# A ``running`` run whose heartbeat (app.agent.orchestrator.HEARTBEAT_SECONDS) is older than this
# has no live process behind it. Not "every running run at startup": during a zero-downtime deploy
# the new container starts while the old one still executes its runs, and those must not be cut
# off. The price is that after a crash a run stays ``running`` (and blocks a new run on its bot)
# for up to STALE_RUN_AFTER + SWEEP_SECONDS.
STALE_RUN_AFTER = timedelta(seconds=120)
SWEEP_SECONDS = 60.0


async def mark_interrupted_runs(stale_after: timedelta = STALE_RUN_AFTER) -> int:
    """Agent runs left in ``running`` by a process that is gone become ``interrupted``, each with
    its ``run_status`` event (also published to live streams in this process)."""
    envelopes = await SqlAgentRepository(get_sessionmaker()).interrupt_stale_runs(stale_after)
    for envelope in envelopes:
        default_bus.publish(envelope)
    return len(envelopes)


async def _sweep_interrupted_runs() -> None:
    try:
        count = await mark_interrupted_runs()
        if count:
            log.info("marked %d abandoned agent runs as interrupted", count)
    except Exception:
        log.exception("could not mark interrupted agent runs")


async def _sweep_forever() -> None:
    """A run abandoned while this process is up (the previous container stopped after this one
    started) is found within SWEEP_SECONDS of going stale, not only at the next start."""
    while True:
        await asyncio.sleep(SWEEP_SECONDS)
        await _sweep_interrupted_runs()


def start_telegram_poller() -> telegram_poller.TelegramPoller | None:
    """The Telegram poller when ``TELEGRAM_MODE=polling`` (None in webhook mode, the default).
    A failure to start is logged; the rest of the app keeps serving."""
    if get_settings().TELEGRAM_MODE != "polling":
        return None
    if not database_configured():
        log.error("TELEGRAM_MODE=polling needs DATABASE_URL; Telegram updates are not fetched")
        return None
    try:
        poller = telegram_poller.start_polling(get_sessionmaker())
    except Exception as exc:  # e.g. ALL_PROXY=socks5://... without httpx's socks support
        log.error("could not start Telegram polling (%s); check the proxy settings", type(exc).__name__)
        return None
    log.info("Telegram polling mode: fetching updates with getUpdates")
    return poller


def start_notification_ticker() -> notification_ticker.NotificationTicker | None:
    """The notification ticker when ``NOTIFICATIONS_TICKER`` is on (None otherwise, the default).
    A failure to start is logged; the rest of the app keeps serving."""
    settings = get_settings()
    if not settings.NOTIFICATIONS_TICKER:
        return None
    if not database_configured():
        log.error("NOTIFICATIONS_TICKER needs DATABASE_URL; notifications are not sent")
        return None
    try:
        ticker = notification_ticker.start_ticker(get_sessionmaker(), settings=settings)
    except Exception as exc:
        log.error("could not start the notification ticker (%s)", type(exc).__name__)
        return None
    log.info("notification ticker started (every %ss)", settings.NOTIFICATIONS_TICK_SECONDS)
    return ticker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    sweeper: asyncio.Task[None] | None = None
    if database_configured():
        await _sweep_interrupted_runs()
        sweeper = asyncio.create_task(_sweep_forever(), name="interrupted-run-sweeper")
    poller = start_telegram_poller()
    app.state.telegram_poller = poller
    ticker = start_notification_ticker()
    app.state.notification_ticker = ticker
    try:
        yield
    finally:
        if ticker is not None:
            await ticker.stop()
        if poller is not None:
            await poller.stop()
        if sweeper is not None:
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper
        await dispose_engine()


def include_api_routers(app: FastAPI) -> list[str]:
    included: list[str] = []
    for info in pkgutil.iter_modules(api_package.__path__):
        if info.name == "deps":
            continue
        module = importlib.import_module(f"{api_package.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            app.include_router(router)
            included.append(info.name)
    return included


def create_app() -> FastAPI:
    settings = get_settings()
    install_log_redaction()  # SECURITY (WP4b): redact tokens and credentials from every log record
    # SECURITY: the interactive docs and the OpenAPI schema need no login and map every route, so they
    # exist only when API_DOCS_ENABLED is set (local development). ``app.openapi()`` works either way.
    docs = settings.API_DOCS_ENABLED
    app = FastAPI(
        title="BotForge",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.auth_rate_limits = AuthRateLimits()  # login and signup limits, per app instance
    # SECURITY: says which AUTH_PROVIDER signs owners in; a supabase setup without usable keys is
    # logged as an error here, at startup, and then refuses every login (fail closed).
    supabase_auth.check_configuration(settings)
    # Re-sends the session cookie after a sliding renewal (app/security/sessions.py; AUTH_PROVIDER=local
    # only). Innermost, so it sees every response the routes produce, including Response objects.
    app.add_middleware(SessionCookieRefresh)
    # SECURITY: FastAPI parses a body before authentication runs, so bodies are capped up front.
    # Added before CORS so that CORS stays the outer layer and also decorates 413 answers.
    app.add_middleware(BodyLimitMiddleware)
    # Directly inside CORS, so that the 500 answer to an unhandled exception gets CORS headers too.
    app.add_middleware(InternalErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(settings.FRONTEND_ORIGIN),
        allow_origin_regex=allowed_origin_regex(settings.FRONTEND_ORIGIN_REGEX),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=list(ALLOWED_REQUEST_HEADERS),  # Authorization by name (app/security/cors.py)
    )
    install_error_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    include_api_routers(app)
    return app


app = create_app()
