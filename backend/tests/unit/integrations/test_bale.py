"""Bale («بله») without a network: the client's Bale requests, platform text rendering, links,
command registration and the redaction of the secret in Bale webhook paths."""

import json
import logging
from typing import Any

import httpx
import pytest
from uvicorn.logging import AccessFormatter

from app.integrations.telegram.adapter import render_text, send_out_message
from app.integrations.telegram.client import FakeTelegramClient, TelegramClient, TelegramError
from app.integrations.telegram.commands import register_default_commands, register_owner_commands
from app.integrations.telegram.platforms import (
    as_platform,
    bot_link,
    is_invalid_token,
    localize,
    render_bale,
)
from app.runtime.contracts import Actor, OutMessage, RuntimeEvent
from app.runtime.texts import nav as nav_texts
from app.security.redact import REDACTED, RedactingFilter, redact

TOKEN = "123456789:abcdIuZmK5qNEm2A1BhUaAg7MPJv1O9KCcBQB2ro"
SECRET = "Zx0-secret_value_from_token_urlsafe_32bytes_A"


class Stub:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def client(self, platform: Any = "bale") -> TelegramClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self))
        return TelegramClient(TOKEN, platform=platform, http=http)

    def payload(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content or b"{}")


def ok(result: Any = True) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


# --- client --------------------------------------------------------------------------------------


async def test_bale_client_calls_tapi_bale_ai() -> None:
    stub = Stub(ok({"id": 123456789, "username": "shop_bot"}))
    client = stub.client()
    assert client.platform == "bale"
    assert await client.get_me() == {"id": 123456789, "username": "shop_bot"}
    url = stub.requests[0].url
    assert url.host == "tapi.bale.ai" and url.path == f"/bot{TOKEN}/getMe"
    assert TOKEN not in repr(client)


async def test_bale_set_webhook_sends_the_url_only() -> None:
    stub = Stub(ok(), ok())
    client = stub.client()
    await client.set_webhook("https://h.example/bale/b/s", None)
    assert stub.payload() == {"url": "https://h.example/bale/b/s"}
    await client.set_webhook("https://h.example/bale/b/s", "ignored", drop_pending_updates=False)
    assert stub.payload() == {"url": "https://h.example/bale/b/s"}  # no secret_token, no other keys


async def test_bale_requests_carry_no_undocumented_parameters() -> None:
    stub = Stub(ok(), ok([]), ok({"message_id": 5}), ok({"message_id": 5}))
    client = stub.client()
    await client.delete_webhook(drop_pending_updates=True)
    assert stub.payload() == {}
    await client.get_updates(offset=3, timeout=1, allowed_updates=["message"])
    assert stub.payload() == {"timeout": 1, "offset": 3}
    markup = {"inline_keyboard": [[{"text": "x", "callback_data": "nav:go:home"}]]}
    await client.send_message(42, "سلام", markup)
    assert stub.payload() == {"chat_id": 42, "text": "سلام", "reply_markup": markup}
    await client.edit_message_text(42, 5, "سلام")
    assert "parse_mode" not in stub.payload()


async def test_telegram_client_is_unchanged() -> None:
    stub = Stub(ok(), ok({"message_id": 1}))
    client = stub.client("telegram")
    await client.set_webhook("https://h.example/tg/b", SECRET)
    assert stub.requests[0].url.host == "api.telegram.org"
    assert stub.payload(0)["secret_token"] == SECRET and "allowed_updates" in stub.payload(0)
    await client.send_message(1, "x")
    assert stub.payload()["parse_mode"] == "HTML"


async def test_bale_invalid_token_is_a_403_error() -> None:
    body = {"ok": False, "error_code": 403, "description": "Bad Request: Token not found"}
    stub = Stub(httpx.Response(403, json=body))
    with pytest.raises(TelegramError) as caught:
        await stub.client().get_me()
    assert caught.value.error_code == 403 and TOKEN not in str(caught.value)
    assert is_invalid_token("bale", 403)
    assert not is_invalid_token("telegram", 403)  # Telegram's 403 is "bot was blocked", not the token
    assert is_invalid_token("telegram", 401) and is_invalid_token("bale", 404)


# --- rendering -----------------------------------------------------------------------------------


def test_telegram_rendering_is_html_escaping() -> None:
    assert render_text("<b>a & *b*</b>") == "&lt;b&gt;a &amp; *b*&lt;/b&gt;"
    assert render_text("<b>", "telegram") == "&lt;b&gt;"


