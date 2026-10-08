"""Telegram navigation end to end through the webhook with the fake client (U4): stable nav routes,
stale presses as NEW messages, sessions across revision activation, the error notice. Needs a
database."""

import copy
import uuid
from typing import Any

import httpx
import pytest

from app.db.models import Bot
from app.integrations.telegram.client import FakeTelegramClient
from app.revisions.service import activate, create_draft
from app.runtime.pg_store import PgStore
from app.runtime.runtime import BotRuntime
from app.runtime.texts import nav as nav_texts
from tests.integration.helpers import SessionFactory
from tests.integration.tg_helpers import (
    ALICE,
    CAP,
    Chat,
    LiveBot,
    callback_update,
    make_live_bot,
)

WORKSHOP = {
    "title": "کارگاه عکاسی",
    "description": "مقدماتی",
    "teacher": "سارا",
    "starts_at": "2027-11-01T10:00:00+03:30",
    "price": "۱۲۰۰۰",
}
PHONE = {"key": "phone", "label": "تلفن", "type": "phone"}


def form_spec(golden: dict[str, Any]) -> dict[str, Any]:
    """The golden spec whose booking asks one question, so a user can be caught mid-form."""
    spec = copy.deepcopy(golden)
    next(c for c in spec["capabilities"] if c["key"] == CAP)["form_fields"] = [PHONE]
    return spec


def with_flag(spec: dict[str, Any], key: str, **flags: Any) -> dict[str, Any]:
    out = copy.deepcopy(spec)
    next(c for c in out["capabilities"] if c["key"] == key).update(flags)
    return out


@pytest.fixture
async def bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, form_spec(golden_spec), owner_actor_id="900")


async def add_workshop(client: httpx.AsyncClient, bot: LiveBot) -> int:
    response = await client.post(f"/bots/{bot.id}/data/workshop", json={"data": WORKSHOP}, headers=ALICE)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def publish(session_factory: SessionFactory, bot: LiveBot, spec: dict[str, Any]) -> uuid.UUID:
    """Activate ``spec`` as the bot's next revision (what a capability toggle does)."""
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None
        revision = await create_draft(session, bot.id, spec=spec, parent_id=row.active_revision_id)
        await activate(session, revision.id)
        await session.commit()
        return revision.id


async def session_of(session_factory: SessionFactory, bot: LiveBot, actor: str) -> dict[str, Any] | None:
    async with session_factory() as session:
        return await PgStore(session, bot.id, "live").get_session(actor)


def edits(fake: FakeTelegramClient, user: int) -> list[dict[str, Any]]:
    return [k for n, k in fake.calls if n == "editMessageText" and k["chat_id"] == user]


