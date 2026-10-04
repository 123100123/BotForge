"""JwtVerifier: both signing setups, every rejection rule, JWKS caching and refresh bounds."""

import asyncio
import json
import time
import uuid
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.config import Settings, get_settings
from app.security.auth import (
    JWKS_MIN_REFRESH_INTERVAL_SECONDS,
    JWKS_TTL_SECONDS,
    LEEWAY_SECONDS,
    MAX_TOKEN_LENGTH,
    AuthConfig,
    AuthNotConfigured,
    AuthUnavailable,
    CurrentUser,
    InvalidToken,
    JwtVerifier,
    jwks_url_problem,
    parse_jwks,
    reset_verifier,
    verifier_from_settings,
)
from tests.unit.security.tokens import (
    EMAIL,
    ISSUER,
    JWKS_URL,
    OMIT,
    SUPABASE_URL,
    FakeClock,
    StubJwks,
    b64url,
    claims,
    forge,
    hs256_signed_with,
    mint,
    new_ec_key,
    new_rsa_key,
    new_secret,
    public_jwk,
    public_pem,
)

KID_EC = "ec-key-1"
KID_RSA = "rsa-key-1"


@pytest.fixture(scope="module")
def ec_key() -> ec.EllipticCurvePrivateKey:
    return new_ec_key()


@pytest.fixture(scope="module")
def rsa_key() -> Any:
    return new_rsa_key()


@pytest.fixture(scope="module")
def secret() -> str:
    return new_secret()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def stub(ec_key: Any, rsa_key: Any) -> StubJwks:
    return StubJwks(public_jwk(ec_key, KID_EC), public_jwk(rsa_key, KID_RSA))


@pytest.fixture
def asym(stub: StubJwks, clock: FakeClock) -> JwtVerifier:
    return JwtVerifier(AuthConfig(jwks_url=JWKS_URL, issuer=ISSUER), fetch=stub, clock=clock)


@pytest.fixture
def hs(secret: str) -> JwtVerifier:
    return JwtVerifier(AuthConfig(jwt_secret=secret, issuer=ISSUER))


async def rejected(verifier: JwtVerifier, token: str) -> InvalidToken:
    with pytest.raises(InvalidToken) as info:
        await verifier.verify(token)
    if token:
        assert token not in str(info.value)  # log text never carries the token
    return info.value


# ----------------------------------------------------------------------------- accepted tokens


async def test_valid_es256_token(asym: JwtVerifier, ec_key: Any, stub: StubJwks) -> None:
    sub = str(uuid.uuid4())
    assert await asym.verify(mint(ec_key, "ES256", kid=KID_EC, sub=sub)) == CurrentUser(id=sub, email=EMAIL)
    assert asym.mode == "jwks"
    assert stub.urls == [JWKS_URL]


async def test_valid_rs256_token(asym: JwtVerifier, rsa_key: Any) -> None:
    sub = str(uuid.uuid4())
    assert (await asym.verify(mint(rsa_key, "RS256", kid=KID_RSA, sub=sub))).id == sub


async def test_valid_hs256_token(hs: JwtVerifier, secret: str) -> None:
    sub = str(uuid.uuid4())
    assert await hs.verify(mint(secret, "HS256", sub=sub)) == CurrentUser(id=sub, email=EMAIL)
    assert hs.mode == "hs256"


async def test_email_is_optional(hs: JwtVerifier, secret: str) -> None:
    assert (await hs.verify(mint(secret, "HS256", email=OMIT))).email is None
    assert (await hs.verify(mint(secret, "HS256", email=""))).email is None


async def test_audience_list_containing_authenticated_is_accepted(hs: JwtVerifier, secret: str) -> None:
    assert (await hs.verify(mint(secret, "HS256", aud=["authenticated", "other"]))).email == EMAIL


# ----------------------------------------------------------------------------- claim checks


async def test_expired_token_is_rejected_but_small_clock_skew_is_tolerated(
    hs: JwtVerifier, secret: str
) -> None:
    now = int(time.time())
    await rejected(hs, mint(secret, "HS256", exp=now - 3600))
    await rejected(hs, mint(secret, "HS256", exp=now - LEEWAY_SECONDS - 30))
    await rejected(hs, mint(secret, "HS256", exp=OMIT))  # exp is required
    await rejected(hs, mint(secret, "HS256", exp="tomorrow"))
    assert (await hs.verify(mint(secret, "HS256", exp=now - 5))).email == EMAIL  # within the leeway


