r"""CORS policy (roadmap: Security, "CORS: only the frontend origin").

The web app calls this API from its own origins: the production site, a custom domain, deploy
previews. CORS decides which of them a browser lets read the API's answers. It is not
authentication (a client outside a browser ignores it); authentication is a Bearer token that the
web app attaches itself, never a cookie.

``FRONTEND_ORIGIN`` is a comma-separated list. Each entry is normalized to the form a browser sends
in its ``Origin`` header (lowercase, no trailing slash, no default port). An entry that is not an
http(s) origin, ``*`` and ``null`` included, is ignored with a warning: a configuration mistake can
only narrow CORS, never open it to every site, and it does not stop the process, which also serves
every bot's Telegram webhook.

``FRONTEND_ORIGIN_REGEX`` (optional, unset by default) also allows the https origins it matches,
for preview URLs that change per pull request, e.g.
``https://deploy-preview-[0-9]+--<site>\.netlify\.app``. It is anchored here, only ever matches a
well-formed https origin, and is ignored with a warning when it does not compile or when it also
matches an origin no deployment of ours uses (``_FOREIGN_ORIGINS``: a catch-all, or every site on a
shared host). Risk: whoever can get a page served at a matching origin (a site with a matching name,
or a deploy preview built from their pull request) can call the API from a browser. Such a page
still cannot act as a signed-in user unless it already holds that user's token, so the impact is
low, but the pattern must name the project's own site. Keep it simple (literal text, character
classes, single quantifiers): it runs against every request's ``Origin`` header.
"""

import logging
import re

log = logging.getLogger(__name__)

# scheme://host[:port] in lowercase; the host is a DNS name, an IPv4 address or a bracketed IPv6 one.
_ORIGIN = re.compile(
    r"(?P<scheme>https?)://"
    r"(?P<host>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*|\[[0-9a-f:.]+\])"
    r"(?::(?P<port>[0-9]{1,5}))?"
)
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Checked before the configured pattern, in linear time: the whole Origin header must be a
# well-formed https origin, so the pattern never sees plain http, "null" or an over-long value.
_HTTPS_ORIGIN = r"(?=https://[a-z0-9.-]{1,253}(?::[0-9]{1,5})?\Z)"

# Origins no deployment of ours uses. A pattern that matches one of them is a catch-all or admits
# every site on a shared host, not only this project's own previews.
_FOREIGN_ORIGINS = (
    "null",
    "https://example.com",
    "https://example.netlify.app",
    "https://deploy-preview-1--example.netlify.app",
    "https://example.vercel.app",
    "https://example.onrender.com",
)


def normalize_origin(entry: str) -> str | None:
    """``entry`` in the form a browser sends in ``Origin``, or None if it is not an http(s) origin."""
    candidate = entry.strip().rstrip("/")
    if not candidate.isascii():  # browsers send an internationalized host in its xn-- form
        return None
    match = _ORIGIN.fullmatch(candidate.lower())
    if match is None:
        return None
    origin = f"{match['scheme']}://{match['host']}"
    if match["port"] is not None:
        port = int(match["port"])
        if not 0 < port <= 65535:
            return None
        if port != _DEFAULT_PORTS[match["scheme"]]:
            origin += f":{port}"
    return origin


def allowed_origins(value: str) -> list[str]:
    """The origins listed in ``FRONTEND_ORIGIN`` (comma-separated), normalized, without duplicates."""
    origins: list[str] = []
    for entry in value.split(","):
        if not entry.strip():
            continue
        origin = normalize_origin(entry)
        if origin is None:
            log.warning(
                "FRONTEND_ORIGIN: ignoring %r, not an http(s) origin such as https://app.example.com "
                "(no path, no wildcard)",
                re.sub(r"//.*@", "//***@", entry.strip()),  # never repeat a password pasted in by mistake
            )
        elif origin not in origins:
            origins.append(origin)
    if not origins:
        log.warning("FRONTEND_ORIGIN lists no valid origin")
    return origins


def allowed_origin_regex(value: str | None) -> str | None:
    """``FRONTEND_ORIGIN_REGEX`` anchored and limited to https origins; None if unset or rejected."""
    pattern = (value or "").strip()
    if not pattern:
        return None
    try:
        re.compile(pattern)  # on its own first, so an unbalanced ")" cannot escape the group below
        anchored = rf"\A{_HTTPS_ORIGIN}(?:{pattern})\Z"
        compiled = re.compile(anchored)
    except re.error as exc:
        log.warning("FRONTEND_ORIGIN_REGEX ignored: not a valid regular expression (%s)", exc)
        return None
    foreign = next((origin for origin in _FOREIGN_ORIGINS if compiled.fullmatch(origin)), None)
    if foreign is not None:
        log.warning("FRONTEND_ORIGIN_REGEX ignored: it also matches %s; name your own site in it", foreign)
        return None
    return anchored
