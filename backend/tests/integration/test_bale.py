"""Bale («بله») bots: connect, links, per-platform uniqueness and the Bale webhook, with the fake
client (never the real Bale API). Needs a database."""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import Bot, TgUpdate
from app.integrations.telegram import texts
from app.integrations.telegram.client import FakeTelegramClient, TelegramError
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory
from tests.integration.tg_helpers import (
    ALICE,
    SECRET_HEADER,
    LiveBot,
    callback_update,
    make_live_bot,
    message_update,
    new_token,
)

BALE_TOKEN = "123456789:abcdIuZmK5qNEm2A1BhUaAg7MPJv1O9KCcBQB2ro"  # the shape Bale's BotFather issues


async def stored(session_factory: SessionFactory, bot_id: Any) -> Bot:
    async with session_factory() as session:
        row = (await session.execute(select(Bot).where(Bot.id == bot_id))).scalar_one()
        session.expunge(row)
        return row


async def connect(
    client: httpx.AsyncClient, bot_id: Any, token: str = BALE_TOKEN, platform: str = "bale"
) -> httpx.Response:
    return await client.post(
        f"/bots/{bot_id}/telegram/connect", json={"token": token, "platform": platform}, headers=ALICE
    )


async def updates(session_factory: SessionFactory, bot_id: Any) -> int:
    async with session_factory() as session:
        query = select(func.count()).select_from(TgUpdate).where(TgUpdate.bot_id == bot_id)
        return (await session.execute(query)).scalar_one()


# --- connect -----------------------------------------------------------------------------------


