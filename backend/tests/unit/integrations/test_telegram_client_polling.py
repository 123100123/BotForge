"""Telegram client methods used by polling mode, against a stub transport (no network)."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.integrations.telegram import client as client_module
from app.integrations.telegram.client import (
    ALLOWED_UPDATES,
    FakeTelegramClient,
    TelegramClient,
    TelegramError,
)
from app.integrations.telegram.poller import Backoff

TOKEN = "123456789:AAH-secretsecretsecretsecret_secret1234"


class Stub:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.timeouts: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.timeouts.append(request.extensions.get("timeout", {}))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def client(self) -> TelegramClient:
        return TelegramClient(TOKEN, http=httpx.AsyncClient(transport=httpx.MockTransport(self)))


def ok(result: Any = True) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    return recorded


async def test_get_updates_payload_and_a_read_timeout_above_the_long_poll() -> None:
    stub = Stub(ok([{"update_id": 7, "message": {}}, "junk"]))
    updates = await stub.client().get_updates(offset=7, timeout=25, allowed_updates=ALLOWED_UPDATES)
    assert updates == [{"update_id": 7, "message": {}}]  # non-objects are dropped
    request = stub.requests[0]
    assert request.url.path == f"/bot{TOKEN}/getUpdates"
    assert json.loads(request.content) == {
        "timeout": 25,
        "allowed_updates": ["message", "callback_query"],
        "offset": 7,
    }
    assert stub.timeouts[0]["read"] > 25  # the request outlives Telegram's hold


async def test_get_updates_without_offset_leaves_it_out() -> None:
    stub = Stub(ok([]))
    assert await stub.client().get_updates(offset=None, timeout=25, allowed_updates=ALLOWED_UPDATES) == []
    assert "offset" not in json.loads(stub.requests[0].content)


@pytest.mark.parametrize(
    "response",
    [
        httpx.ConnectError("boom"),
        httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 3},
            },
        ),
    ],
)
async def test_get_updates_never_retries_by_itself(response: Any, no_sleep: list[float]) -> None:
    """The poller owns backoff and retry_after: the client raises the first failure."""
    stub = Stub(response)
    with pytest.raises(TelegramError) as raised:
        await stub.client().get_updates(offset=None, timeout=25, allowed_updates=ALLOWED_UPDATES)
    assert len(stub.requests) == 1 and no_sleep == []
    assert TOKEN not in str(raised.value)
    if isinstance(response, httpx.Response):
        assert raised.value.error_code == 429 and raised.value.retry_after == 3


async def test_delete_webhook_keeps_queued_updates_unless_asked() -> None:
    stub = Stub(ok(), ok())
    client = stub.client()
    await client.delete_webhook()
    await client.delete_webhook(drop_pending_updates=True)
    bodies = [json.loads(r.content) for r in stub.requests]
    assert bodies == [{"drop_pending_updates": False}, {"drop_pending_updates": True}]


async def test_other_calls_still_retry_once(no_sleep: list[float]) -> None:
    stub = Stub(httpx.ConnectError("boom"), ok({"message_id": 1}))
    await stub.client().send_message(1, "hi")
    assert len(stub.requests) == 2


async def test_fake_get_updates_confirms_by_offset_and_raises_scripted_errors() -> None:
    fake = FakeTelegramClient()
    fake.poll_wait = 0
    fake.push_updates({"update_id": 1}, {"update_id": 2})
    assert [u["update_id"] for u in await fake.get_updates(offset=None, timeout=25, allowed_updates=[])] == [
        1,
        2,
    ]
    assert [u["update_id"] for u in await fake.get_updates(offset=2, timeout=25, allowed_updates=[])] == [2]
    assert await fake.get_updates(offset=3, timeout=25, allowed_updates=[]) == []
    fake.get_updates_errors.append(TelegramError("getUpdates", "Conflict", error_code=409))
    with pytest.raises(TelegramError):
        await fake.get_updates(offset=3, timeout=25, allowed_updates=[])
    assert fake.calls_to("getUpdates")[0] == {"offset": None, "timeout": 25, "allowed_updates": []}


@pytest.mark.parametrize(
    ("rng", "expected"),
    [
        (lambda: 1.0, [1, 2, 4, 8, 16, 32, 60, 60]),
        (lambda: 0.0, [0.5, 1, 2, 4, 8, 16, 30, 30]),
    ],
)
def test_backoff_doubles_with_jitter_up_to_the_cap(rng: Callable[[], float], expected: list[float]) -> None:
    backoff = Backoff(rng)
    assert [backoff.next() for _ in expected] == expected
    backoff.reset()
    assert backoff.next() == expected[0]
