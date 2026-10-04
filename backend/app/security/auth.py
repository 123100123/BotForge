"""Supabase access-token verification.

The browser signs in through Supabase Auth and sends the access token as
``Authorization: Bearer <jwt>``. ``JwtVerifier.verify`` turns a token into a ``CurrentUser`` or
raises; ``app/api/deps.py`` maps the errors to HTTP responses.

Two signing setups, chosen by configuration (``app/config.py``):

* asymmetric: ``SUPABASE_JWKS_URL`` (``<SUPABASE_URL>/auth/v1/.well-known/jwks.json``) publishes
  ES256 or RS256 public keys. They are cached for ``JWKS_TTL_SECONDS`` and refetched when a token
  names an unknown ``kid``. Whatever triggers it, at most one fetch happens per
  ``JWKS_MIN_REFRESH_INTERVAL_SECONDS``, so random ``kid`` values cannot hammer the endpoint.
* legacy HS256: ``SUPABASE_JWT_SECRET``, the project's shared JWT secret (32 characters or more).

If both are set, the asymmetric setup is used and the secret is ignored. If neither is set, or the
configured value is unusable, every verification raises ``AuthNotConfigured``: the service fails
closed and never accepts an unverified token.

Each mode pins its algorithms (asymmetric: ES256/RS256, each only with a key of the matching type;
legacy: HS256 only), so ``alg: none`` and an HS256 token "signed" with a public key are rejected.
Checked on every token: signature, ``exp`` (with ``LEEWAY_SECONDS`` of clock skew),
``aud == "authenticated"``, ``iss == <SUPABASE_URL>/auth/v1`` when ``SUPABASE_URL`` is set, and a
non-empty string ``sub``. Anonymous Supabase sessions (``is_anonymous: true``) are refused because
owners sign up with email and password.

Exception messages are for server logs only. They never contain token material and are never sent
to clients.
"""

import asyncio
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Self

import jwt
from jwt import PyJWK
from pydantic import BaseModel

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

AUDIENCE = "authenticated"
LEEWAY_SECONDS = 30
MAX_TOKEN_LENGTH = 16 * 1024
MAX_KID_LENGTH = 256
MAX_SUB_LENGTH = 255
MIN_SECRET_LENGTH = 32
ASYMMETRIC_ALGORITHMS = ("ES256", "RS256")

JWKS_TTL_SECONDS = 600.0
JWKS_MIN_REFRESH_INTERVAL_SECONDS = 15.0
JWKS_FETCH_TIMEOUT_SECONDS = 5.0
JWKS_MAX_BYTES = 256 * 1024

# JWS compact serialization: three non-empty base64url segments without padding.
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

JwksFetcher = Callable[[str], Awaitable[Any]]


class CurrentUser(BaseModel):
    id: str  # Supabase user id (JWT "sub")
    email: str | None = None


class AuthError(Exception):
    """Base class for verification failures. The message is for server logs only."""


class InvalidToken(AuthError):
    """The token is malformed, expired, or fails a check (HTTP 401)."""


class AuthUnavailable(AuthError):
    """Tokens cannot be verified right now, e.g. no signing keys could be loaded (HTTP 503)."""


class AuthNotConfigured(AuthUnavailable):
    """No usable verification setup is configured (HTTP 503; fail closed)."""


@dataclass(frozen=True)
class AuthConfig:
    jwks_url: str | None = None
    jwt_secret: str | None = field(default=None, repr=False)
    issuer: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        base_url = (settings.SUPABASE_URL or "").strip().rstrip("/")
        return cls(
            jwks_url=(settings.SUPABASE_JWKS_URL or "").strip() or None,
            jwt_secret=(settings.SUPABASE_JWT_SECRET or "").strip() or None,
            issuer=f"{base_url}/auth/v1" if base_url else None,
        )


# --------------------------------------------------------------------------- JWKS


def jwks_url_problem(url: str) -> str | None:
    """Why ``url`` cannot be used as the key source, or None if it can.

    Keys must arrive over TLS: whoever controls the key set controls every login. Plain http is
    accepted only for a loopback host (a local Supabase stack).
    """
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return "SUPABASE_JWKS_URL is not a valid URL"
    if parts.scheme == "https" and host:
        return None
    if parts.scheme == "http" and host in _LOOPBACK_HOSTS:
        return None
    return "SUPABASE_JWKS_URL must be an https:// URL (http:// is accepted only for localhost)"


