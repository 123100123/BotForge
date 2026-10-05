"""CSRF protection for cookie-authenticated requests.

Every request with a method other than GET, HEAD or OPTIONS that carries the session cookie, and
every signup, login and logout request (login CSRF), must:

* send ``X-BotForge-CSRF: 1``. A cross-site page cannot add a custom header to a request without a
  CORS preflight, and the CORS policy (``app.main``) admits only the configured frontend origins;
* if it sends ``Origin``, send one of the allowed origins: the origin (scheme, host, port) of
  ``PUBLIC_BASE_URL`` and of every ``FRONTEND_ORIGIN`` entry. This also holds when the CORS list
  is misconfigured (a ``*`` entry never matches anything here).

Browsers send ``Origin`` already serialized (lowercase scheme and host, no default port), so the
header is compared exactly against the normalized allowed origins; ``Origin: null`` never matches.
The Telegram webhook is not cookie-authenticated and is not subject to this check.
"""

from urllib.parse import urlsplit

from fastapi import Request

from app.config import get_settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-BotForge-CSRF"
CSRF_HEADER_VALUE = "1"
_DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_of(url: str) -> str | None:
    """``scheme://host[:port]`` of an http(s) URL, as a browser serializes it; None if not one."""
    try:
        parts = urlsplit(url.strip())
        scheme, host, port = parts.scheme.lower(), parts.hostname, parts.port
    except ValueError:  # e.g. a non-numeric or out-of-range port
        return None
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    suffix = f":{port}" if port is not None and port != _DEFAULT_PORTS[scheme] else ""
    return f"{scheme}://{host}{suffix}"


def allowed_origins() -> frozenset[str]:
    settings = get_settings()
    candidates = [settings.PUBLIC_BASE_URL, *settings.frontend_origins]
    return frozenset(origin for origin in map(origin_of, candidates) if origin)


def csrf_ok(request: Request) -> bool:
    """Whether a state-changing request passes the CSRF check (see the module docstring)."""
    if [value.strip() for value in request.headers.getlist(CSRF_HEADER)] != [CSRF_HEADER_VALUE]:
        return False
    origins = request.headers.getlist("origin")
    if not origins:
        return True
    allowed = allowed_origins()
    return all(origin.strip() in allowed for origin in origins)
