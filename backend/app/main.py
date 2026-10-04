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
from app.config import get_settings
from app.db.models import AgentRun
from app.db.session import DatabaseNotConfigured, database_configured, dispose_engine, get_sessionmaker

log = logging.getLogger(__name__)

_HTTP_MESSAGES = {
    400: "درخواست نامعتبر است.",
    401: "ورود لازم است.",
    403: "دسترسی مجاز نیست.",
    404: "مورد درخواستی پیدا نشد.",
    405: "این روش درخواست مجاز نیست.",
    409: "درخواست با وضعیت فعلی سازگار نیست.",
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
    app = FastAPI(title="BotForge", lifespan=lifespan)
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
