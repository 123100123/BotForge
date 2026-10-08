"""FastAPI application factory.

Every module in ``app/api/`` that exposes a ``router`` attribute is included automatically (except
``deps``), so later work packages add routers without editing this file.

Errors use one body shape: ``{"error": {"code", "message"}}``. Route code raises
``HTTPException(status, detail={"code": ..., "message": <Persian>})``.
"""

import importlib
import logging
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import update
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.api as api_package
from app.agent import events as agent_events
from app.config import get_settings
from app.db.models import AgentEvent, AgentRun
from app.db.session import DatabaseNotConfigured, database_configured, dispose_engine, get_sessionmaker
from app.integrations.telegram import poller as telegram_poller
from app.notifications import ticker as notification_ticker
from app.security.body_limit import BodyLimitMiddleware
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
        return _error(500, "internal_error", "خطای داخلی سرور رخ داد.")


async def mark_interrupted_runs() -> int:
    """Agent runs left in ``running`` by a previous process become ``interrupted``.

    Each also gets a ``run_interrupted`` event and the ``run_status`` event for the new status, in
    the same transaction, so a client that tails the run sees what happened.
    """
    async with get_sessionmaker()() as session:
        result = await session.execute(
            update(AgentRun)
            .where(AgentRun.status == "running")
            .values(status="interrupted")
            .returning(AgentRun.id, AgentRun.phase)
        )
        runs = result.all()
        for run_id, phase in runs:
            for type_, payload in (
                agent_events.run_interrupted("server_restart"),
                agent_events.run_status("interrupted", phase),
            ):
                session.add(AgentEvent(run_id=run_id, type=type_, payload=payload))
        await session.commit()
        return len(runs)


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
    if database_configured():
        try:
            count = await mark_interrupted_runs()
            if count:
                log.info("marked %d running agent runs as interrupted", count)
        except Exception:
            log.exception("could not mark interrupted agent runs")
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
    # Re-sends the session cookie after a sliding renewal (app/security/sessions.py). Innermost, so
    # it sees every response the routes produce, including those returned as Response objects.
    app.add_middleware(SessionCookieRefresh)
    # SECURITY: FastAPI parses a body before authentication runs, so bodies are capped up front.
    # Added before CORS so that CORS stays the outer layer and also decorates 413 answers.
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    include_api_routers(app)
    return app


app = create_app()