async def test_connect_bale_registers_the_url_only_webhook_and_ble_ir_links(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice")
    response = await connect(tg_client, bot_id)
    assert response.status_code == 200, response.text
    body = response.json()
    row = await stored(session_factory, bot_id)
    assert body["platform"] == "bale" and body["connected"] is True
    assert body["bot_link"] == "https://ble.ir/workshop_test_bot"
    assert body["owner_link"] == f"https://ble.ir/workshop_test_bot?start=owner_{row.owner_link_code}"
    assert row.platform == "bale" and row.tg_bot_id == fake_tg.bot_id and row.status == "live"

    assert fake_tg.platforms and set(fake_tg.platforms) == {"bale"}
    [hook] = fake_tg.calls_to("setWebhook")
    # the secret is in the path, and no secret_token is handed to setWebhook
    assert hook["url"] == f"https://bots.example.test/bale/{bot_id}/{row.tg_webhook_secret}"
    assert hook["secret_token"] is None
    # Telegram-only steps are skipped: other-server checks and the command menu
    for method in ("getWebhookInfo", "getUpdates", "setMyCommands", "setChatMenuButton"):
        assert fake_tg.calls_to(method) == [], method
    # the secret never appears in the response
    assert row.tg_webhook_secret not in response.text

    payload = (await tg_client.get(f"/bots/{bot_id}", headers=ALICE)).json()
    assert payload["platform"] == "bale"


async def test_connect_without_platform_stays_telegram(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice")
    _, token = new_token()
    response = await tg_client.post(f"/bots/{bot_id}/telegram/connect", json={"token": token}, headers=ALICE)
    assert response.status_code == 200, response.text
    assert response.json()["platform"] == "telegram"
    assert response.json()["bot_link"] == "https://t.me/workshop_test_bot"
    assert set(fake_tg.platforms) == {"telegram"}
    [hook] = fake_tg.calls_to("setWebhook")
    assert hook["url"].endswith(f"/tg/{bot_id}") and hook["secret_token"]


async def test_bale_403_token_not_found_is_an_invalid_token(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice")
    fake_tg.get_me_error = TelegramError("getMe", "Bad Request: Token not found", error_code=403)
    response = await connect(tg_client, bot_id)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_token"
    assert fake_tg.calls_to("setWebhook") == []


async def test_bale_errors_name_bale_not_telegram(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice")
    fake_tg.fail_methods["setWebhook"] = "Bad Request: bad webhook"
    response = await connect(tg_client, bot_id)
    assert response.status_code == 502
    message = response.json()["error"]["message"]
    assert "«بله»" in message and "تلگرام" not in message


async def test_bale_refuses_a_public_url_on_another_port(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient, monkeypatch: Any
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://bots.example.test:8443")
    get_settings.cache_clear()
    bot_id, _ = await make_bot("alice")
    response = await connect(tg_client, bot_id)
    assert response.status_code == 503 and response.json()["error"]["code"] == "public_url_missing"
    assert fake_tg.calls == []


async def test_messenger_bot_ids_are_unique_per_platform(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    telegram_bot, _ = await make_bot("alice")
    _, token = new_token()
    assert (await connect(tg_client, telegram_bot, token, "telegram")).status_code == 200
    # the same numeric id on Bale belongs to a different bot: allowed
    bale_bot, _ = await make_bot("alice")
    assert (await connect(tg_client, bale_bot)).status_code == 200
    # a second Bale bot with that id is refused
    other, _ = await make_bot("alice")
    response = await connect(tg_client, other)
    assert response.status_code == 409 and response.json()["error"]["code"] == "telegram_bot_in_use"
    assert "«بله»" in response.json()["error"]["message"]
    assert (await stored(session_factory, telegram_bot)).platform == "telegram"
    assert (await stored(session_factory, bale_bot)).platform == "bale"


async def test_switching_platform_drops_the_previous_webhook_on_its_own_platform(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice")
    _, token = new_token()
    assert (await connect(tg_client, bot_id, token, "telegram")).status_code == 200
    fake_tg.calls.clear()
    fake_tg.platforms.clear()
    assert (await connect(tg_client, bot_id)).status_code == 200  # same fake id, now on Bale
    assert fake_tg.calls_to("deleteWebhook")  # the Telegram webhook is removed
    assert fake_tg.platforms[-1] == "telegram"  # ... through a Telegram client


# --- the Bale webhook --------------------------------------------------------------------------


@pytest.fixture
async def bale_bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, golden_spec, platform="bale")


async def test_bale_webhook_with_the_secret_answers_in_plain_text(
    tg_client: httpx.AsyncClient,
    bale_bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    response = await tg_client.post(
        f"/bale/{bale_bot.id}/{bale_bot.secret}", json=message_update(1, 501, "/start")
    )
    assert response.status_code == 200
    sent = fake_tg.sent_to(501)
    assert sent, fake_tg.calls
    assert set(fake_tg.platforms) == {"bale"}
    assert fake_tg.platform == "bale"
    # Bale text is never HTML-escaped, and it carries no Markdown control characters
    for message in sent:
        assert "&lt;" not in message["text"] and "&amp;" not in message["text"]
        assert not set("*_`[]~") & set(message["text"])
    assert await updates(session_factory, bale_bot.id) == 1

    # a button press works through the same route
    data = sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    response = await tg_client.post(
        f"/bale/{bale_bot.id}/{bale_bot.secret}", json=callback_update(2, 501, data)
    )
    assert response.status_code == 200
    assert fake_tg.calls_to("answerCallbackQuery")


async def test_bale_webhook_wrong_secret_is_403_and_nothing_happens(
    tg_client: httpx.AsyncClient,
    bale_bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    update = message_update(1, 501, "/start")
    for secret in ("wrong", bale_bot.secret + "x", bale_bot.secret[:-1], "%D9%85"):
        response = await tg_client.post(f"/bale/{bale_bot.id}/{secret}", json=update)
        assert response.status_code == 403, secret
    assert fake_tg.calls == []
    assert await updates(session_factory, bale_bot.id) == 0


async def test_each_webhook_route_serves_only_its_platform(
    tg_client: httpx.AsyncClient,
    bale_bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    update = message_update(1, 501, "/start")
    # a Bale bot is not reachable through the Telegram route, even with its secret in the header
    response = await tg_client.post(
        f"/tg/{bale_bot.id}", json=update, headers={SECRET_HEADER: bale_bot.secret}
    )
    assert response.status_code == 404
    # and a Telegram bot is not reachable through the Bale route
    telegram_bot = await make_live_bot(session_factory, golden_spec)
    response = await tg_client.post(f"/bale/{telegram_bot.id}/{telegram_bot.secret}", json=update)
    assert response.status_code == 404
    assert fake_tg.calls == []


async def test_bale_webhook_drops_a_duplicate_delivery(
    tg_client: httpx.AsyncClient,
    bale_bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    update = message_update(7, 501, "/start")
    url = f"/bale/{bale_bot.id}/{bale_bot.secret}"
    assert (await tg_client.post(url, json=update)).status_code == 200
    first = len(fake_tg.calls)
    assert first > 0
    assert (await tg_client.post(url, json=update)).status_code == 200
    assert len(fake_tg.calls) == first
    assert await updates(session_factory, bale_bot.id) == 1


async def test_bale_owner_link_and_staff_link_use_ble_ir(
    tg_client: httpx.AsyncClient,
    bale_bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    url = f"/bale/{bale_bot.id}/{bale_bot.secret}"
    response = await tg_client.post(
        url, json=message_update(1, 777, f"/start owner_{bale_bot.owner_link_code}")
    )
    assert response.status_code == 200
    assert (await stored(session_factory, bale_bot.id)).owner_actor_id == "777"
    assert fake_tg.sent_to(777)[0]["text"] == texts.OWNER_LINKED
    assert fake_tg.calls_to("setMyCommands") == []  # no command menu on Bale

    status = (await tg_client.get(f"/bots/{bale_bot.id}/telegram", headers=ALICE)).json()
    assert status["platform"] == "bale" and status["owner_linked"] is True
    assert status["bot_link"] == "https://ble.ir/workshop_test_bot"

    team = await tg_client.post(f"/bots/{bale_bot.id}/team/staff-link", headers=ALICE)
    assert team.status_code == 200, team.text
    assert team.json()["staff_link"].startswith("https://ble.ir/workshop_test_bot?start=staff_")


async def test_bale_bot_without_a_revision_is_not_ready(
    tg_client: httpx.AsyncClient,
    session_factory: SessionFactory,
    fake_tg: FakeTelegramClient,
    tg_env: None,
) -> None:
    bot = await make_live_bot(session_factory, None, platform="bale")  # no active revision
    response = await tg_client.post(f"/bale/{bot.id}/{bot.secret}", json=message_update(1, 501, "hi"))
    assert response.status_code == 200
    assert fake_tg.sent_to(501)[-1]["text"] == texts.NOT_READY
