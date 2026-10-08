"""The Telegram webhook end to end with the fake client. Needs a database."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, RecordRow, TgUpdate
from app.integrations.telegram import texts
from app.integrations.telegram.client import FakeTelegramClient
from tests.integration.helpers import SessionFactory, user_id
from tests.integration.tg_helpers import (
    ALICE,
    CAP,
    SECRET_HEADER,
    Chat,
    LiveBot,
    capacity_spec,
    make_live_bot,
    message_update,
)

WORKSHOP = {
    "title": "کارگاه عکاسی",
    "description": "مقدماتی",
    "teacher": "سارا",
    "starts_at": "2027-11-01T10:00:00+03:30",
    "price": "۱۲۰۰۰",
}


@pytest.fixture
async def bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    """A live bot with the golden spec at capacity 1, so waitlisting needs only two users."""
    return await make_live_bot(session_factory, capacity_spec(golden_spec, 1))


async def add_workshop(client: httpx.AsyncClient, bot: LiveBot, title: str = "کارگاه عکاسی") -> int:
    response = await client.post(
        f"/bots/{bot.id}/data/workshop", json={"data": {**WORKSHOP, "title": title}}, headers=ALICE
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def count(session_factory: SessionFactory, model: Any, bot_id: Any) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(model).where(model.bot_id == bot_id))
        ).scalar_one()


async def load_bot(session_factory: SessionFactory, bot_id: Any) -> Bot:
    async with session_factory() as session:
        row = (await session.execute(select(Bot).where(Bot.id == bot_id))).scalar_one()
        session.expunge(row)
        return row


# --- authentication and routing ----------------------------------------------------------------


async def test_wrong_or_missing_secret_is_403_and_nothing_happens(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    update = message_update(1, 501, "/start")
    for headers in ({}, {SECRET_HEADER: "wrong"}, {SECRET_HEADER: ""}, {SECRET_HEADER: bot.secret + "x"}):
        response = await tg_client.post(f"/tg/{bot.id}", json=update, headers=headers)
        assert response.status_code == 403, headers
        assert response.json()["error"]["code"] == "forbidden"
    assert fake_tg.calls == []
    assert await count(session_factory, TgUpdate, bot.id) == 0


async def test_non_ascii_secret_header_is_403_not_500(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    response = await tg_client.post(
        f"/tg/{bot.id}",
        content=b"{}",
        headers={SECRET_HEADER.encode(): "سر".encode(), b"content-type": b"application/json"},
    )
    assert response.status_code == 403


async def test_unknown_bot_and_invalid_id_are_404(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    unknown = await tg_client.post(
        "/tg/5ba1b6a6-3b5c-4f0e-9d1b-000000000000", json={}, headers={SECRET_HEADER: bot.secret}
    )
    invalid = await tg_client.post("/tg/not-a-uuid", json={}, headers={SECRET_HEADER: bot.secret})
    assert unknown.status_code == invalid.status_code == 404
    assert unknown.json() == invalid.json()
    assert unknown.json()["error"]["code"] == "bot_not_found"


async def test_a_bot_without_a_secret_rejects_everything(
    tg_client: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    owner_id = await user_id(session_factory, "alice")
    async with session_factory() as session:
        disconnected = Bot(owner_id=owner_id, name="x")
        session.add(disconnected)
        await session.commit()
        bot_id = disconnected.id
    for secret in ("", "anything"):
        response = await tg_client.post(f"/tg/{bot_id}", json={}, headers={SECRET_HEADER: secret})
        assert response.status_code == 403


async def test_oversized_body_is_rejected_after_the_secret_check(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    big = json.dumps({"update_id": 1, "pad": "x" * (1024 * 1024 + 10)}).encode()
    headers = {SECRET_HEADER: bot.secret, "content-type": "application/json"}
    response = await tg_client.post(f"/tg/{bot.id}", content=big, headers=headers)
    assert response.status_code == 413 and response.json()["error"]["code"] == "body_too_large"

    async def chunks() -> Any:  # no Content-Length: the stream itself is measured
        for i in range(0, len(big), 65536):
            yield big[i : i + 65536]

    streamed = await tg_client.post(f"/tg/{bot.id}", content=chunks(), headers=headers)
    assert streamed.status_code == 413

    wrong = await tg_client.post(f"/tg/{bot.id}", content=big, headers={**headers, SECRET_HEADER: "nope"})
    assert wrong.status_code == 403  # the secret is checked first
    assert fake_tg.calls == []


# Header bytes are decoded as latin-1, so "²", "³" and "¹" (0xB2, 0xB3, 0xB9) are the non-ASCII
# characters for which str.isdigit() is true that can arrive; int() rejects every one of them.
@pytest.mark.parametrize("declared", [b"\xb2", b"\xb3", b"\xb9", b"1\xb2", b"-1", b"1e3", b" 12"])
async def test_a_content_length_that_is_not_ascii_digits_is_no_error(
    tg_client: httpx.AsyncClient, bot: LiveBot, declared: bytes
) -> None:
    """``"²".isdigit()`` is true but ``int("²")`` fails: the webhook answered a 500. Such a header is
    now ignored and the body is measured as it streams, as when no length is declared."""
    headers = [
        (b"content-type", b"application/json"),
        (SECRET_HEADER.encode(), bot.secret.encode()),
        (b"content-length", declared),
    ]
    body = json.dumps({"update_id": 987_654}).encode()
    response = await tg_client.post(f"/tg/{bot.id}", content=body, headers=headers)
    assert response.status_code == 200, (declared, response.text)
    assert response.json() == {"ok": True}

    big = json.dumps({"update_id": 987_655, "pad": "x" * (1024 * 1024 + 10)}).encode()
    too_big = await tg_client.post(f"/tg/{bot.id}", content=big, headers=headers)
    assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "body_too_large"


# --- dedupe, readiness -----------------------------------------------------------------------


async def test_duplicate_update_is_acknowledged_but_not_processed_again(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    chat = Chat(tg_client, bot, fake_tg, 501)
    update = message_update(42, 501, "/start")
    assert (await chat.post(update)).status_code == 200
    first_calls = len(fake_tg.calls)
    assert first_calls >= 1
    again = await chat.post(update)
    assert again.status_code == 200
    assert len(fake_tg.calls) == first_calls
    assert await count(session_factory, TgUpdate, bot.id) == 1


async def test_same_update_id_on_two_bots_is_not_a_duplicate(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    other = await make_live_bot(session_factory, golden_spec)
    for b in (bot, other):
        await Chat(tg_client, b, fake_tg, 501).post(message_update(7, 501, "/start"))
    assert len(fake_tg.calls_to("sendMessage")) == 2


async def test_bot_without_active_revision_replies_not_ready(
    tg_client: httpx.AsyncClient, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    bot = await make_live_bot(session_factory, None)
    chat = Chat(tg_client, bot, fake_tg, 501)
    assert (await chat.say("/start")).status_code == 200
    assert chat.last_text() == texts.NOT_READY
    assert (await chat.press("menu:home:")).status_code == 200
    assert chat.last_text() == texts.NOT_READY
    assert len(fake_tg.calls_to("answerCallbackQuery")) == 1  # the button press is still answered


async def test_group_messages_and_unsupported_updates_are_ignored(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    chat = Chat(tg_client, bot, fake_tg, 501)
    assert (await chat.post(message_update(1, 501, "/start", chat_type="group"))).status_code == 200
    assert (await chat.post({"update_id": 2, "edited_message": {"text": "x"}})).status_code == 200
    assert (await chat.post({"update_id": 3, "message": {"chat": {"type": "private"}}})).status_code == 200
    assert fake_tg.calls == []


# --- the golden flow --------------------------------------------------------------------------


async def test_golden_flow_book_waitlist_cancel_and_promotion(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    ali, sara = Chat(tg_client, bot, fake_tg, 601), Chat(tg_client, bot, fake_tg, 602)

    # start -> menu
    assert (await ali.say("/start")).status_code == 200
    assert ali.last_text().startswith("سلام")
    assert any(b["callback_data"] == "menu:open:workshops" for b in ali.buttons())
    assert fake_tg.calls[-1][0] == "sendMessage"

    # menu -> list -> item: each callback edits the message that carried the button
    await ali.press(ali.data_with("menu:open:workshops"))
    assert fake_tg.calls[-1][0] == "editMessageText" and fake_tg.calls[-1][1]["message_id"] == 77
    assert "کارگاه عکاسی" in ali.last_text() or any("کارگاه عکاسی" in b["text"] for b in ali.buttons())
    await ali.press(ali.data_with(f"{CAP}:item:"))
    assert "کارگاه عکاسی" in ali.last_text()

    # book -> confirmed
    book = ali.data_with(f"{CAP}:book:")
    assert book == f"{CAP}:book:{item}"
    await ali.press(book)
    confirmed_text = ali.last_text()
    # a second user is waitlisted: capacity is 1
    await sara.press(f"{CAP}:book:{item}")
    assert sara.last_text() != confirmed_text
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RecordRow).where(RecordRow.bot_id == bot.id, RecordRow.collection == CAP)
                )
            )
            .scalars()
            .all()
        )
    by_actor = {r.actor_id: r for r in rows}
    assert by_actor["601"].status == "confirmed" and by_actor["602"].status == "waitlisted"
    assert {r.env for r in rows} == {"live"}

    # every callback was answered
    assert len(fake_tg.calls_to("answerCallbackQuery")) == 4

    # ali cancels -> sara is promoted and receives a message in her own chat
    before = len(sara.shown())
    await ali.press(f"{CAP}:cancel:{by_actor['601'].id}")
    assert len(sara.shown()) == before + 1
    promoted = sara.shown()[-1]
    assert promoted["text"]
    assert fake_tg.calls[-1][0] in ("sendMessage", "editMessageText")
    async with session_factory() as session:
        statuses = {
            r.actor_id: r.status
            for r in (
                await session.execute(
                    select(RecordRow).where(RecordRow.bot_id == bot.id, RecordRow.collection == CAP)
                )
            ).scalars()
        }
    assert statuses == {"601": "cancelled", "602": "confirmed"}


async def test_text_message_outside_a_form_shows_the_menu(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    chat = Chat(tg_client, bot, fake_tg, 603)
    await chat.say("یک پیام تصادفی")
    assert any(b["callback_data"].startswith("menu:open:") for b in chat.buttons())


async def test_hostile_user_text_never_reaches_telegram_unescaped(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    await add_workshop(tg_client, bot, title="<b>x</b> & <i>y</i>")
    chat = Chat(tg_client, bot, fake_tg, 604)
    await chat.say("/start")
    await chat.press("menu:open:workshops")
    await chat.press(chat.data_with(f"{CAP}:item:"))
    shown = chat.shown()[-1]
    assert "<b>" not in shown["text"] and "<i>" not in shown["text"]
    assert "&lt;b&gt;x&lt;/b&gt; &amp; &lt;i&gt;y&lt;/i&gt;" in shown["text"]


async def test_concurrent_bookings_are_serialized_by_the_advisory_lock(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    chats = [Chat(tg_client, bot, fake_tg, 700 + i) for i in range(4)]
    responses = await asyncio.gather(*(c.press(f"{CAP}:book:{item}") for c in chats))
    assert all(r.status_code == 200 for r in responses)
    async with session_factory() as session:
        statuses = sorted(
            r.status
            for r in (
                await session.execute(
                    select(RecordRow).where(RecordRow.bot_id == bot.id, RecordRow.collection == CAP)
                )
            ).scalars()
        )
    assert statuses == ["confirmed", "waitlisted", "waitlisted", "waitlisted"]


# --- owner linking ----------------------------------------------------------------------------


async def test_owner_link_stores_the_owner_and_is_consumed(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    owner = Chat(tg_client, bot, fake_tg, 900)
    assert (await owner.say(f"/start owner_{bot.owner_link_code}")).status_code == 200
    assert owner.last_text() == texts.OWNER_LINKED
    row = await load_bot(session_factory, bot.id)
    assert row.owner_actor_id == "900"
    assert row.owner_link_code is None  # single use: no code stays armed after a link

    # the used link cannot be reused, not even by someone else
    intruder = Chat(tg_client, bot, fake_tg, 901)
    await intruder.say(f"/start owner_{bot.owner_link_code}")
    assert intruder.last_text() == texts.OWNER_LINK_INVALID
    assert (await load_bot(session_factory, bot.id)).owner_actor_id == "900"

    # a wrong code never links anyone
    await intruder.say("/start owner_totallywrong")
    assert intruder.last_text() == texts.OWNER_LINK_INVALID
    assert (await load_bot(session_factory, bot.id)).owner_actor_id == "900"


async def test_after_a_link_nothing_is_armed_until_the_owner_reconnects(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    await Chat(tg_client, bot, fake_tg, 900).say(f"/start owner_{bot.owner_link_code}")
    status = (await tg_client.get(f"/bots/{bot.id}/telegram", headers=ALICE)).json()
    # nothing on the Settings page (or a screenshot of it) could make someone else the owner
    assert status["owner_linked"] is True and status["owner_link"] is None

    # a new link exists only after an action of the authenticated owner: reconnecting the token,
    # which also unlinks the current owner (the new code links an owner, it never replaces one)
    reconnected = await tg_client.post(
        f"/bots/{bot.id}/telegram/connect", json={"token": bot.token}, headers=ALICE
    )
    assert reconnected.status_code == 200, reconnected.text
    assert reconnected.json()["owner_linked"] is False
    assert (await load_bot(session_factory, bot.id)).owner_actor_id is None
    link = reconnected.json()["owner_link"]
    assert link and "?start=owner_" in link
    bot.secret = (await load_bot(session_factory, bot.id)).tg_webhook_secret  # re-registered webhook
    successor = Chat(tg_client, bot, fake_tg, 901)
    await successor.say(f"/start {link.split('?start=', 1)[1]}")
    assert successor.last_text() == texts.OWNER_LINKED
    assert (await load_bot(session_factory, bot.id)).owner_actor_id == "901"


async def test_reconnecting_revokes_an_owner_link_that_was_never_used(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    leaked = bot.owner_link_code
    reconnected = await tg_client.post(
        f"/bots/{bot.id}/telegram/connect", json={"token": bot.token}, headers=ALICE
    )
    assert reconnected.status_code == 200 and leaked not in reconnected.json()["owner_link"]
    bot.secret = (await load_bot(session_factory, bot.id)).tg_webhook_secret  # re-registered webhook
    intruder = Chat(tg_client, bot, fake_tg, 901)
    await intruder.say(f"/start owner_{leaked}")
    assert intruder.last_text() == texts.OWNER_LINK_INVALID
    assert (await load_bot(session_factory, bot.id)).owner_actor_id is None


async def reconnect(
    client: httpx.AsyncClient, bot: LiveBot, session_factory: SessionFactory
) -> dict[str, Any]:
    """Connect the bot's token again through the API (the webhook secret changes with it)."""
    response = await client.post(f"/bots/{bot.id}/telegram/connect", json={"token": bot.token}, headers=ALICE)
    assert response.status_code == 200, response.text
    bot.secret = (await load_bot(session_factory, bot.id)).tg_webhook_secret or ""
    return response.json()


