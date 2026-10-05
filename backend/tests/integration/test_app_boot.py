"""App skeleton: boots with no database, auto-includes routers, uniform error bodies."""

import importlib
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

import app.api as api_package
from app.api.deps import CurrentUser, get_current_user
from app.config import Settings, get_settings
from app.main import create_app
from app.security.sessions import SESSION_COOKIE, new_token
from tests.integration.helpers import make_client

PROBE = """
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/probe/ok")
async def ok() -> dict[str, str]:
    return {"probe": "ok"}


@router.get("/probe/domain")
async def domain() -> None:
    raise HTTPException(409, detail={"code": "probe_conflict", "message": "تداخل"})


@router.get("/probe/boom")
async def boom() -> None:
    raise RuntimeError("boom")
"""


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def probe_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    (tmp_path / "zz_probe_router.py").write_text(PROBE, encoding="utf-8")
    (tmp_path / "zz_not_a_router.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(api_package, "__path__", [*api_package.__path__, str(tmp_path)])
    importlib.invalidate_caches()
    yield create_app()
    for name in ("zz_probe_router", "zz_not_a_router"):
        sys.modules.pop(f"app.api.{name}", None)


def test_settings_import_cleanly_without_env() -> None:
    settings = Settings(_env_file=None)
    assert settings.DATABASE_URL is None
    assert settings.async_database_url is None
    assert settings.FRONTEND_ORIGIN


def test_security_settings_defaults_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("API_DOCS_ENABLED", "AUTH_SESSION_MAX_AGE_DAYS"):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.API_DOCS_ENABLED is False  # the API docs are opt-in (local development only)
    assert defaults.AUTH_SESSION_MAX_AGE_DAYS == 30
    for days in (1, 366):
        assert days == Settings(_env_file=None, AUTH_SESSION_MAX_AGE_DAYS=days).AUTH_SESSION_MAX_AGE_DAYS
    for days in (0, -1, 367):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, AUTH_SESSION_MAX_AGE_DAYS=days)


def test_database_url_is_rewritten_for_asyncpg() -> None:
    assert Settings(_env_file=None, DATABASE_URL="postgres://u@h/db").async_database_url == (
        "postgresql+asyncpg://u@h/db"
    )
    assert Settings(_env_file=None, DATABASE_URL="postgresql://u@h/db").async_database_url == (
        "postgresql+asyncpg://u@h/db"
    )


async def test_healthz_without_database() -> None:
    async with make_client(create_app()) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_lifespan_skips_database_work_when_unconfigured() -> None:
    app = create_app()
    async with app.router.lifespan_context(app):
        pass  # would raise DatabaseNotConfigured if it touched the database


def test_real_routers_are_included_and_deps_is_not() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {"/healthz", "/me", "/bots", "/bots/{bot_id}", "/bots/{bot_id}/data"} <= paths


async def test_router_auto_include(probe_app: Any) -> None:
    paths = set(probe_app.openapi()["paths"])
    assert "/probe/ok" in paths
    async with make_client(probe_app) as client:
        response = await client.get("/probe/ok")
    assert response.json() == {"probe": "ok"}


async def test_error_body_for_domain_http_error(probe_app: Any) -> None:
    async with make_client(probe_app) as client:
        response = await client.get("/probe/domain")
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "probe_conflict", "message": "تداخل"}}


async def test_error_body_for_unhandled_exception(probe_app: Any) -> None:
    async with make_client(probe_app) as client:
        response = await client.get("/probe/boom")
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "internal_error"
    assert "boom" not in response.text


async def test_error_body_for_unknown_route_and_method() -> None:
    async with make_client(create_app()) as client:
        missing = await client.get("/nope")
        wrong_method = await client.post("/healthz")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "http_404"
    assert missing.json()["error"]["message"]
    assert wrong_method.status_code == 405
    assert set(wrong_method.json()["error"]) == {"code", "message"}


async def test_error_body_for_validation_failure(nodb_client: httpx.AsyncClient) -> None:
    response = await nodb_client.post("/bots", json={})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"]


async def test_error_body_when_database_is_not_configured() -> None:
    app = create_app()

    async def user() -> CurrentUser:
        return CurrentUser(id=uuid.UUID(int=1), email="alice@example.com")

    app.dependency_overrides[get_current_user] = user
    async with make_client(app) as client:
        response = await client.get("/bots")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"


# Routes reachable without a session. The Telegram webhook authenticates by its secret header; the
# auth routes are how a session is obtained (and ended).
PUBLIC_ROUTES = {"/healthz", "/tg/{bot_id}", "/auth/signup", "/auth/login", "/auth/logout"}
STATE_CHANGING = {"post", "put", "patch", "delete"}
# FastAPI's own docs pages and schema: outside the schema, public whenever served, and a map of every
# route. They exist only with API_DOCS_ENABLED (local development).
DOCS_ROUTES = ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json")


