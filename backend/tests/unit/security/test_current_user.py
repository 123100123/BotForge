"""``get_current_user`` through the real app (no database): header parsing, status codes, bodies."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest
import pytest_asyncio

from app.api.deps import AUTH_REQUIRED, AUTH_UNAVAILABLE, INVALID_TOKEN
from app.config import get_settings
from app.main import create_app
from app.security import auth
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


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch) -> Iterator[Configure]:
    """Set the auth environment explicitly (no .env, no database) and rebuild the verifier."""

    def apply(
        *, secret: str | None = None, jwks_url: str | None = None, supabase_url: str = SUPABASE_URL
    ) -> None:
        monkeypatch.setenv("SUPABASE_JWT_SECRET", secret or "")
        monkeypatch.setenv("SUPABASE_JWKS_URL", jwks_url or "")
        monkeypatch.setenv("SUPABASE_URL", supabase_url)
        monkeypatch.setenv("DATABASE_URL", "")
        get_settings.cache_clear()
        auth.reset_verifier()

    yield apply
    get_settings.cache_clear()
    auth.reset_verifier()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def error(pair: tuple[str, str]) -> dict[str, dict[str, str]]:
    return {"error": {"code": pair[0], "message": pair[1]}}


async def test_valid_token_returns_the_user(configure: Configure, client: httpx.AsyncClient) -> None:
    configure(secret=SECRET)
    sub = str(uuid.uuid4())
    response = await client.get("/me", headers=bearer(mint(SECRET, "HS256", sub=sub)))
    assert response.status_code == 200
    assert response.json() == {"id": sub, "email": EMAIL}
    lowercase = await client.get("/me", headers={"Authorization": f"bearer {mint(SECRET, 'HS256')}"})
    assert lowercase.status_code == 200


@pytest.mark.parametrize("header", [None, "", "Bearer", "Basic dXNlcjpwYXNz", "Token abc", "abc"])
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
        mint(SECRET, "HS256", exp=now - 3600),
        mint(new_secret(), "HS256"),
        mint(SECRET, "HS256", aud="anon"),
        mint(SECRET, "HS256", iss="https://other-project.supabase.co/auth/v1"),
        mint(SECRET, "HS256", sub=OMIT),
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


async def test_unconfigured_auth_fails_closed_with_503(
    configure: Configure, client: httpx.AsyncClient
) -> None:
    configure()  # neither SUPABASE_JWKS_URL nor SUPABASE_JWT_SECRET
    for token in (mint(SECRET, "HS256"), forge({"alg": "none", "typ": "JWT"}, claims(), b"x")):
        response = await client.get("/me", headers=bearer(token))
        assert response.status_code == 503
        assert response.json() == error(AUTH_UNAVAILABLE)


async def test_jwks_mode_through_the_app(
    configure: Configure, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = new_ec_key()
    stub = StubJwks(public_jwk(key, "k1"))
    monkeypatch.setattr(auth, "fetch_jwks", stub)
    configure(jwks_url=JWKS_URL, secret=SECRET)  # both set: JWKS wins
    sub = str(uuid.uuid4())
    response = await client.get("/me", headers=bearer(mint(key, "ES256", kid="k1", sub=sub)))
    assert response.status_code == 200 and response.json()["id"] == sub
    assert stub.urls == [JWKS_URL]
    legacy = await client.get("/me", headers=bearer(mint(SECRET, "HS256")))
    assert legacy.status_code == 401 and legacy.json() == error(INVALID_TOKEN)


async def test_unreachable_jwks_is_503(
    configure: Configure, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = StubJwks()
    stub.fail = True
    monkeypatch.setattr(auth, "fetch_jwks", stub)
    configure(jwks_url=JWKS_URL)
    response = await client.get("/me", headers=bearer(mint(new_ec_key(), "ES256", kid="k1")))
    assert response.status_code == 503
    assert response.json() == error(AUTH_UNAVAILABLE)


def test_openapi_documents_the_bearer_scheme() -> None:
    schema = create_app().openapi()
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert {"HTTPBearer": []} in schema["paths"]["/bots/{bot_id}"]["get"]["security"]