@pytest.mark.parametrize(
    "text",
    [
        "[click](https://evil.example)",
        "*bold* _italic_ ~strike~ `code` ```block```",
        "نام: [بیا](tg://user?id=1) *ویژه*",
    ],
)
def test_bale_rendering_neutralises_markdown(text: str) -> None:
    rendered = render_text(text, "bale")
    assert not set("*_`[]~") & set(rendered)
    assert len(rendered) == len(text)  # one look-alike per control character, nothing else changes


def test_bale_rendering_keeps_everything_else_as_written() -> None:
    text = "سفارش <۱۲> & قیمت: ۱۲۰٬۰۰۰ تومان (کد A-7) https://example.com/a?b=1"
    assert render_text(text, "bale") == text  # no HTML escaping on Bale
    assert render_bale("a_b") == "a＿b"


def test_bale_rendering_caps_the_length() -> None:
    rendered = render_text("x" * 5000, "bale")
    assert len(rendered) == 4000 and rendered.endswith("…")


def test_fixed_texts_name_the_platform() -> None:
    assert "تلگرام" in nav_texts.COMING_SOON
    rendered = render_text(f"عنوان\n{nav_texts.COMING_SOON}", "bale")
    assert "تلگرام" not in rendered and "«بله»" in rendered
    assert render_text(nav_texts.COMING_SOON, "telegram") == nav_texts.COMING_SOON
    # user text that mentions Telegram is never rewritten
    assert render_text("کانال تلگرام ما", "bale") == "کانال تلگرام ما"
    assert localize("ارتباط با تلگرام", "bale") == "ارتباط با «بله»"
    assert localize("ارتباط با تلگرام", "telegram") == "ارتباط با تلگرام"


def test_links_and_platform_values() -> None:
    assert bot_link("bale", "shop_bot") == "https://ble.ir/shop_bot"
    assert bot_link("bale", "shop_bot", "owner_x") == "https://ble.ir/shop_bot?start=owner_x"
    assert bot_link("telegram", "shop_bot", "staff_y") == "https://t.me/shop_bot?start=staff_y"
    assert as_platform("bale") == "bale"
    assert as_platform(None) == "telegram" and as_platform("whatsapp") == "telegram"


async def test_send_out_message_renders_for_the_clients_platform() -> None:
    from datetime import UTC, datetime

    fake = FakeTelegramClient(platform="bale")
    event = RuntimeEvent(
        bot_id="b", env="live", actor=Actor(id="5", display_name="x"), kind="start", now=datetime.now(UTC)
    )
    await send_out_message(fake, OutMessage(to_actor_id="5", text="*hi* <b>"), event, None)
    assert fake.sent_to(5)[0]["text"] == "∗hi∗ <b>"


# --- commands ------------------------------------------------------------------------------------


async def test_no_command_menu_is_registered_on_bale() -> None:
    fake = FakeTelegramClient(platform="bale")
    await register_default_commands(fake)
    await register_owner_commands(fake, 7)
    assert fake.calls == []
    telegram = FakeTelegramClient()
    await register_default_commands(telegram)
    assert telegram.calls_to("setMyCommands")


# --- log redaction -------------------------------------------------------------------------------


def test_the_bale_webhook_secret_is_redacted() -> None:
    path = f"/bale/0b6c6d3e-1111-4c4c-9e9e-123456789abc/{SECRET}"
    assert redact(path) == f"/bale/0b6c6d3e-1111-4c4c-9e9e-123456789abc/{REDACTED}"
    assert redact(f"POST {path}?x=1 HTTP/1.1") == (
        f"POST /bale/0b6c6d3e-1111-4c4c-9e9e-123456789abc/{REDACTED}?x=1 HTTP/1.1"
    )
    assert redact("/tg/abc") == "/tg/abc"


def test_uvicorn_access_line_for_the_bale_webhook_hides_the_secret() -> None:
    formatter = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "POST", f"/bale/some-bot-id/{SECRET}", "1.1", 200),
        None,
    )
    RedactingFilter().filter(record)
    line = formatter.format(record)
    assert SECRET not in line
    assert line == f'10.0.0.1:5000 - "POST /bale/some-bot-id/{REDACTED} HTTP/1.1" 200 OK'