async def test_token_issued_in_the_future_is_rejected(hs: JwtVerifier, secret: str) -> None:
    await rejected(hs, mint(secret, "HS256", iat=int(time.time()) + 3600))
    await rejected(hs, mint(secret, "HS256", nbf=int(time.time()) + 3600))


@pytest.mark.parametrize("aud", ["anon", "service_role", "authenticated ", ["other"], "", None, OMIT])
async def test_wrong_or_missing_audience_is_rejected(hs: JwtVerifier, secret: str, aud: Any) -> None:
    await rejected(hs, mint(secret, "HS256", aud=aud))


@pytest.mark.parametrize(
    "iss",
    [
        "https://other-project.supabase.co/auth/v1",
        f"{ISSUER}/",
        ISSUER[:-1],  # a prefix: PyJWT 2.10.0 accepted substrings
        SUPABASE_URL,
        "supabase",
        "",
        None,
        123,
        OMIT,
    ],
)
async def test_wrong_or_missing_issuer_is_rejected(hs: JwtVerifier, secret: str, iss: Any) -> None:
    # Signed by hand: PyJWT refuses to encode a non-string iss.
    token = hs256_signed_with(secret.encode(), {"alg": "HS256", "typ": "JWT"}, claims(iss=iss))
    await rejected(hs, token)


async def test_issuer_is_not_checked_without_supabase_url(secret: str) -> None:
    verifier = JwtVerifier(AuthConfig(jwt_secret=secret))
    assert (await verifier.verify(mint(secret, "HS256", iss="https://anything.example"))).email == EMAIL


@pytest.mark.parametrize("sub", [OMIT, None, "", "   ", 123, ["a"], "x" * 256])
async def test_missing_or_unusable_subject_is_rejected(hs: JwtVerifier, secret: str, sub: Any) -> None:
    await rejected(hs, mint(secret, "HS256", sub=sub))


async def test_anonymous_session_is_rejected(hs: JwtVerifier, secret: str) -> None:
    await rejected(hs, mint(secret, "HS256", is_anonymous=True))


# ----------------------------------------------------------------------------- signatures


async def test_bad_signature_is_rejected(asym: JwtVerifier, hs: JwtVerifier, secret: str) -> None:
    await rejected(asym, mint(new_ec_key(), "ES256", kid=KID_EC))  # right kid, someone else's key
    await rejected(hs, mint(new_secret(), "HS256"))  # another project's secret
    header, payload, signature = mint(secret, "HS256").split(".")
    forged_payload = b64url(json.dumps(claims(sub=str(uuid.uuid4()))).encode())
    await rejected(hs, f"{header}.{forged_payload}.{signature}")  # payload swapped under a valid signature
    await rejected(hs, f"{header}.{payload}.{signature[:-4]}")  # truncated signature


@pytest.mark.parametrize("alg", ["none", "None", "NONE", ""])
async def test_alg_none_is_rejected_in_both_modes(
    asym: JwtVerifier, hs: JwtVerifier, stub: StubJwks, alg: str
) -> None:
    for signature in (b"", b"x"):
        token = forge({"alg": alg, "typ": "JWT", "kid": KID_EC}, claims(), signature)
        await rejected(asym, token)
        await rejected(hs, token)
    await rejected(hs, forge({"typ": "JWT"}, claims(), b"x"))  # no alg at all
    assert stub.calls == 0  # refused before any key lookup


async def test_hs256_token_signed_with_the_public_key_is_rejected(
    asym: JwtVerifier, stub: StubJwks, ec_key: Any, rsa_key: Any
) -> None:
    for key, kid in ((ec_key, KID_EC), (rsa_key, KID_RSA)):
        header = {"alg": "HS256", "typ": "JWT", "kid": kid}
        for key_bytes in (public_pem(key), json.dumps(public_jwk(key, kid)).encode()):
            await rejected(asym, hs256_signed_with(key_bytes, header, claims()))
    assert stub.calls == 0  # refused before any key lookup


async def test_token_algorithm_must_match_the_key_type(asym: JwtVerifier, ec_key: Any, rsa_key: Any) -> None:
    await rejected(asym, mint(rsa_key, "RS256", kid=KID_EC))
    await rejected(asym, mint(ec_key, "ES256", kid=KID_RSA))