def start_payload(link: str) -> str:
    return link.split("?start=", 1)[1]


async def test_relinking_after_a_disconnect_shows_a_fresh_link_for_the_new_account(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    first = Chat(tg_client, bot, fake_tg, 900)
    await first.say(f"/start owner_{bot.owner_link_code}")
    assert first.last_text() == texts.OWNER_LINKED

    # The Settings page's advice for another Telegram account: disconnect, then reconnect the token.
    gone = (await tg_client.delete(f"/bots/{bot.id}/telegram", headers=ALICE)).json()
    assert (gone["connected"], gone["owner_linked"], gone["owner_link"]) == (False, False, None)
    row = await load_bot(session_factory, bot.id)
    assert (row.owner_actor_id, row.owner_link_code) == (None, None)  # unlinked, nothing armed

    connected = await reconnect(tg_client, bot, session_factory)
    status = (await tg_client.get(f"/bots/{bot.id}/telegram", headers=ALICE)).json()
    assert status == connected
    assert status["owner_linked"] is False and status["owner_link"]  # the page shows the fresh link
    fresh = start_payload(status["owner_link"])
    assert fresh != f"owner_{bot.owner_link_code}"

    # the used code stays dead, for the old account and for anyone else
    for chat in (first, Chat(tg_client, bot, fake_tg, 902)):
        await chat.say(f"/start owner_{bot.owner_link_code}")
        assert chat.last_text() == texts.OWNER_LINK_INVALID
    assert (await load_bot(session_factory, bot.id)).owner_actor_id is None

    # the fresh link links the new account, once
    second = Chat(tg_client, bot, fake_tg, 901)
    await second.say(f"/start {fresh}")
    assert second.last_text() == texts.OWNER_LINKED
    assert (await load_bot(session_factory, bot.id)).owner_actor_id == "901"
    status = (await tg_client.get(f"/bots/{bot.id}/telegram", headers=ALICE)).json()
    assert (status["owner_linked"], status["owner_link"]) == (True, None)
    late = Chat(tg_client, bot, fake_tg, 903)
    await late.say(f"/start {fresh}")
    assert late.last_text() == texts.OWNER_LINK_INVALID
    assert (await load_bot(session_factory, bot.id)).owner_actor_id == "901"

    # owner alerts reach the new account only
    seen_by_first = len(first.shown())
    await Chat(tg_client, bot, fake_tg, 610).press(f"{CAP}:book:{item}")
    assert len(first.shown()) == seen_by_first
    assert len(second.shown()) == 2 and second.last_text() != texts.OWNER_LINKED  # the "booked" alert


async def test_disconnecting_revokes_an_owner_link_that_was_never_used(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    leaked = bot.owner_link_code
    await tg_client.delete(f"/bots/{bot.id}/telegram", headers=ALICE)
    assert (await load_bot(session_factory, bot.id)).owner_link_code is None
    connected = await reconnect(tg_client, bot, session_factory)
    intruder = Chat(tg_client, bot, fake_tg, 901)
    await intruder.say(f"/start owner_{leaked}")
    assert intruder.last_text() == texts.OWNER_LINK_INVALID
    owner = Chat(tg_client, bot, fake_tg, 900)
    await owner.say(f"/start {start_payload(connected['owner_link'])}")
    assert owner.last_text() == texts.OWNER_LINKED
    assert (await load_bot(session_factory, bot.id)).owner_actor_id == "900"


async def test_a_code_left_armed_beside_a_linked_owner_is_hidden_and_replaces_no_one(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    # Older code could leave both (link, then reconnect): such a code must neither show nor work.
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None
        row.owner_actor_id, row.owner_link_code = "900", "leftover-code"
        await session.commit()
    status = (await tg_client.get(f"/bots/{bot.id}/telegram", headers=ALICE)).json()
    assert (status["owner_linked"], status["owner_link"]) == (True, None)
    intruder = Chat(tg_client, bot, fake_tg, 901)
    await intruder.say("/start owner_leftover-code")
    assert intruder.last_text() == texts.OWNER_LINK_INVALID
    assert (await load_bot(session_factory, bot.id)).owner_actor_id == "900"


async def test_a_link_made_while_a_disconnect_runs_does_not_survive_it(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = Chat(tg_client, bot, fake_tg, 900)
    delete_webhook = fake_tg.delete_webhook

    async def link_meanwhile() -> None:  # the disconnect request has already read the bot row
        await owner.say(f"/start owner_{bot.owner_link_code}")
        assert owner.last_text() == texts.OWNER_LINKED
        await delete_webhook()

    monkeypatch.setattr(fake_tg, "delete_webhook", link_meanwhile)
    gone = await tg_client.delete(f"/bots/{bot.id}/telegram", headers=ALICE)
    assert gone.status_code == 200 and gone.json()["owner_linked"] is False
    row = await load_bot(session_factory, bot.id)
    assert (row.owner_actor_id, row.owner_link_code) == (None, None)


async def test_a_link_made_while_a_reconnect_runs_does_not_survive_it(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = Chat(tg_client, bot, fake_tg, 900)
    get_me = fake_tg.get_me

    async def link_meanwhile() -> dict[str, Any]:  # the connect request has already read the bot row
        await owner.say(f"/start owner_{bot.owner_link_code}")
        assert owner.last_text() == texts.OWNER_LINKED
        return await get_me()

    monkeypatch.setattr(fake_tg, "get_me", link_meanwhile)
    connected = await reconnect(tg_client, bot, session_factory)
    assert connected["owner_linked"] is False and connected["owner_link"]
    row = await load_bot(session_factory, bot.id)
    assert row.owner_actor_id is None
    assert row.owner_link_code and f"owner_{row.owner_link_code}" == start_payload(connected["owner_link"])


async def wait_until_the_owner_update_waits_for_the_row(
    observer: AsyncSession, task: asyncio.Task[Any]
) -> None:
    query = text(
        "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
        "AND query ILIKE 'UPDATE%owner_actor_id%'"
    )
    for _ in range(500):
        assert not task.done(), "the link finished without waiting for the row"
        if (await observer.execute(query)).scalar_one():
            return
        await observer.commit()  # pg_stat_activity is a snapshot per transaction
        await asyncio.sleep(0.01)
    raise AssertionError("the owner UPDATE never waited for the row lock")


async def test_a_code_revoked_while_the_link_waits_for_the_row_links_no_one(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    owner = Chat(tg_client, bot, fake_tg, 900)
    async with session_factory() as revoking, session_factory() as observer:
        # a connect or disconnect that has written the row but not committed yet (no bot lock)
        await revoking.execute(update(Bot).where(Bot.id == bot.id).values(owner_link_code="rotated-code"))
        link = asyncio.create_task(owner.say(f"/start owner_{bot.owner_link_code}"))
        await wait_until_the_owner_update_waits_for_the_row(observer, link)
        await revoking.commit()
        assert (await link).status_code == 200
    assert owner.last_text() == texts.OWNER_LINK_INVALID
    assert (await load_bot(session_factory, bot.id)).owner_actor_id is None


async def test_linked_owner_receives_alerts_and_may_use_owner_actions(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    item = await add_workshop(tg_client, bot)
    owner = Chat(tg_client, bot, fake_tg, 900)
    await owner.say(f"/start owner_{bot.owner_link_code}")
    customer = Chat(tg_client, bot, fake_tg, 610)
    await customer.press(f"{CAP}:book:{item}")
    alerts = owner.shown()
    assert len(alerts) == 2  # the confirmation and the "booked" alert
    assert alerts[-1]["text"] != texts.OWNER_LINKED


# --- robustness -------------------------------------------------------------------------------


async def test_internal_error_still_returns_200_and_the_next_update_works(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import app.api.webhook as webhook

    real = webhook.dispatch

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(webhook, "dispatch", boom)
    chat = Chat(tg_client, bot, fake_tg, 620)
    response = await chat.say("/start")
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert "engine exploded" in caplog.text and str(bot.id) in caplog.text
    assert "/start" not in caplog.text  # message content is not logged

    monkeypatch.setattr(webhook, "dispatch", real)
    assert (await chat.say("/start")).status_code == 200
    assert chat.shown()  # the session was usable again


async def test_malformed_bodies_return_200(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    headers = {SECRET_HEADER: bot.secret, "content-type": "application/json"}
    for body in (b"not json", b"[]", b"{}", b'{"update_id": "7"}', b'{"update_id": true}'):
        response = await tg_client.post(f"/tg/{bot.id}", content=body, headers=headers)
        assert response.status_code == 200, body


async def test_delivery_failure_does_not_fail_the_webhook_and_state_is_kept(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    fake_tg.fail_methods["editMessageText"] = "Bad Request: message can't be edited"
    fake_tg.fail_methods["sendMessage"] = "Forbidden: bot was blocked by the user"
    chat = Chat(tg_client, bot, fake_tg, 630)
    assert (await chat.press(f"{CAP}:book:{item}")).status_code == 200
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RecordRow).where(RecordRow.bot_id == bot.id, RecordRow.collection == CAP)
                )
            )
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == ["confirmed"]  # committed before delivery
    assert "blocked" in (await load_bot(session_factory, bot.id)).tg_last_error
