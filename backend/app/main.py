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

import app.api as api_package
from app.agent.events import default_bus
from app.agent.repository import SqlAgentRepository
from app.config import get_settings
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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    sweeper: asyncio.Task[None] | None = None
    if database_configured():
        await _sweep_interrupted_runs()
        sweeper = asyncio.create_task(_sweep_forever(), name="interrupted-run-sweeper")
    yield
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
    app = FastAPI(title="BotForge", lifespan=lifespan)
    # SECURITY: FastAPI parses a body before authentication runs, so bodies are capped up front.
    # Added before CORS so that CORS stays the outer layer and also decorates 413 answers.
    app.add_middleware(BodyLimitMiddleware)
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