async def test_legacy_mode_accepts_only_hs256(
    hs: JwtVerifier, secret: str, ec_key: Any, rsa_key: Any
) -> None:
    await rejected(hs, mint(ec_key, "ES256", kid=KID_EC))
    await rejected(hs, mint(rsa_key, "RS256", kid=KID_RSA))
    await rejected(hs, mint(secret, "HS384"))
    await rejected(hs, mint(secret, "HS512"))


async def test_asymmetric_token_needs_a_key_id(asym: JwtVerifier, stub: StubJwks, ec_key: Any) -> None:
    await rejected(asym, mint(ec_key, "ES256"))
    await rejected(asym, forge({"alg": "ES256", "kid": ""}, claims(), b"sig"))
    await rejected(asym, forge({"alg": "ES256", "kid": 7}, claims(), b"sig"))
    await rejected(asym, forge({"alg": "ES256", "kid": "k" * 300}, claims(), b"sig"))
    assert stub.calls == 0


@pytest.mark.parametrize(
    "token", ["", "abc", "a.b", "a.b.c.d", "a..c", "eyJ.eyJ.", "a.b.c", "x y.z.w", "Bearer a.b.c"]
)
async def test_malformed_tokens_are_rejected(asym: JwtVerifier, hs: JwtVerifier, token: str) -> None:
    await rejected(asym, token)
    await rejected(hs, token)


async def test_oversized_token_is_rejected(hs: JwtVerifier, secret: str) -> None:
    token = mint(secret, "HS256", filler="x" * MAX_TOKEN_LENGTH)
    assert len(token) > MAX_TOKEN_LENGTH
    await rejected(hs, token)


# ----------------------------------------------------------------------------- JWKS cache


async def test_unknown_kid_triggers_one_refresh(
    asym: JwtVerifier, stub: StubJwks, clock: FakeClock, ec_key: Any
) -> None:
    await asym.verify(mint(ec_key, "ES256", kid=KID_EC))
    assert stub.calls == 1
    rotated = new_ec_key()
    stub.document["keys"].append(public_jwk(rotated, "ec-key-2"))  # Supabase publishes a new key
    clock.advance(JWKS_MIN_REFRESH_INTERVAL_SECONDS + 1)

    sub = str(uuid.uuid4())
    assert (await asym.verify(mint(rotated, "ES256", kid="ec-key-2", sub=sub))).id == sub
    assert stub.calls == 2
    await asym.verify(mint(rotated, "ES256", kid="ec-key-2"))  # now cached
    await asym.verify(mint(ec_key, "ES256", kid=KID_EC))
    assert stub.calls == 2


async def test_unknown_kid_refreshes_are_rate_limited(
    asym: JwtVerifier, stub: StubJwks, clock: FakeClock, ec_key: Any
) -> None:
    await asym.verify(mint(ec_key, "ES256", kid=KID_EC))
    clock.advance(JWKS_MIN_REFRESH_INTERVAL_SECONDS + 1)
    flood = [mint(ec_key, "ES256", kid=f"random-{i}") for i in range(50)]
    results = await asyncio.gather(*(asym.verify(t) for t in flood), return_exceptions=True)
    assert all(isinstance(r, InvalidToken) for r in results)
    assert stub.calls == 2  # one refresh for the whole flood

    clock.advance(1)
    await rejected(asym, mint(ec_key, "ES256", kid="random-x"))
    assert stub.calls == 2  # still inside the interval
    clock.advance(JWKS_MIN_REFRESH_INTERVAL_SECONDS)
    await rejected(asym, mint(ec_key, "ES256", kid="random-y"))
    assert stub.calls == 3


async def test_concurrent_requests_share_one_fetch(ec_key: Any, clock: FakeClock) -> None:
    stub = StubJwks(public_jwk(ec_key, KID_EC), delay=0.01)
    verifier = JwtVerifier(AuthConfig(jwks_url=JWKS_URL, issuer=ISSUER), fetch=stub, clock=clock)
    tokens = [mint(ec_key, "ES256", kid=KID_EC) for _ in range(20)]
    users = await asyncio.gather(*(verifier.verify(t) for t in tokens))
    assert len(users) == 20
    assert stub.calls == 1