def _usable_jwk(entry: dict[str, Any]) -> PyJWK | None:
    """A verification key from one JWKS entry, or None if it must not be used.

    Only public EC P-256 (ES256) and RSA (RS256) signature keys qualify. Symmetric ("oct") keys,
    private keys, other curves and key types, and keys declared for another algorithm or use are
    skipped, so the key set can never widen the pinned algorithms.
    """
    kty, crv = entry.get("kty"), entry.get("crv")
    if kty == "EC" and crv == "P-256":
        algorithm = "ES256"
    elif kty == "RSA":
        algorithm = "RS256"
    else:
        return None
    if entry.get("alg", algorithm) != algorithm or entry.get("use", "sig") != "sig":
        return None
    key_ops = entry.get("key_ops")
    if key_ops is not None and (not isinstance(key_ops, list) or "verify" not in key_ops):
        return None
    if "d" in entry:  # private key material has no place in a published key set
        return None
    try:
        return PyJWK(entry, algorithm=algorithm)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        return None


def parse_jwks(document: Any) -> dict[str, PyJWK]:
    """The usable keys of a JWKS document by ``kid`` (the first entry wins on duplicates)."""
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise ValueError("JWKS document must be a JSON object with a 'keys' list")
    keys: dict[str, PyJWK] = {}
    for entry in document["keys"]:
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid or kid in keys:
            continue
        key = _usable_jwk(entry)
        if key is not None:
            keys[kid] = key
    return keys


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a 3xx surfaces as HTTPError: keys come only from the configured URL


