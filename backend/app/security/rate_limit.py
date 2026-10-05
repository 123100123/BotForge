"""In-process rate limits (one backend process with one worker; see the Dockerfile).

``RateLimiter`` allows at most ``limit`` events per sliding ``window`` per key. Keys that saw no
event for a whole window are dropped by a sweep that runs at most once per window, so keys chosen by
unauthenticated callers (emails, addresses) cannot grow memory without bound.

Login and signup limits (``AuthRateLimits``) count every attempt, successful or not, per client
address and, for login, per email.

Client address: ``request.client.host``. Behind a reverse proxy that is the proxy's address unless
uvicorn's proxy-header support rewrites it from ``X-Forwarded-For``; uvicorn does that only for
connections from the addresses in ``--forwarded-allow-ips`` / the ``FORWARDED_ALLOW_IPS`` environment
variable (default ``127.0.0.1,::1``). This module never reads ``X-Forwarded-For`` itself. If the proxy
is not trusted that way, every caller shares the proxy's address and the per-address limit becomes
one limit for everybody. IPv6 addresses are limited per /64, the block usually given to one host.
"""

import hashlib
import ipaddress
import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

AUTH_WINDOW_SECONDS = 15 * 60.0
LOGIN_ATTEMPTS_PER_EMAIL = 10
AUTH_ATTEMPTS_PER_ADDRESS = 30  # logins and signups together


class RateLimiter:
    """At most ``limit`` events per ``window`` seconds per key (in process; one backend process)."""

    def __init__(self, window: float = 60.0, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = clock()

    def allow(self, key: str, limit: int) -> bool:
        """Record an event for ``key`` and return True, or return False (recording nothing) when
        ``key`` already had ``limit`` events in the last window."""
        now = self._clock()
        self._sweep(now)
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()
        self._expire(hits, now)
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str) -> int:
        """Whole seconds until ``key`` regains an event (at least 1)."""
        hits = self._hits.get(key)
        if not hits:
            return 1
        return max(1, math.ceil(self.window - (self._clock() - hits[0])))

    def __len__(self) -> int:
        return len(self._hits)

    def _expire(self, hits: deque[float], now: float) -> None:
        while hits and now - hits[0] > self.window:
            hits.popleft()

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < self.window:
            return
        self._last_sweep = now
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] > self.window]:
            del self._hits[key]


def client_address(request: Request) -> str:
    """The rate-limit key for the caller's address (see the module docstring)."""
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return f"other:{host[:64]}"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, 64), strict=False))
    return str(ip)


class AuthRateLimits:
    """The login and signup limits of one app instance (``app.state.auth_rate_limits``)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.by_address = RateLimiter(AUTH_WINDOW_SECONDS, clock=clock)
        self.by_email = RateLimiter(AUTH_WINDOW_SECONDS, clock=clock)

    def allow_signup(self, address: str) -> int | None:
        """None when allowed (and counted); otherwise the seconds to wait."""
        if not self.by_address.allow(address, AUTH_ATTEMPTS_PER_ADDRESS):
            return self.by_address.retry_after(address)
        return None

    def allow_login(self, address: str, email: str) -> int | None:
        """None when allowed (and counted for the address and the email); otherwise the seconds to
        wait. ``email`` is the normalized address as typed; only its digest is kept."""
        if not self.by_address.allow(address, AUTH_ATTEMPTS_PER_ADDRESS):
            return self.by_address.retry_after(address)
        key = hashlib.sha256(email.encode("utf-8", "surrogatepass")).hexdigest()
        if not self.by_email.allow(key, LOGIN_ATTEMPTS_PER_EMAIL):
            return self.by_email.retry_after(key)
        return None