async def test_keys_are_refetched_after_the_ttl(
    asym: JwtVerifier, stub: StubJwks, clock: FakeClock, ec_key: Any
) -> None:
    token = mint(ec_key, "ES256", kid=KID_EC)
    await asym.verify(token)
    clock.advance(JWKS_TTL_SECONDS - 1)
    await asym.verify(token)
    assert stub.calls == 1
    clock.advance(2)
    await asym.verify(token)
    assert stub.calls == 2


async def test_a_key_removed_from_the_set_stops_being_trusted(
    asym: JwtVerifier, stub: StubJwks, clock: FakeClock, ec_key: Any
) -> None:
    token = mint(ec_key, "ES256", kid=KID_EC)
    await asym.verify(token)
    stub.document["keys"] = [k for k in stub.document["keys"] if k["kid"] != KID_EC]
    clock.advance(JWKS_TTL_SECONDS + 1)
    await rejected(asym, token)


async def test_unreachable_jwks_without_cached_keys_is_unavailable(
    asym: JwtVerifier, stub: StubJwks, clock: FakeClock, ec_key: Any
) -> None:
    stub.fail = True
    token = mint(ec_key, "ES256", kid=KID_EC)
    for _ in range(3):
        with pytest.raises(AuthUnavailable):
            await asym.verify(token)
    assert stub.calls == 1  # retries are rate limited too
    stub.fail = False
    clock.advance(JWKS_MIN_REFRESH_INTERVAL_SECONDS + 1)
    assert (await asym.verify(token)).email == EMAIL
    assert stub.calls == 2


async def test_cached_keys_survive_a_failed_refresh(
    asym: JwtVerifier, stub: StubJwks, clock: FakeClock, ec_key: Any
) -> None:
    token = mint(ec_key, "ES256", kid=KID_EC)
    await asym.verify(token)
    stub.fail = True
    clock.advance(JWKS_TTL_SECONDS + 1)
    assert (await asym.verify(token)).email == EMAIL
    assert stub.calls == 2


async def test_an_empty_key_set_is_unavailable(asym: JwtVerifier, stub: StubJwks, ec_key: Any) -> None:
    stub.document = {"keys": []}  # e.g. a legacy-only project pointed at its JWKS URL
    with pytest.raises(AuthUnavailable):
        await asym.verify(mint(ec_key, "ES256", kid=KID_EC))


async def test_symmetric_keys_in_the_jwks_are_never_used(clock: FakeClock, secret: str) -> None:
    stub = StubJwks({"kty": "oct", "k": b64url(secret.encode()), "kid": "hmac", "alg": "HS256"})
    verifier = JwtVerifier(AuthConfig(jwks_url=JWKS_URL, issuer=ISSUER), fetch=stub, clock=clock)
    await rejected(verifier, mint(secret, "HS256", kid="hmac"))
    with pytest.raises(AuthUnavailable):  # the oct key is not a usable key at all
        await verifier.verify(hs256_signed_with(secret.encode(), {"alg": "ES256", "kid": "hmac"}, claims()))


def test_parse_jwks_keeps_only_public_es256_and_rs256_signing_keys(ec_key: Any, rsa_key: Any) -> None:
    p384 = ec.generate_private_key(ec.SECP384R1())
    document = {
        "keys": [
            public_jwk(ec_key, "good-ec"),
            public_jwk(rsa_key, "good-rsa"),
            public_jwk(new_ec_key(), "good-ec"),  # duplicate kid: the first one wins
            {"kty": "oct", "k": b64url(b"0" * 32), "kid": "hmac", "alg": "HS256"},
            {**ECAlgorithm.to_jwk(ec_key, as_dict=True), "kid": "private"},  # carries "d"
            {**ECAlgorithm.to_jwk(p384.public_key(), as_dict=True), "kid": "p384"},
            {**public_jwk(rsa_key, "ps256"), "alg": "PS256"},
            {**public_jwk(ec_key, "rs256-declared"), "alg": "RS256"},
            {**public_jwk(rsa_key, "enc"), "use": "enc"},
            {**public_jwk(ec_key, "sign-only"), "key_ops": ["sign"]},
            {**public_jwk(ec_key, "no-kid"), "kid": ""},
            {"kty": "EC", "crv": "P-256", "kid": "broken", "x": "AAAA", "y": "AAAA"},
            {"kty": "OKP", "crv": "Ed25519", "kid": "eddsa", "x": b64url(b"0" * 32)},
            "not-an-object",
        ]
    }
    keys = parse_jwks(document)
    assert set(keys) == {"good-ec", "good-rsa"}
    assert keys["good-ec"].algorithm_name == "ES256"
    assert keys["good-rsa"].algorithm_name == "RS256"
    assert keys["good-ec"].key.public_numbers() == ec_key.public_key().public_numbers()


