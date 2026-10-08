"""``get_current_user`` with AUTH_PROVIDER=supabase through the real app, with no database: header
parsing, status codes and bodies, and that every refusal comes before any database work (with
DATABASE_URL unset, reaching the database would answer 503 ``database_unavailable`` instead).
Restored from the staging branch's tests/unit/security/test_current_user.py (b0125fc) and extended
for the provider switch. The same paths against a database: tests/integration/test_supabase_auth_api.py.
"""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Request
from pydantic import ValidationError

from app.api.auth import LOCAL_AUTH_DISABLED
from app.api.deps import AUTH_REQUIRED, AUTH_UNAVAILABLE, INVALID_TOKEN, request_credential
from app.config import Settings, get_settings
from app.main import create_app
from app.security import supabase_auth
from app.security.sessions import SESSION_COOKIE, new_token, request_refresh
from app.security.supabase_auth import SupabaseUser
from tests.unit.security.tokens import (
    EMAIL,
    JWKS_URL,
    OMIT,
    SUPABASE_URL,
    StubJwks,
    claims,
    forge,
    mint,
    new_ec_key,
    new_secret,
    public_jwk,
)

SECRET = new_secret()
Configure = Callable[..., None]
DATABASE_UNAVAILABLE = "database_unavailable"  # app.main: what reaching the (unset) database answers


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch) -> Iterator[Configure]:
    """Set the auth environment explicitly (no .env, no database) and rebuild the verifier."""

    def apply(
        *,
        provider: str = "supabase",
        secret: str | None = None,
        jwks_url: str | None = None,
        supabase_url: str = SUPABASE_URL,
        **extra: str,
    ) -> None:
        monkeypatch.setenv("AUTH_PROVIDER", provider)
        monkeypatch.setenv("SUPABASE_JWT_SECRET", secret or "")
        monkeypatch.setenv("SUPABASE_JWKS_URL", jwks_url or "")
        monkeypatch.setenv("SUPABASE_URL", supabase_url)
        monkeypatch.setenv("DATABASE_URL", "")
        for name, value in extra.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        supabase_auth.reset_verifier()

    yield apply
    get_settings.cache_clear()
    supabase_auth.reset_verifier()


