"""Telegram client against a stub transport: no network, token never leaks, retry rules."""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.integrations.telegram import client as client_module
from app.integrations.telegram.client import FakeTelegramClient, TelegramClient, TelegramError

TOKEN = "123456789:AAH-secretsecretsecretsecret_secret1234"


class Stub:
    """Scripted responses; records requests."""

    def __init__(self, *responses: Callable[[httpx.Request], httpx.Response] | httpx.Response | Exception):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item

    def client(self) -> TelegramClient:
        return TelegramClient(TOKEN, http=httpx.AsyncClient(transport=httpx.MockTransport(self)))


def ok(result: Any = True) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def failure(status: int, description: str, **parameters: Any) -> httpx.Response:
    body: dict[str, Any] = {"ok": False, "error_code": status, "description": description}
    if parameters:
        body["parameters"] = parameters
    return httpx.Response(status, json=body)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    return recorded


async def test_get_me_returns_result_and_calls_the_token_url() -> None:
    stub = Stub(ok({"id": 5, "username": "x_bot"}))
    assert await stub.client().get_me() == {"id": 5, "username": "x_bot"}
    assert stub.requests[0].url.path == f"/bot{TOKEN}/getMe"


async def test_set_webhook_payload() -> None:
    stub = Stub(ok())
    await stub.client().set_webhook("https://h.example/tg/1", "sec")
    body = json.loads(stub.requests[0].content)
    assert body == {
        "url": "https://h.example/tg/1",
        "secret_token": "sec",
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    }
    assert stub.requests[0].url.path.endswith("/setWebhook")


async def test_set_webhook_can_keep_pending_updates() -> None:
    stub = Stub(ok())
    await stub.client().set_webhook("https://h.example/tg/1", "sec", drop_pending_updates=False)
    assert json.loads(stub.requests[0].content)["drop_pending_updates"] is False


async def test_send_message_uses_html_and_inline_keyboard() -> None:
    stub = Stub(ok({"message_id": 9}))
    markup = {"inline_keyboard": [[{"text": "a", "callback_data": "x:y:"}]]}
    assert await stub.client().send_message(42, "hi", markup) == {"message_id": 9}
    body = json.loads(stub.requests[0].content)
    assert body == {"chat_id": 42, "text": "hi", "parse_mode": "HTML", "reply_markup": markup}


async def test_edit_and_answer_callback_payloads() -> None:
    stub = Stub(ok({"message_id": 3}), ok())
    c = stub.client()
    await c.edit_message_text(42, 3, "t")
    await c.answer_callback_query("cb1")
    assert json.loads(stub.requests[0].content) == {
        "chat_id": 42,
        "message_id": 3,
        "text": "t",
        "parse_mode": "HTML",
    }
    assert json.loads(stub.requests[1].content) == {"callback_query_id": "cb1"}
    assert stub.requests[1].url.path.endswith("/answerCallbackQuery")


async def test_api_error_carries_description_but_not_the_token(caplog: pytest.LogCaptureFixture) -> None:
    stub = Stub(failure(400, "Bad Request: chat not found"))
    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramError) as info:
        await stub.client().send_message(1, "x")
    exc = info.value
    assert exc.description == "Bad Request: chat not found"
    assert exc.error_code == 400 and not exc.network
    assert str(exc) == "sendMessage: Bad Request: chat not found"
    assert TOKEN not in str(exc) and TOKEN not in repr(exc) and TOKEN not in caplog.text
    assert len(stub.requests) == 1  # a 400 is not retried


async def test_unauthorized_token_is_a_401_error() -> None:
    with pytest.raises(TelegramError) as info:
        await Stub(failure(401, "Unauthorized")).client().get_me()
    assert info.value.error_code == 401


async def test_429_is_retried_once_after_retry_after(sleeps: list[float]) -> None:
    stub = Stub(failure(429, "Too Many Requests: retry after 2", retry_after=2), ok({"message_id": 1}))
    assert await stub.client().send_message(1, "x") == {"message_id": 1}
    assert sleeps == [2.0]
    assert len(stub.requests) == 2


async def test_second_429_is_raised(sleeps: list[float]) -> None:
    stub = Stub(
        failure(429, "Too Many Requests", retry_after=1), failure(429, "Too Many Requests", retry_after=1)
    )
    with pytest.raises(TelegramError) as info:
        await stub.client().send_message(1, "x")
    assert info.value.error_code == 429 and info.value.retry_after == 1.0
    assert len(stub.requests) == 2


async def test_long_retry_after_is_not_waited_for(sleeps: list[float]) -> None:
    stub = Stub(failure(429, "Too Many Requests", retry_after=600))
    with pytest.raises(TelegramError):
        await stub.client().send_message(1, "x")
    assert sleeps == [] and len(stub.requests) == 1


async def test_network_error_is_retried_once() -> None:
    stub = Stub(httpx.ConnectError("boom"), ok({"id": 1}))
    assert await stub.client().get_me() == {"id": 1}
    assert len(stub.requests) == 2


async def test_persistent_network_error_never_mentions_the_token(caplog: pytest.LogCaptureFixture) -> None:
    leaky = httpx.ConnectError(f"cannot connect to https://api.telegram.org/bot{TOKEN}/getMe")
    stub = Stub(leaky, leaky)
    with caplog.at_level(logging.DEBUG), pytest.raises(TelegramError) as info:
        await stub.client().get_me()
    exc = info.value
    assert exc.network is True
    assert TOKEN not in str(exc) and TOKEN not in repr(exc) and TOKEN not in caplog.text
    assert exc.__cause__ is None and exc.__suppress_context__  # the leaky original is not chained
    assert TOKEN not in repr(stub.client())


async def test_non_json_error_body_still_yields_a_typed_error() -> None:
    with pytest.raises(TelegramError) as info:
        await Stub(httpx.Response(502, text="<html>bad gateway</html>")).client().get_me()
    assert info.value.description == "HTTP 502"


async def test_fake_client_records_calls_and_can_fail() -> None:
    fake = FakeTelegramClient()
    assert fake.provider("tok") is fake and fake.tokens == ["tok"]
    await fake.send_message(7, "a")
    fake.fail_methods["sendMessage"] = "Forbidden: bot was blocked by the user"
    with pytest.raises(TelegramError, match="blocked"):
        await fake.send_message(7, "b")
    assert [c[0] for c in fake.calls] == ["sendMessage", "sendMessage"]
    assert [k["text"] for k in fake.sent_to(7)] == ["a", "b"]
