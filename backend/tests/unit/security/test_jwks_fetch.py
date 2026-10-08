"""The default JWKS fetcher over real HTTP, against a loopback server (no external network).
Restored from the staging branch (b0125fc); only the module name changed."""

import json
import threading
import urllib.error
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.security.supabase_auth import JWKS_MAX_BYTES, AuthConfig, JwtVerifier, fetch_jwks
from tests.unit.security.tokens import EMAIL, mint, new_ec_key, public_jwk

Route = tuple[int, dict[str, str], bytes]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, dict[str, Route]]]:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    routes: dict[str, Route] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, headers, body = routes.get(self.path, (404, {}, b""))
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", routes
    finally:
        httpd.shutdown()
        httpd.server_close()


def json_route(document: Any) -> Route:
    return 200, {"Content-Type": "application/json"}, json.dumps(document).encode()


async def test_fetches_and_parses_the_document(server: tuple[str, dict[str, Route]]) -> None:
    base, routes = server
    routes["/jwks"] = json_route({"keys": []})
    assert await fetch_jwks(f"{base}/jwks") == {"keys": []}


async def test_redirects_are_refused(server: tuple[str, dict[str, Route]]) -> None:
    base, routes = server
    routes["/jwks"] = json_route({"keys": []})
    routes["/moved"] = (302, {"Location": f"{base}/jwks"}, b"")
    with pytest.raises(urllib.error.HTTPError):
        await fetch_jwks(f"{base}/moved")


async def test_error_status_and_oversized_or_non_json_bodies_fail(
    server: tuple[str, dict[str, Route]],
) -> None:
    base, routes = server
    routes["/error"] = (500, {}, b"{}")
    routes["/huge"] = (200, {}, b"{" + b" " * JWKS_MAX_BYTES + b"}")
    routes["/html"] = (200, {}, b"<html>")
    with pytest.raises(urllib.error.HTTPError):
        await fetch_jwks(f"{base}/error")
    with pytest.raises(ValueError, match="too large"):
        await fetch_jwks(f"{base}/huge")
    with pytest.raises(ValueError):
        await fetch_jwks(f"{base}/html")


async def test_verifier_with_the_default_fetcher(server: tuple[str, dict[str, Route]]) -> None:
    base, routes = server
    key = new_ec_key()
    routes["/auth/v1/.well-known/jwks.json"] = json_route({"keys": [public_jwk(key, "k1")]})
    # http:// is accepted for loopback hosts only (a local Supabase stack).
    verifier = JwtVerifier(AuthConfig(jwks_url=f"{base}/auth/v1/.well-known/jwks.json"))
    assert (await verifier.verify(mint(key, "ES256", kid="k1"))).email == EMAIL