@pytest.mark.parametrize("document", [[], {}, {"keys": {}}, {"keys": "x"}, "keys", None])
def test_parse_jwks_rejects_documents_that_are_not_key_sets(document: Any) -> None:
    with pytest.raises(ValueError):
        parse_jwks(document)


# ----------------------------------------------------------------------------- configuration


async def test_unconfigured_verifier_fails_closed(secret: str) -> None:
    verifier = JwtVerifier(AuthConfig())
    assert verifier.mode is None
    for token in (mint(secret, "HS256"), forge({"alg": "none"}, claims(), b"x"), ""):
        with pytest.raises(AuthNotConfigured):
            await verifier.verify(token)


async def test_short_secret_is_a_configuration_error() -> None:
    verifier = JwtVerifier(AuthConfig(jwt_secret="x" * 31))
    assert verifier.mode is None
    with pytest.raises(AuthNotConfigured):
        await verifier.verify(mint(new_secret(), "HS256"))


@pytest.mark.parametrize(
    "url",
    [
        "http://unit-test-project.supabase.co/auth/v1/.well-known/jwks.json",
        "file:///etc/passwd",
        "ftp://example.com/jwks.json",
        "https://",
        "//example.com/jwks.json",
        "not a url",
        "https://[::1",
    ],
)
async def test_jwks_url_must_use_tls(url: str, ec_key: Any) -> None:
    stub = StubJwks(public_jwk(ec_key, KID_EC))
    verifier = JwtVerifier(AuthConfig(jwks_url=url, jwt_secret=new_secret()), fetch=stub)
    assert verifier.mode is None  # and no silent fallback to the secret
    with pytest.raises(AuthNotConfigured):
        await verifier.verify(mint(ec_key, "ES256", kid=KID_EC))
    assert stub.calls == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://abc.supabase.co/auth/v1/.well-known/jwks.json",
        "http://localhost:54321/auth/v1/.well-known/jwks.json",
        "http://127.0.0.1:54321/auth/v1/.well-known/jwks.json",
        "http://[::1]:54321/auth/v1/.well-known/jwks.json",
    ],
)
def test_tls_or_loopback_jwks_urls_are_accepted(url: str) -> None:
    assert jwks_url_problem(url) is None


async def test_jwks_wins_when_both_are_configured(
    stub: StubJwks, clock: FakeClock, secret: str, ec_key: Any
) -> None:
    verifier = JwtVerifier(
        AuthConfig(jwks_url=JWKS_URL, jwt_secret=secret, issuer=ISSUER), fetch=stub, clock=clock
    )
    assert verifier.mode == "jwks"
    await rejected(verifier, mint(secret, "HS256"))
    assert (await verifier.verify(mint(ec_key, "ES256", kid=KID_EC))).email == EMAIL


def test_config_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        SUPABASE_URL=" https://abc.supabase.co/ ",
        SUPABASE_JWT_SECRET=" distinctive-secret-value ",
        SUPABASE_JWKS_URL=" https://abc.supabase.co/auth/v1/.well-known/jwks.json ",
    )
    config = AuthConfig.from_settings(settings)
    assert config == AuthConfig(
        jwks_url="https://abc.supabase.co/auth/v1/.well-known/jwks.json",
        jwt_secret="distinctive-secret-value",
        issuer="https://abc.supabase.co/auth/v1",
    )
    assert "distinctive-secret-value" not in repr(config)
    empty = Settings(_env_file=None, SUPABASE_URL="", SUPABASE_JWT_SECRET="", SUPABASE_JWKS_URL=None)
    assert AuthConfig.from_settings(empty) == AuthConfig()


def test_process_wide_verifier_follows_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", new_secret())
    monkeypatch.setenv("SUPABASE_JWKS_URL", "")
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    get_settings.cache_clear()
    reset_verifier()
    try:
        first = verifier_from_settings()
        assert first is verifier_from_settings()
        assert first.mode == "hs256" and first.issuer == ISSUER
        monkeypatch.setenv("SUPABASE_JWT_SECRET", new_secret())
        get_settings.cache_clear()
        assert verifier_from_settings() is not first
    finally:
        get_settings.cache_clear()
        reset_verifier()