async def test_every_api_route_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: a route added without ``get_current_user`` (directly or through an ownership
    dependency) fails here, before any database access. Public routes belong in PUBLIC_ROUTES.

    Routes are enumerated from the OpenAPI schema (included routers are not flattened into
    ``app.routes`` in this FastAPI version), so ``include_in_schema=False`` routes are not covered.
    FastAPI's docs routes are such routes: with API_DOCS_ENABLED false (the default) they must not exist.
    """
    monkeypatch.setenv("API_DOCS_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()
    checked = 0
    async with make_client(app) as client:
        for path in DOCS_ROUTES:
            response = await client.get(path)
            assert response.status_code == 404, (path, response.status_code)
            assert response.json()["error"]["code"] == "http_404"
        for template, operations in app.openapi()["paths"].items():
            if template in PUBLIC_ROUTES:
                continue
            path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), template)
            for method in sorted(set(operations) & {"get", "post", "put", "patch", "delete"}):
                response = await client.request(method.upper(), path)
                assert response.status_code == 401, (method, template, response.status_code)
                assert response.json()["error"]["code"] == "auth_required"
                checked += 1
    assert checked >= 11  # /me, the bot routes and the data routes


async def test_api_docs_are_served_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-in for local development works (so the 404s above come from the setting)."""
    monkeypatch.setenv("API_DOCS_ENABLED", "true")
    get_settings.cache_clear()
    async with make_client(create_app()) as client:
        for path in DOCS_ROUTES:
            assert (await client.get(path)).status_code == 200, path
        schema = (await client.get("/openapi.json")).json()
    assert {"/me", "/bots", "/auth/login"} <= set(schema["paths"])


async def test_every_state_changing_route_requires_the_csrf_header() -> None:
    """Regression guard: with a session cookie but without ``X-BotForge-CSRF: 1`` (or with a foreign
    Origin), every state-changing route except the Telegram webhook is refused with 403 before any
    database work. GET routes are not subject to the check (they get as far as the session lookup)."""
    app = create_app()
    cookie = {"Cookie": f"{SESSION_COOKIE}={new_token()}"}
    attempts = {
        "no header": cookie,
        "wrong value": {**cookie, "X-BotForge-CSRF": "true"},
        "foreign origin": {**cookie, "X-BotForge-CSRF": "1", "Origin": "https://evil.example.com"},
        "null origin": {**cookie, "X-BotForge-CSRF": "1", "Origin": "null"},
    }
    checked = 0
    async with make_client(app) as client:
        for template, operations in app.openapi()["paths"].items():
            if template == "/tg/{bot_id}":
                continue
            path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), template)
            for method in sorted(set(operations) & STATE_CHANGING):
                for label, headers in attempts.items():
                    response = await client.request(method.upper(), path, headers=headers, json={})
                    assert response.status_code == 403, (label, method, template, response.status_code)
                    assert response.json()["error"]["code"] == "csrf_failed"
                checked += 1
    assert checked >= 20  # the auth routes, bot, data, run, revision, simulator and Telegram routes


async def test_cors_allows_only_the_frontend_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example.com")
    get_settings.cache_clear()
    async with make_client(create_app()) as client:
        allowed = await client.options(
            "/bots",
            headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "GET"},
        )
        denied = await client.options(
            "/bots",
            headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
        )
    assert allowed.headers.get("access-control-allow-origin") == "https://app.example.com"
    assert "access-control-allow-origin" not in denied.headers


async def test_cors_accepts_several_comma_separated_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_ORIGIN", " https://app.example.com/ , https://preview.example.com ,, / ")
    get_settings.cache_clear()
    try:
        assert get_settings().frontend_origins == ["https://app.example.com", "https://preview.example.com"]
        async with make_client(create_app()) as client:
            results: dict[str, str | None] = {}
            for origin in ("https://app.example.com", "https://preview.example.com", "https://evil.example.com"):
                preflight = await client.options(
                    "/bots", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
                )
                simple = await client.get("/healthz", headers={"Origin": origin})
                assert preflight.headers.get("access-control-allow-origin") == simple.headers.get(
                    "access-control-allow-origin"
                )
                results[origin] = simple.headers.get("access-control-allow-origin")
    finally:
        get_settings.cache_clear()
    assert results == {
        "https://app.example.com": "https://app.example.com",
        "https://preview.example.com": "https://preview.example.com",
        "https://evil.example.com": None,
    }