async def test_nav_and_legacy_buttons_render_the_role_home(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    ali = Chat(tg_client, bot, fake_tg, 601)
    await ali.say("/start")
    home = [b["callback_data"] for b in ali.buttons()]
    assert home == ["nav:go:bkg", "nav:go:bkg.mine", "nav:go:info"]
    for data in ("nav:go:home", "menu:home:", "menu:open:about", "nav:go:info"):
        await ali.press(data)
        assert edits(fake_tg, 601), data  # navigation edits the pressed message
    await ali.press("nav:go:home")
    assert [b["callback_data"] for b in ali.buttons()] == home

    owner = Chat(tg_client, bot, fake_tg, 900)
    await owner.say("/start")
    assert owner.last_text().startswith("🧭 مدیریت ")
    assert owner.buttons()[-1] == {"text": nav_texts.CUSTOMER_VIEW, "callback_data": "nav:go:cust"}
    await owner.press("nav:go:cust")
    assert "nav:go:bkg" in [b["callback_data"] for b in owner.buttons()]


async def test_the_same_update_twice_is_processed_once(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    ali = Chat(tg_client, bot, fake_tg, 601)
    update = callback_update(424242, 601, "nav:go:bkg")
    assert (await ali.post(update)).status_code == 200
    assert (await ali.post(update)).status_code == 200
    assert len(fake_tg.calls_to("answerCallbackQuery")) == 1
    assert len(ali.shown()) == 1


@pytest.mark.parametrize("data", ["menu:open:gone_key", "nav:go:unknown", "nav:go:bkg~7", f"{CAP}:item:999"])
async def test_an_old_button_gets_a_new_stale_message_and_the_pressed_one_is_untouched(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, data: str
) -> None:
    ali = Chat(tg_client, bot, fake_tg, 601)
    await ali.press(data)
    assert edits(fake_tg, 601) == []
    (sent,) = [k for n, k in fake_tg.calls if n == "sendMessage"]
    assert sent["text"].startswith(nav_texts.STALE)
    assert fake_tg.calls_to("answerCallbackQuery")  # the press is answered


async def test_activation_between_render_and_click_keeps_forms_it_can_continue(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    item = await add_workshop(tg_client, bot)
    ali, sara = Chat(tg_client, bot, fake_tg, 601), Chat(tg_client, bot, fake_tg, 602)
    await sara.say("/start")  # sara's home is rendered with «دربارهٔ ما»
    assert "nav:go:info" in [b["callback_data"] for b in sara.buttons()]
    await ali.press(f"{CAP}:book:{item}")  # ali is asked for a phone number
    assert (await session_of(session_factory, bot, "601") or {}).get("capability") == CAP

    # the owner turns "info" off: a new revision is activated while both chats are open
    await publish(session_factory, bot, with_flag(form_spec(golden_spec), "info", enabled=False))
    assert (await session_of(session_factory, bot, "601") or {}).get("capability") == CAP  # survived
    await ali.say("09121234567")
    assert "ثبت" in ali.last_text()  # the booking went through
    assert await session_of(session_factory, bot, "601") is None

    before = len(sara.shown())
    await sara.press("nav:go:info")  # the entry sara still sees is gone
    assert edits(fake_tg, 602) == []
    assert len(sara.shown()) == before + 1
    assert sara.last_text().startswith(nav_texts.STALE)
    assert "nav:go:info" not in [b["callback_data"] for b in sara.buttons()]

    # a form of a capability the next revision disables is dropped
    reza = Chat(tg_client, bot, fake_tg, 603)
    await reza.press(f"{CAP}:book:{item}")
    assert await session_of(session_factory, bot, "603") is not None
    await publish(session_factory, bot, with_flag(form_spec(golden_spec), CAP, enabled=False))
    assert await session_of(session_factory, bot, "603") is None


async def test_a_runtime_failure_is_answered_and_explained(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(self: Any, *args: Any) -> Any:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(BotRuntime, "handle", boom)
    ali = Chat(tg_client, bot, fake_tg, 601)
    assert (await ali.press("nav:go:bkg")).status_code == 200  # process_update logs and drops it
    assert len(fake_tg.calls_to("answerCallbackQuery")) == 1
    assert ali.last_text() == nav_texts.ERROR
    assert ali.buttons() == [
        {"text": nav_texts.RETRY, "callback_data": "nav:go:bkg"},
        {"text": nav_texts.HOME, "callback_data": "nav:go:home"},
    ]
    assert edits(fake_tg, 601) == []


async def test_bot_commands_through_the_webhook(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    ali = Chat(tg_client, bot, fake_tg, 601)
    await ali.say("/start")
    home = [b["callback_data"] for b in ali.buttons()]
    for command in ("/menu", "/menu@workshop_test_bot", "/panel"):  # a customer has no panel: their home
        await ali.say(command)
        assert [b["callback_data"] for b in ali.buttons()] == home, command
    assert edits(fake_tg, 601) == []  # commands send new messages

    await ali.say("/help@workshop_test_bot")
    assert ali.last_text().startswith("❓")
    assert [b["callback_data"] for b in ali.buttons()] == ["nav:go:home"]

    owner = Chat(tg_client, bot, fake_tg, 900)
    await owner.say("/panel")
    assert owner.last_text().startswith("🧭 مدیریت ")
    await owner.say("/menu")
    assert owner.last_text().startswith("🧭 مدیریت ")
