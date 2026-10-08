"""Telegram connect / status / disconnect endpoints with the fake client. Needs a database."""

import logging
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Bot
from app.integrations.telegram.client import FakeTelegramClient, TelegramError
from app.security.crypto import decrypt_token
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory
from tests.integration.tg_helpers import ALICE, make_live_bot, new_token

BOB = {"X-Test-User": "bob"}


async def stored(session_factory: SessionFactory, bot_id: Any) -> Bot:
    async with session_factory() as session:
        row = (await session.execute(select(Bot).where(Bot.id == bot_id))).scalar_one()
        session.expunge(row)
        return row


async def connect(
    client: httpx.AsyncClient, bot_id: Any, token: str, headers: dict = ALICE
) -> httpx.Response:
    return await client.post(f"/bots/{bot_id}/telegram/connect", json={"token": token}, headers=headers)


async def test_status_of_an_unconnected_bot(tg_client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    response = await tg_client.get(f"/bots/{bot_id}/telegram", headers=ALICE)
    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "username": None,
        "bot_link": None,
        "owner_linked": False,
        "owner_link": None,
        "last_error": None,
    }


async def test_connect_stores_encrypted_token_and_registers_the_webhook(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice")  # has an active revision
    _, token = new_token()
    response = await connect(tg_client, bot_id, token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connected"] is True and body["username"] == "workshop_test_bot"
    assert body["bot_link"] == "https://t.me/workshop_test_bot"
    assert body["owner_linked"] is False

    row = await stored(session_factory, bot_id)
    assert body["owner_link"] == f"https://t.me/workshop_test_bot?start=owner_{row.owner_link_code}"
    assert row.owner_link_code
    # stored encrypted, never in plaintext
    assert row.tg_token_enc and token not in row.tg_token_enc
    assert decrypt_token(row.tg_token_enc) == token
    assert row.tg_bot_id == fake_tg.bot_id and row.tg_username == "workshop_test_bot"
    assert row.tg_webhook_secret and len(row.tg_webhook_secret) >= 32
    assert row.status == "live"  # active revision + token

    # the token and the secret never appear in the response
    assert token not in response.text and row.tg_webhook_secret not in response.text
    assert row.tg_token_enc not in response.text

    # getMe happened with the token, then setWebhook with url + secret
    assert fake_tg.tokens == [token]
    [hook] = fake_tg.calls_to("setWebhook")
    assert hook["url"] == f"https://bots.example.test/tg/{bot_id}"
    assert hook["secret_token"] == row.tg_webhook_secret
    assert hook["drop_pending_updates"] is True  # a fresh connect must not replay old updates

    again = await tg_client.get(f"/bots/{bot_id}/telegram", headers=ALICE)
    assert again.json() == body


async def test_connect_without_active_revision_leaves_the_bot_in_draft(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200
    assert (await stored(session_factory, bot_id)).status == "draft"


async def test_telegram_bot_already_used_by_another_bot_is_refused(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    first, _ = await make_bot("alice", active=False)
    second, _ = await make_bot("bob", active=False)
    assert (await connect(tg_client, first, new_token()[1])).status_code == 200
    response = await connect(tg_client, second, new_token()[1], BOB)  # same fake Telegram bot id
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "telegram_bot_in_use" and "قبلاً" in error["message"]
    assert error["message"] == (
        "ربات تلگرام @workshop_test_bot قبلاً به کسب‌وکار دیگری در این سامانه وصل شده است. "
        "اول آن را از آنجا جدا کنید."
    )
    row = await stored(session_factory, second)
    assert row.tg_token_enc is None and row.tg_bot_id is None and row.tg_webhook_secret is None
    assert len(fake_tg.calls_to("setWebhook")) == 1  # only the first bot registered a webhook
    first_row = await stored(session_factory, first)  # the first business is unaffected
    assert first_row.tg_bot_id == fake_tg.bot_id and first_row.tg_token_enc and first_row.status == "draft"
    assert first_row.tg_last_error is None


async def test_reconnecting_the_same_bot_is_allowed(tg_client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        "12345:short",
        "abc:" + "A" * 30,
        "۱۲۳۴۵۶۷۸۹:" + "A" * 35,  # non-ASCII digits
        "123456789:" + "A" * 29,  # shorter than any real token (and than the log redaction pattern)
    ],
)
async def test_malformed_token_is_rejected_without_calling_telegram(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient, token: str
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    response = await connect(tg_client, bot_id, token)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_token"
    assert fake_tg.calls == []


async def test_token_rejected_by_telegram(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.get_me_error = TelegramError("getMe", "Unauthorized", error_code=401)
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_token"
    assert (await stored(session_factory, bot_id)).tg_token_enc is None


async def test_telegram_unreachable(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.get_me_error = TelegramError("getMe", "network error (ConnectError)", network=True)
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "telegram_unreachable"


async def test_set_webhook_failure_leaves_nothing_stored(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.fail_methods["setWebhook"] = "Bad Request: bad webhook: HTTPS url must be provided for webhook"
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 502 and response.json()["error"]["code"] == "telegram_error"
    row = await stored(session_factory, bot_id)
    assert row.tg_token_enc is None and row.tg_bot_id is None and row.tg_webhook_secret is None


@pytest.mark.parametrize("url", ["", "http://bots.example.test", "https://localhost:8000"])
async def test_public_base_url_must_be_configured(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", url)
    get_settings.cache_clear()
    bot_id, _ = await make_bot("alice", active=False)
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 503 and response.json()["error"]["code"] == "public_url_missing"
    assert fake_tg.calls == []


async def test_missing_encryption_key_fails_closed(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
) -> None:
    monkeypatch.setenv("TOKEN_ENC_KEY", "")
    get_settings.cache_clear()
    bot_id, _ = await make_bot("alice", active=False)
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 503 and response.json()["error"]["code"] == "server_misconfigured"
    assert (await stored(session_factory, bot_id)).tg_token_enc is None


async def test_connect_does_not_log_the_token(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, caplog: pytest.LogCaptureFixture
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    _, token = new_token()
    with caplog.at_level(logging.DEBUG):
        assert (await connect(tg_client, bot_id, token)).status_code == 200
    assert token not in caplog.text


async def test_disconnect_clears_everything_and_deletes_the_webhook(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice")
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200
    async with session_factory() as session:  # the owner has linked their Telegram account
        linked = await session.get(Bot, bot_id)
        assert linked is not None
        linked.owner_actor_id = "900"
        await session.commit()
    response = await tg_client.delete(f"/bots/{bot_id}/telegram", headers=ALICE)
    assert response.status_code == 200 and response.json()["connected"] is False
    assert response.json()["username"] is None and response.json()["bot_link"] is None
    assert response.json()["owner_linked"] is False and response.json()["owner_link"] is None
    row = await stored(session_factory, bot_id)
    assert (row.tg_token_enc, row.tg_webhook_secret, row.tg_username, row.tg_bot_id) == (None,) * 4
    assert (row.owner_actor_id, row.owner_link_code) == (None, None)  # unlinked, code revoked
    assert row.status == "draft"
    assert len(fake_tg.calls_to("deleteWebhook")) == 1


async def test_disconnect_succeeds_even_if_telegram_fails(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200
    fake_tg.fail_methods["deleteWebhook"] = "Unauthorized"
    response = await tg_client.delete(f"/bots/{bot_id}/telegram", headers=ALICE)
    assert response.status_code == 200
    assert (await stored(session_factory, bot_id)).tg_token_enc is None


async def test_disconnected_bot_can_be_connected_by_another_bot(
    tg_client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    first, _ = await make_bot("alice", active=False)
    second, _ = await make_bot("bob", active=False)
    assert (await connect(tg_client, first, new_token()[1])).status_code == 200
    await tg_client.delete(f"/bots/{first}/telegram", headers=ALICE)
    assert (await connect(tg_client, second, new_token()[1], BOB)).status_code == 200


async def test_another_owners_bot_is_a_404(tg_client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    assert (await tg_client.get(f"/bots/{bot_id}/telegram", headers=BOB)).status_code == 404
    assert (await connect(tg_client, bot_id, new_token()[1], BOB)).status_code == 404
    assert (await tg_client.delete(f"/bots/{bot_id}/telegram", headers=BOB)).status_code == 404


# --- one Telegram bot, one BotForge bot, across servers ---------------------------------------------

ELSEWHERE = "telegram_bot_in_use_elsewhere"
COMPETITOR = TelegramError(
    "getUpdates",
    "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running",
    error_code=409,
)


async def assert_nothing_stored(
    session_factory: SessionFactory, bot_id: Any, fake_tg: FakeTelegramClient
) -> None:
    row = await stored(session_factory, bot_id)
    assert row.tg_token_enc is None and row.tg_bot_id is None and row.tg_webhook_secret is None
    assert fake_tg.calls_to("setWebhook") == [] and fake_tg.calls_to("deleteWebhook") == []


async def test_a_webhook_of_another_server_refuses_the_connection(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.webhook_url = "https://other-server.example.test/tg/0f0f0f0f-0000-0000-0000-000000000000"
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == ELSEWHERE and "سرور دیگری" in error["message"]
    assert fake_tg.calls_to("getUpdates") == []  # no probe: with a webhook set nobody can be polling
    await assert_nothing_stored(session_factory, bot_id, fake_tg)


async def test_a_webhook_of_this_server_is_a_reconnect_and_needs_no_probe(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.webhook_url = f"https://bots.example.test/tg/{bot_id}"
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200
    assert fake_tg.calls_to("getUpdates") == [] and len(fake_tg.calls_to("setWebhook")) == 1


async def test_a_competing_poller_found_by_the_probe_refuses_the_connection(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.get_updates_errors.append(COMPETITOR)
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 409 and response.json()["error"]["code"] == ELSEWHERE
    assert response.json()["error"]["message"] == (
        "این ربات تلگرام همین حالا به سرور دیگری وصل است (یک نسخهٔ دیگر BotForge یا برنامهٔ دیگری). "
        "اول آن را از آنجا جدا کنید، بعد دوباره امتحان کنید."
    )
    # the probe never confirms anything: no offset, one update at most
    [probe] = fake_tg.calls_to("getUpdates")
    assert probe["offset"] is None and probe["limit"] == 1 and probe["timeout"] == 6
    await assert_nothing_stored(session_factory, bot_id, fake_tg)


async def test_a_clean_token_connects_after_a_probe_that_finds_nobody(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.push_updates({"update_id": 5})  # pending updates are seen by the probe and left alone
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200
    names = [name for name, _ in fake_tg.calls]
    assert names == ["getMe", "getWebhookInfo", "getUpdates", "setWebhook"]
    assert fake_tg.pending_updates == [{"update_id": 5}]


async def test_other_probe_failures_do_not_block_the_connection(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.get_updates_errors.append(TelegramError("getUpdates", "Bad Gateway", error_code=502))
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200


async def test_a_webhook_info_failure_is_reported(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.fail_methods["getWebhookInfo"] = "Bad Request"
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 502 and response.json()["error"]["code"] == "telegram_error"
    await assert_nothing_stored(session_factory, bot_id, fake_tg)


async def test_reconnecting_the_same_token_here_is_not_a_false_positive(
    tg_client: httpx.AsyncClient, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    """This server's own poller holds the token: a probe would see it as a competitor."""
    bot = await make_live_bot(session_factory, None)
    fake_tg.bot_id = bot.tg_bot_id
    fake_tg.get_updates_errors.append(COMPETITOR)  # what our own poller would cause
    response = await connect(tg_client, bot.id, bot.token)
    assert response.status_code == 200, response.text
    assert fake_tg.calls_to("getUpdates") == []  # no probe
    assert fake_tg.get_updates_errors == [COMPETITOR]
    assert (await stored(session_factory, bot.id)).tg_bot_id == bot.tg_bot_id


async def test_the_same_telegram_bot_with_a_new_token_is_probed(
    tg_client: httpx.AsyncClient, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    bot = await make_live_bot(session_factory, None)
    fake_tg.bot_id = bot.tg_bot_id
    fake_tg.get_updates_errors.append(COMPETITOR)
    response = await connect(tg_client, bot.id, new_token()[1])
    assert response.status_code == 409 and response.json()["error"]["code"] == ELSEWHERE
    assert len(fake_tg.calls_to("getUpdates")) == 1


async def test_polling_mode_refuses_a_foreign_webhook_without_a_public_url(
    monkeypatch: pytest.MonkeyPatch,
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    monkeypatch.setenv("TELEGRAM_MODE", "polling")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost")
    get_settings.cache_clear()
    bot_id, _ = await make_bot("alice", active=False)
    fake_tg.webhook_url = "https://other-server.example.test/tg/x"
    response = await connect(tg_client, bot_id, new_token()[1])
    assert response.status_code == 409 and response.json()["error"]["code"] == ELSEWHERE
    await assert_nothing_stored(session_factory, bot_id, fake_tg)
    fake_tg.webhook_url = ""  # no webhook and no poller: polling-mode connect works
    assert (await connect(tg_client, bot_id, new_token()[1])).status_code == 200
