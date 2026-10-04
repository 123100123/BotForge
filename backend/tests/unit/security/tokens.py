"""Locally generated keys and tokens for auth tests: no network and no Supabase project."""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

SUPABASE_URL = "https://unit-test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
EMAIL = "owner@example.com"

OMIT: Any = object()  # claim value meaning "leave this claim out"

PrivateKey = ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey


def new_secret() -> str:
    return secrets.token_urlsafe(48)  # 64 characters, like a real project secret


def new_ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def new_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(private_key: PrivateKey, kid: str) -> dict[str, Any]:
    """The JWKS entry Supabase would publish for ``private_key``."""
    public = private_key.public_key()
    if isinstance(public, ec.EllipticCurvePublicKey):
        jwk, alg = ECAlgorithm.to_jwk(public, as_dict=True), "ES256"
    else:
        jwk, alg = RSAAlgorithm.to_jwk(public, as_dict=True), "RS256"
    return {**jwk, "kid": kid, "alg": alg, "use": "sig", "key_ops": ["verify"], "ext": True}


def public_pem(private_key: PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def claims(**overrides: Any) -> dict[str, Any]:
    """Claims shaped like a Supabase access token; ``OMIT`` removes a claim."""
    now = int(time.time())
    base: dict[str, Any] = {
        "iss": ISSUER,
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "exp": now + 3600,
        "iat": now,
        "email": EMAIL,
        "role": "authenticated",
        "is_anonymous": False,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not OMIT}


def mint(key: Any, algorithm: str, *, kid: str | None = None, **overrides: Any) -> str:
    headers = {"kid": kid} if kid is not None else None
    return jwt.encode(claims(**overrides), key, algorithm=algorithm, headers=headers)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def forge(header: dict[str, Any], payload: dict[str, Any], signature: bytes = b"") -> str:
    """A token with arbitrary header and signature bytes (for attacks PyJWT refuses to sign)."""
    return ".".join(
        [b64url(json.dumps(header).encode()), b64url(json.dumps(payload).encode()), b64url(signature)]
    )


def hs256_signed_with(key_bytes: bytes, header: dict[str, Any], payload: dict[str, Any]) -> str:
    """HMAC-SHA256 over the token with arbitrary key bytes, e.g. a public key (algorithm confusion)."""
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    signature = hmac.new(key_bytes, signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url(signature)}"


class StubJwks:
    """Async JWKS fetcher serving ``document``; counts calls and can simulate an outage."""

    def __init__(self, *entries: dict[str, Any], delay: float = 0.0) -> None:
        self.document: dict[str, Any] = {"keys": list(entries)}
        self.calls = 0
        self.urls: list[str] = []
        self.fail = False
        self.delay = delay

    async def __call__(self, url: str) -> Any:
        self.calls += 1
        self.urls.append(url)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise OSError("JWKS endpoint unreachable")
        return json.loads(json.dumps(self.document))


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