def _fetch_jwks_blocking(url: str) -> Any:
    opener = urllib.request.build_opener(_RefuseRedirects())
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "botforge-backend"}
    )
    with opener.open(request, timeout=JWKS_FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(JWKS_MAX_BYTES + 1)
    if len(body) > JWKS_MAX_BYTES:
        raise ValueError("JWKS document is too large")
    return json.loads(body)


async def fetch_jwks(url: str) -> Any:
    """Default fetcher: GET the JWKS document (certificate-verified TLS, no redirects, bounded
    time and size), off the event loop."""
    return await asyncio.to_thread(_fetch_jwks_blocking, url)


class JwksCache:
    """Signing keys from one JWKS URL: TTL cache, refresh on unknown ``kid``, bounded refresh rate.

    A failed refresh keeps the previously loaded keys. A successful one replaces them, so a key
    removed from the set stops being trusted.
    """

    def __init__(
        self,
        url: str,
        fetch: JwksFetcher,
        *,
        ttl: float = JWKS_TTL_SECONDS,
        min_refresh_interval: float = JWKS_MIN_REFRESH_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self._fetch = fetch
        self._ttl = ttl
        self._min_refresh_interval = min_refresh_interval
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._loaded_at: float | None = None
        self._attempted_at: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> PyJWK:
        # While another request refreshes expired keys, the cached ones keep serving.
        if self._is_stale() and not (self._keys and self._lock.locked()):
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            await self._refresh(wanted_kid=kid)
            key = self._keys.get(kid)
        if key is not None:
            return key
        if not self._keys:
            raise AuthUnavailable("no usable signing keys could be loaded from the JWKS URL")
        raise InvalidToken("token names an unknown signing key")

    def _is_stale(self) -> bool:
        return self._loaded_at is None or self._clock() - self._loaded_at >= self._ttl

    async def _refresh(self, wanted_kid: str | None = None) -> None:
        async with self._lock:
            # The request we waited for may already have done the work.
            if wanted_kid is not None and wanted_kid in self._keys:
                return
            if wanted_kid is None and not self._is_stale():
                return
            now = self._clock()
            if self._attempted_at is not None and now - self._attempted_at < self._min_refresh_interval:
                return  # bounded refresh rate, whatever the trigger
            self._attempted_at = now
            try:
                keys = parse_jwks(await self._fetch(self.url))
            except Exception as exc:  # network, HTTP status, JSON, or document shape
                log.warning(
                    "JWKS refresh from %s failed (%s); %d cached key(s) stay in use",
                    self.url,
                    type(exc).__name__,
                    len(self._keys),
                )
                return
            if not keys:
                log.warning("JWKS at %s contains no usable ES256/RS256 signing keys", self.url)
            self._keys = keys
            self._loaded_at = self._clock()


# --------------------------------------------------------------------------- verifier


class JwtVerifier:
    """Verifies Supabase access tokens for one configuration."""

    def __init__(
        self,
        config: AuthConfig,
        *,
        fetch: JwksFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
        jwks_ttl: float = JWKS_TTL_SECONDS,
        jwks_min_refresh_interval: float = JWKS_MIN_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        self.issuer = config.issuer
        self._secret: bytes | None = None
        self._jwks: JwksCache | None = None
        self._problem: str | None = None
        if config.jwks_url:
            self._problem = jwks_url_problem(config.jwks_url)
            if self._problem is None:
                self._jwks = JwksCache(
                    config.jwks_url,
                    fetch or fetch_jwks,
                    ttl=jwks_ttl,
                    min_refresh_interval=jwks_min_refresh_interval,
                    clock=clock,
                )
                if config.jwt_secret:
                    log.warning(
                        "SUPABASE_JWKS_URL and SUPABASE_JWT_SECRET are both set; tokens are verified "
                        "with the JWKS keys only and SUPABASE_JWT_SECRET is ignored"
                    )
        elif config.jwt_secret:
            if len(config.jwt_secret) < MIN_SECRET_LENGTH:
                self._problem = f"SUPABASE_JWT_SECRET is shorter than {MIN_SECRET_LENGTH} characters"
            else:
                self._secret = config.jwt_secret.encode("utf-8")
        else:
            self._problem = "neither SUPABASE_JWKS_URL nor SUPABASE_JWT_SECRET is set"
        if self._problem is not None:
            log.error("authentication is not configured: %s; authenticated requests get 503", self._problem)

    @property
    def mode(self) -> Literal["jwks", "hs256"] | None:
        if self._jwks is not None:
            return "jwks"
        if self._secret is not None:
            return "hs256"
        return None

    async def verify(self, token: str) -> CurrentUser:
        if self._problem is not None:
            raise AuthNotConfigured(self._problem)
        if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH or not _TOKEN_SHAPE.fullmatch(token):
            raise InvalidToken("not a compact JWS")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidToken(f"unreadable header ({type(exc).__name__})") from None
        alg = header.get("alg")
        if self._jwks is not None:
            # Algorithm and kid are checked before any key lookup or network access.
            if alg not in ASYMMETRIC_ALGORITHMS:
                raise InvalidToken("algorithm not allowed")
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > MAX_KID_LENGTH:
                raise InvalidToken("missing or invalid key id")
            key = await self._jwks.get(kid)
            if key.algorithm_name != alg:
                raise InvalidToken("algorithm does not match the signing key")
            claims = self._decode(token, key, key.algorithm_name)
        elif self._secret is not None:
            if alg != "HS256":
                raise InvalidToken("algorithm not allowed")
            claims = self._decode(token, self._secret, "HS256")
        else:  # unreachable: _problem is set whenever no key source is configured
            raise AuthNotConfigured("no verification key")
        return self._user(claims)

    def _decode(self, token: str, key: PyJWK | bytes, algorithm: str) -> dict[str, Any]:
        required = ["exp", "sub", "aud", *(["iss"] if self.issuer else [])]
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=AUDIENCE,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={
                    "verify_signature": True,
                    "require": required,
                    "enforce_minimum_key_length": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise InvalidToken(f"rejected ({type(exc).__name__})") from None

    def _user(self, claims: dict[str, Any]) -> CurrentUser:
        # PyJWT has validated these already; the identity-critical ones are re-checked locally so a
        # library regression (such as PyJWT 2.10.0's substring issuer match) cannot open the door.
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub.strip() or len(sub) > MAX_SUB_LENGTH:
            raise InvalidToken("unusable subject")
        aud = claims.get("aud")
        if aud != AUDIENCE and not (isinstance(aud, list) and AUDIENCE in aud):
            raise InvalidToken("wrong audience")
        if self.issuer is not None and claims.get("iss") != self.issuer:
            raise InvalidToken("wrong issuer")
        if claims.get("is_anonymous") is True:
            raise InvalidToken("anonymous session")
        email = claims.get("email")
        return CurrentUser(id=sub, email=email if isinstance(email, str) and email else None)


# --------------------------------------------------------------------------- process-wide verifier

_current: tuple[AuthConfig, JwtVerifier] | None = None


def verifier_from_settings() -> JwtVerifier:
    """The process-wide verifier for the current settings, rebuilt when they change."""
    global _current
    config = AuthConfig.from_settings(get_settings())
    if _current is None or _current[0] != config:
        _current = (config, JwtVerifier(config))
    return _current[1]


def reset_verifier() -> None:
    """Forget the process-wide verifier and its cached keys (for tests)."""
    global _current
    _current = None


async def get_verifier() -> JwtVerifier:
    """FastAPI dependency used by ``get_current_user``."""
    return verifier_from_settings()