def client_for(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(create_app()) as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def error(pair: tuple[str, str]) -> dict[str, dict[str, str]]:
    return {"error": {"code": pair[0], "message": pair[1]}}


def identity_app() -> FastAPI:
    """The real app plus a probe route that returns the verified credential, so the bearer path can
    be checked end to end without the database that /me needs for the account row."""
    app = create_app()

    @app.get("/probe/identity")
    async def identity(credential: object = Depends(request_credential)) -> dict[str, str | None]:
        assert isinstance(credential, SupabaseUser)
        return {"id": str(credential.id), "email": credential.email}

    return app


# --------------------------------------------------------------------------- the bearer token


async def test_a_valid_token_is_verified_before_the_database_is_reached(configure: Configure) -> None:
    configure(secret=SECRET)
    sub = str(uuid.uuid4())
    token = mint(SECRET, "HS256", sub=sub)
    async with client_for(identity_app()) as c:
        verified = await c.get("/probe/identity", headers=bearer(token))
        assert verified.status_code == 200 and verified.json() == {"id": sub, "email": EMAIL}
        lowercase = await c.get("/probe/identity", headers={"Authorization": f"bearer {token}"})
        assert lowercase.status_code == 200
        # /me goes on to the account row, which needs the database (unset here): auth itself passed.
        me = await c.get("/me", headers=bearer(token))
    assert me.status_code == 503 and me.json()["error"]["code"] == DATABASE_UNAVAILABLE


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer ", "Basic dXNlcjpwYXNz", "Token abc", "abc"])
async def test_missing_or_non_bearer_authorization_is_401(
    configure: Configure, client: httpx.AsyncClient, header: str | None
) -> None:
    configure(secret=SECRET)
    response = await client.get("/me", headers={} if header is None else {"Authorization": header})
    assert response.status_code == 401
    assert response.json() == error(AUTH_REQUIRED)
    assert response.headers["www-authenticate"] == "Bearer"


async def test_invalid_tokens_are_401_without_details(
    configure: Configure, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    configure(secret=SECRET)
    caplog.set_level(logging.DEBUG)
    now = int(time.time())
    bad_tokens = [
        "not-a-jwt",
        "a.b.c",
        mint(SECRET, "HS256", exp=now - 3600),  # expired
        mint(new_secret(), "HS256"),  # wrong signature (another project's secret)
        mint(SECRET, "HS256", aud="anon"),
        mint(SECRET, "HS256", iss="https://other-project.supabase.co/auth/v1"),
        mint(SECRET, "HS256", sub=OMIT),
        mint(SECRET, "HS256", sub="local-dev-owner"),  # not a user id
        mint(SECRET, "HS256", is_anonymous=True),  # an anonymous Supabase session
        forge({"alg": "none", "typ": "JWT"}, claims(), b"x"),
        f"{mint(SECRET, 'HS256')} trailing",
    ]
    for token in bad_tokens:
        response = await client.get("/me", headers=bearer(token))
        assert response.status_code == 401, token
        assert response.json() == error(INVALID_TOKEN)
        assert response.headers["www-authenticate"] == "Bearer"
        if len(token) > 20:
            assert token.split(" ")[0] not in response.text
            assert token.split(" ")[0] not in caplog.text
    assert any(r.name == "app.api.deps" for r in caplog.records)  # rejections are logged, tokens are not


async def test_unconfigured_auth_fails_closed(configure: Configure, client: httpx.AsyncClient) -> None:
    configure()  # AUTH_PROVIDER=supabase, but neither SUPABASE_JWKS_URL nor SUPABASE_JWT_SECRET
    for token in (mint(SECRET, "HS256"), forge({"alg": "none", "typ": "JWT"}, claims(), b"x")):
        for method, path in (("GET", "/me"), ("GET", "/bots"), ("POST", "/bots")):
            response = await client.request(method, path, headers=bearer(token), json={"name": "x"})
            assert response.status_code == 503, (method, path)
            assert response.json() == error(AUTH_UNAVAILABLE)
    anonymous = await client.get("/bots")
    assert anonymous.status_code == 401 and anonymous.json() == error(AUTH_REQUIRED)


async def test_a_short_secret_fails_closed(configure: Configure, client: httpx.AsyncClient) -> None:
    weak = "x" * 20
    configure(secret=weak)
    response = await client.get("/me", headers=bearer(mint(weak + "y" * 12, "HS256")))
    assert response.status_code == 503 and response.json() == error(AUTH_UNAVAILABLE)


async def test_jwks_mode_through_the_app(configure: Configure, monkeypatch: pytest.MonkeyPatch) -> None:
    key = new_ec_key()
    stub = StubJwks(public_jwk(key, "k1"))
    monkeypatch.setattr(supabase_auth, "fetch_jwks", stub)
    configure(jwks_url=JWKS_URL, secret=SECRET)  # both set: JWKS wins
    sub = str(uuid.uuid4())
    async with client_for(identity_app()) as c:
        response = await c.get("/probe/identity", headers=bearer(mint(key, "ES256", kid="k1", sub=sub)))
        assert response.status_code == 200 and response.json()["id"] == sub
        assert stub.urls == [JWKS_URL]
        legacy = await c.get("/me", headers=bearer(mint(SECRET, "HS256")))
    assert legacy.status_code == 401 and legacy.json() == error(INVALID_TOKEN)


async def test_unreachable_jwks_is_503(
    configure: Configure, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubJwks()
    stub.fail = True
    monkeypatch.setattr(supabase_auth, "fetch_jwks", stub)
    configure(jwks_url=JWKS_URL)
    response = await client.get("/me", headers=bearer(mint(new_ec_key(), "ES256", kid="k1")))
    assert response.status_code == 503
    assert response.json() == error(AUTH_UNAVAILABLE)


# --------------------------------------------------------------------------- cookies and CSRF


def session_cookie_headers() -> dict[str, str]:
    """A well-formed session cookie with the CSRF header: everything the own login looks for."""
    return {"Cookie": f"{SESSION_COOKIE}={new_token()}", "X-BotForge-CSRF": "1"}


async def test_a_session_cookie_authenticates_nothing(
    configure: Configure, client: httpx.AsyncClient
) -> None:
    configure(secret=SECRET)
    for method, path in (
        ("GET", "/me"),
        ("GET", "/bots"),
        ("POST", "/bots"),
        ("DELETE", f"/bots/{uuid.uuid4()}"),
    ):
        response = await client.request(method, path, headers=session_cookie_headers(), json={"name": "x"})
        # 401 before any database work (not 503), and not a CSRF verdict either: cookies are not read.
        assert response.status_code == 401, (method, path, response.text)
        assert response.json() == error(AUTH_REQUIRED)
        assert response.headers["www-authenticate"] == "Bearer"


async def test_bearer_requests_need_no_csrf_header(configure: Configure, client: httpx.AsyncClient) -> None:
    configure(secret=SECRET)
    token = mint(SECRET, "HS256")
    for headers in ({}, {"Origin": "https://evil.example.com"}, {"X-BotForge-CSRF": "1"}):
        response = await client.post("/bots", json={"name": "x"}, headers={**bearer(token), **headers})
        # Authentication passed without the CSRF header or a listed Origin; the account row is next.
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == DATABASE_UNAVAILABLE


async def test_local_mode_ignores_bearer_tokens(configure: Configure, client: httpx.AsyncClient) -> None:
    configure(provider="local", secret=SECRET)
    token = mint(SECRET, "HS256")
    for method in ("GET", "POST"):
        response = await client.request(method, "/bots", headers=bearer(token), json={"name": "x"})
        assert response.status_code == 401 and response.json()["error"]["code"] == "auth_required"
        assert "www-authenticate" not in response.headers  # the own login's 401, exactly as before


@pytest.mark.parametrize("path", ["/auth/signup", "/auth/login", "/auth/logout"])
async def test_the_own_login_routes_are_404(
    configure: Configure, client: httpx.AsyncClient, path: str
) -> None:
    configure(secret=SECRET, AUTH_ALLOW_SIGNUP="false")
    body = {"email": "owner@example.com", "password": "correct horse battery"}
    for headers in (
        {},
        {"X-BotForge-CSRF": "1"},
        {"X-BotForge-CSRF": "1", "Origin": "https://evil.example.com"},
    ):
        response = await client.post(path, json=body, headers=headers)
        # Before the CSRF check, the signup switch and the rate limits, and without the database.
        assert response.status_code == 404, (path, headers, response.text)
        assert response.json() == error(LOCAL_AUTH_DISABLED)
        assert "set-cookie" not in response.headers


async def test_the_own_login_routes_still_exist_in_local_mode(
    configure: Configure, client: httpx.AsyncClient
) -> None:
    configure(provider="local")
    response = await client.post("/auth/login", json={"email": "a@example.com", "password": "x" * 12})
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"


# Routes reachable without a login (tests/integration/test_app_boot.py has the same list for the own
# login). In supabase mode the /auth routes answer 404 (see above).
PUBLIC_ROUTES = {"/healthz", "/tg/{bot_id}", "/auth/signup", "/auth/login", "/auth/logout"}


async def test_every_api_route_requires_a_bearer_token(
    configure: Configure, client: httpx.AsyncClient
) -> None:
    """Regression guard for supabase mode, as test_every_api_route_requires_authentication is for the
    own login: every route refuses a request without a bearer token, with a session cookie and the
    CSRF header present (they count for nothing), before any database access."""
    configure(secret=SECRET)
    checked = 0
    for template, operations in create_app().openapi()["paths"].items():
        if template in PUBLIC_ROUTES:
            continue
        path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), template)
        for method in sorted(set(operations) & {"get", "post", "put", "patch", "delete"}):
            response = await client.request(method.upper(), path, headers=session_cookie_headers())
            assert response.status_code == 401, (method, template, response.status_code)
            assert response.json() == error(AUTH_REQUIRED)
            checked += 1
    assert checked >= 50  # /me, bots, runs, revisions, data, uploads, analysis, copilot, team, ...


# --------------------------------------------------------------------------- the cookie refresh


async def test_the_cookie_refresh_middleware_passes_through_in_supabase_mode(configure: Configure) -> None:
    def app_with_refresh() -> FastAPI:
        app = create_app()

        @app.get("/probe/refresh")
        async def refresh(request: Request) -> dict[str, bool]:
            request_refresh(request, new_token(), timedelta(hours=1))  # what a local renewal asks for
            return {"ok": True}

        return app

    configure(provider="local")
    async with client_for(app_with_refresh()) as c:
        local = await c.get("/probe/refresh")
    assert local.headers.get("set-cookie", "").startswith(f"{SESSION_COOKIE}=")
    configure(secret=SECRET)
    async with client_for(app_with_refresh()) as c:
        supabase = await c.get("/probe/refresh")
    assert supabase.status_code == 200 and "set-cookie" not in supabase.headers


# --------------------------------------------------------------------------- the setting and CORS


def test_auth_provider_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_PROVIDER", raising=False)
    assert Settings(_env_file=None).AUTH_PROVIDER == "local"
    for raw, expected in (
        (" Supabase ", "supabase"),
        ("LOCAL", "local"),
        ("", "local"),
        ("supabase", "supabase"),
    ):
        provider = Settings(_env_file=None, AUTH_PROVIDER=raw).AUTH_PROVIDER
        assert provider == expected, raw
    for wrong in ("keycloak", "supa base", "none", "*"):
        with pytest.raises(ValidationError):  # never a silent fallback: the process does not start
            Settings(_env_file=None, AUTH_PROVIDER=wrong)


async def test_the_cors_preflight_allows_the_bearer_header_for_listed_origins_only(
    configure: Configure,
) -> None:
    configure(secret=SECRET, FRONTEND_ORIGIN="https://app.example.com")
    requested = "authorization,content-type,x-botforge-csrf,last-event-id"

    def preflight(origin: str, headers: str = requested) -> dict[str, str]:
        return {
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": headers,
        }

    async with client_for(create_app()) as c:
        allowed = await c.options("/bots", headers=preflight("https://app.example.com"))
        foreign = await c.options("/bots", headers=preflight("https://evil.example.com"))
        unknown_header = await c.options("/bots", headers=preflight("https://app.example.com", "x-evil"))
        actual = await c.get("/me", headers={"Origin": "https://app.example.com"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://app.example.com"
    allowed_headers = {h.strip().lower() for h in allowed.headers["access-control-allow-headers"].split(",")}
    assert {"authorization", "content-type", "x-botforge-csrf", "last-event-id"} <= allowed_headers
    assert foreign.status_code == 400 and "access-control-allow-origin" not in foreign.headers
    assert unknown_header.status_code == 400
    # A 401 still carries the CORS headers, so the web app can read it and send the user to /login.
    assert actual.status_code == 401
    assert actual.headers["access-control-allow-origin"] == "https://app.example.com"
