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
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import app.api as api_package
from app.config import get_settings
from app.db.models import AgentRun
from app.db.session import DatabaseNotConfigured, database_configured, dispose_engine, get_sessionmaker
from app.security.body_limit import BodyLimitMiddleware
from app.security.redact import install_log_redaction

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


async def mark_interrupted_runs() -> int:
    """Agent runs left in ``running`` by a previous process become ``interrupted``."""
    async with get_sessionmaker()() as session:
        result = await session.execute(
            update(AgentRun).where(AgentRun.status == "running").values(status="interrupted")
        )
        await session.commit()
        return result.rowcount or 0  # type: ignore[attr-defined]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if database_configured():
        try:
            count = await mark_interrupted_runs()
            if count:
                log.info("marked %d running agent runs as interrupted", count)
        except Exception:
            log.exception("could not mark interrupted agent runs")
    yield
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
    app = FastAPI(title="BotForge", lifespan=lifespan)
    # SECURITY: FastAPI parses a body before authentication runs, so bodies are capped up front.
    # Added before CORS so that CORS stays the outer layer and also decorates 413 answers.
    app.add_middleware(BodyLimitMiddleware)
    # Directly inside CORS, so that the 500 answer to an unhandled exception gets CORS headers too.
    app.add_middleware(InternalErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_ORIGIN],
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
