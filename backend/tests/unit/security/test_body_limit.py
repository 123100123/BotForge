"""Request bodies are capped before authentication runs (FastAPI parses a body before dependencies).

Driven straight through ASGI so the test can count how much of the body the application pulled.
No database: every request here is answered before a session would be opened.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.main import create_app
from app.security.body_limit import MAX_BODY_BYTES

CHUNK = 64 * 1024
ROUTES_WITH_BODIES = [
    "/bots",
    f"/bots/{uuid.uuid4()}/simulator/events",
    f"/bots/{uuid.uuid4()}/telegram/connect",
]


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def post_raw(path: str, total: int, *, declare_length: bool) -> tuple[int, int, bytes]:
    """POST ``total`` bytes without any credentials. Returns (status, bytes pulled, response body)."""
    app = create_app()
    remaining, pulled = total, 0
    status: list[int] = []
    body = bytearray()

    async def receive() -> dict[str, Any]:
        nonlocal remaining, pulled
        if remaining <= 0:
            return {"type": "http.disconnect"}
        size = min(CHUNK, remaining)
        remaining -= size
        pulled += size
        return {"type": "http.request", "body": b"x" * size, "more_body": remaining > 0}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    headers = [(b"host", b"test"), (b"content-type", b"application/json")]
    if declare_length:
        headers.append((b"content-length", str(total).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("203.0.113.9", 4000),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    return status[0], pulled, bytes(body)


@pytest.mark.parametrize("path", ROUTES_WITH_BODIES)
async def test_a_streamed_oversized_body_is_cut_off_before_authentication(path: str) -> None:
    status, pulled, body = await post_raw(path, 32 * MAX_BODY_BYTES, declare_length=False)
    assert status == 413
    assert pulled <= MAX_BODY_BYTES + CHUNK  # not the 32 MiB that were offered
    assert b"http_413" in body  # the project's error body, not a validation error or a 401


@pytest.mark.parametrize("path", ROUTES_WITH_BODIES)
async def test_a_declared_oversized_body_is_refused_without_reading_it(path: str) -> None:
    status, pulled, _ = await post_raw(path, 32 * MAX_BODY_BYTES, declare_length=True)
    assert status == 413
    assert pulled == 0


async def test_a_body_at_the_limit_still_reaches_authentication() -> None:
    padding = b"a" * (MAX_BODY_BYTES - len(b'{"name": ""}'))
    content = b'{"name": "' + padding + b'"}'
    assert len(content) == MAX_BODY_BYTES
    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/bots", content=content, headers={"content-type": "application/json"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


async def test_the_webhook_keeps_its_own_limit_and_ordering() -> None:
    # Not cut off here: the webhook checks its secret first and limits the body itself (it then
    # fails for want of a database in this test, which proves the request got past this layer).
    status, pulled, _ = await post_raw(f"/tg/{uuid.uuid4()}", 2 * MAX_BODY_BYTES, declare_length=True)
    assert status == 503
    assert pulled == 0
