"""The dispatch service: one function for webhook, simulator and admin. Needs a database."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.botspec.models import BotSpec
from app.db.models import Bot, RecordRow
from app.integrations.telegram.adapter import TelegramOrigin
from app.integrations.telegram.client import FakeTelegramClient
from app.runtime.callbacks import make_callback
from app.runtime.contracts import Actor, RuntimeEvent
from app.runtime.pg_store import PgStore
from app.runtime.runtime import BotRuntime
from app.services.dispatch import dispatch
from tests.integration.helpers import REPO, SessionFactory
from tests.integration.tg_helpers import CAP, LiveBot, capacity_spec, make_live_bot

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
async def bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, capacity_spec(golden_spec, 1), owner_actor_id="900")


@pytest.fixture
def spec(golden_spec: dict[str, Any]) -> BotSpec:
    return BotSpec.model_validate(capacity_spec(golden_spec, 1))


def event(bot: LiveBot, env: str, actor: str, kind: str, **kw: Any) -> RuntimeEvent:
    return RuntimeEvent(
        bot_id=str(bot.id),
        env=env,  # type: ignore[arg-type]
        actor=Actor(id=actor, display_name=actor, is_owner=kw.pop("is_owner", False)),
        kind=kind,  # type: ignore[arg-type]
        now=NOW,
        **kw,
    )


async def add_item(session_factory: SessionFactory, bot: LiveBot, env: str) -> int:
    async with session_factory() as session:
        store = PgStore(session, bot.id, env)  # type: ignore[arg-type]
        record = await store.create_record(
            "workshop", {"title": "کارگاه", "starts_at": "2027-11-01T06:30:00+00:00"}, now=NOW
        )
        await session.commit()
        return record.id


async def run(
    session_factory: SessionFactory,
    bot: LiveBot,
    spec: BotSpec,
    ev: RuntimeEvent,
    fake: FakeTelegramClient,
    **kw: Any,
) -> Any:
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None
        return await dispatch(session, row, spec, ev, telegram=fake.provider, **kw)


async def test_sandbox_sends_nothing_and_returns_the_messages(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    response = await run(session_factory, bot, spec, event(bot, "sandbox", "ali", "start"), fake_tg)
    assert response.messages and response.messages[0].to_actor_id == "ali"
    assert fake_tg.calls == [] and fake_tg.tokens == []  # not even a client was built


async def test_sandbox_uses_the_owner_persona_and_never_touches_live_rows(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    item = await add_item(session_factory, bot, "sandbox")
    book = make_callback(CAP, "book", str(item))
    # a confirmed booking alerts the sandbox "owner" persona, a waitlisted one does not
    first = await run(
        session_factory, bot, spec, event(bot, "sandbox", "ali", "callback", data=book), fake_tg
    )
    assert {m.to_actor_id for m in first.messages} == {"ali", "owner"}
    second = await run(
        session_factory, bot, spec, event(bot, "sandbox", "sara", "callback", data=book), fake_tg
    )
    assert {m.to_actor_id for m in second.messages} == {"sara"}
    async with session_factory() as session:
        envs = {
            r.env
            for r in (
                await session.execute(
                    select(RecordRow).where(RecordRow.bot_id == bot.id, RecordRow.collection == CAP)
                )
            ).scalars()
        }
    assert envs == {"sandbox"}


async def test_live_delivers_every_message_with_the_decrypted_token(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    item = await add_item(session_factory, bot, "live")
    ev = event(bot, "live", "601", "callback", data=make_callback(CAP, "book", str(item)))
    origin = TelegramOrigin(chat_id=601, callback_query_id="cq-1", message_id=55)
    response = await run(session_factory, bot, spec, ev, fake_tg, origin=origin)
    assert fake_tg.tokens == [bot.token]
    assert [k["callback_query_id"] for k in fake_tg.calls_to("answerCallbackQuery")] == ["cq-1"]
    # the reply edits the pressed message; the owner (900) gets a separate alert
    assert [k["message_id"] for k in fake_tg.calls_to("editMessageText")] == [55]
    assert len(fake_tg.sent_to(900)) == 1
    assert len(response.messages) == len(fake_tg.calls_to("editMessageText")) + len(
        fake_tg.calls_to("sendMessage")
    )


async def test_delivery_failure_is_recorded_not_raised_and_cleared_by_the_next_clean_delivery(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    fake_tg.fail_methods["sendMessage"] = "Forbidden: bot was blocked by the user"
    response = await run(session_factory, bot, spec, event(bot, "live", "601", "start"), fake_tg)
    assert response.messages  # the caller still gets the response
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None and row.tg_last_error == "sendMessage: Forbidden: bot was blocked by the user"

    fake_tg.fail_methods.clear()
    await run(session_factory, bot, spec, event(bot, "live", "601", "start"), fake_tg)
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None and row.tg_last_error is None


async def test_messages_to_non_telegram_actors_are_skipped_and_keep_the_last_error(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    # a real failure is on record ...
    fake_tg.fail_methods["sendMessage"] = "Forbidden: bot was blocked by the user"
    await run(session_factory, bot, spec, event(bot, "live", "601", "start"), fake_tg)
    fake_tg.fail_methods.clear()
    fake_tg.calls.clear()
    # ... and a reply to a seeded demo customer is neither sent nor counted as a clean delivery
    response = await run(session_factory, bot, spec, event(bot, "live", "demo-01", "start"), fake_tg)
    assert response.messages and {m.to_actor_id for m in response.messages} == {"demo-01"}
    assert fake_tg.calls_to("sendMessage") == []
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None and row.tg_last_error == "sendMessage: Forbidden: bot was blocked by the user"


async def test_delivery_failure_is_logged_with_bot_and_description(
    session_factory: SessionFactory,
    bot: LiveBot,
    spec: BotSpec,
    fake_tg: FakeTelegramClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_tg.fail_methods["sendMessage"] = "Forbidden: bot was blocked by the user"
    await run(session_factory, bot, spec, event(bot, "live", "601", "start"), fake_tg)
    assert str(bot.id) in caplog.text and "sendMessage" in caplog.text and "blocked" in caplog.text
    assert bot.token not in caplog.text


async def test_state_is_committed_before_delivery(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    item = await add_item(session_factory, bot, "live")
    fake_tg.fail_methods["sendMessage"] = "Bad Gateway"
    fake_tg.fail_methods["editMessageText"] = "Bad Gateway"
    ev = event(bot, "live", "601", "callback", data=make_callback(CAP, "book", str(item)))
    await run(session_factory, bot, spec, ev, fake_tg)
    async with session_factory() as session:
        statuses = [
            r.status
            for r in (
                await session.execute(
                    select(RecordRow).where(RecordRow.bot_id == bot.id, RecordRow.collection == CAP)
                )
            ).scalars()
        ]
    assert statuses == ["confirmed"]


async def test_missing_token_is_recorded_and_not_raised(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None
        row.tg_token_enc = "not-a-fernet-token"
        await session.commit()
    response = await run(session_factory, bot, spec, event(bot, "live", "601", "start"), fake_tg)
    assert response.messages and fake_tg.calls == []
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None and row.tg_last_error


async def test_runtime_failure_rolls_back_answers_the_callback_and_raises(
    session_factory: SessionFactory,
    bot: LiveBot,
    spec: BotSpec,
    fake_tg: FakeTelegramClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(self: Any, *args: Any) -> Any:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(BotRuntime, "handle", boom)
    ev = event(bot, "live", "601", "callback", data="menu:home:")
    with pytest.raises(RuntimeError, match="engine exploded"):
        await run(session_factory, bot, spec, ev, fake_tg, origin=TelegramOrigin(601, "cq-9", 5))
    assert [k["callback_query_id"] for k in fake_tg.calls_to("answerCallbackQuery")] == ["cq-9"]
    assert fake_tg.calls_to("sendMessage") == []


async def test_event_for_another_bot_is_refused(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    ev = event(bot, "live", "601", "start").model_copy(
        update={"bot_id": "11111111-1111-1111-1111-111111111111"}
    )
    with pytest.raises(ValueError, match="bot"):
        await run(session_factory, bot, spec, ev, fake_tg)


async def test_live_owner_rights_follow_the_owner_link_read_under_the_lock(
    session_factory: SessionFactory, fake_tg: FakeTelegramClient, tg_env: None
) -> None:
    repair = json.loads((REPO / "examples" / "repair.botspec.json").read_text(encoding="utf-8"))
    bot = await make_live_bot(session_factory, repair, owner_actor_id="900")
    spec = BotSpec.model_validate(repair)
    own = make_callback("repair", "own", "1.approve")  # an owner-only button press

    # flagged as owner when the update was parsed, but 900 is the linked owner now: no rights
    stale = await run(
        session_factory, bot, spec, event(bot, "live", "601", "callback", data=own, is_owner=True), fake_tg
    )
    assert [(o.result, o.reason) for o in stale.outcomes] == [("rejected", "not_allowed")]

    # and the linked owner is recognised even when the flag was computed before the link
    linked = await run(
        session_factory, bot, spec, event(bot, "live", "900", "callback", data=own, is_owner=False), fake_tg
    )
    assert all(o.reason != "not_allowed" for o in linked.outcomes)


async def test_admin_event_does_not_echo_the_owner_reply_to_telegram(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    item = await add_item(session_factory, bot, "live")
    book = make_callback(CAP, "book", str(item))
    await run(session_factory, bot, spec, event(bot, "live", "601", "callback", data=book), fake_tg)
    await run(session_factory, bot, spec, event(bot, "live", "602", "callback", data=book), fake_tg)
    async with session_factory() as session:
        first = (
            await session.execute(
                select(RecordRow).where(
                    RecordRow.bot_id == bot.id, RecordRow.actor_id == "601", RecordRow.collection == CAP
                )
            )
        ).scalar_one()
    fake_tg.calls.clear()
    cancel = event(
        bot, "live", "900", "admin", data=make_callback(CAP, "cancel", str(first.id)), is_owner=True
    )
    response = await run(session_factory, bot, spec, cancel, fake_tg)
    assert any(m.to_actor_id == "900" for m in response.messages)  # in the response for the web admin
    assert fake_tg.sent_to(900) == []  # but not pushed to the owner's Telegram chat
    assert len(fake_tg.sent_to(602)) == 1  # the promoted customer is notified


async def test_live_delivery_skips_actors_that_are_not_telegram_chat_ids(
    session_factory: SessionFactory,
    bot: LiveBot,
    spec: BotSpec,
    fake_tg: FakeTelegramClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="app.services.dispatch")
    response = await run(session_factory, bot, spec, event(bot, "live", "demo-01", "start"), fake_tg)
    assert response.messages and response.messages[0].to_actor_id == "demo-01"  # still in the response
    assert fake_tg.calls_to("sendMessage") == [] and fake_tg.calls_to("editMessageText") == []
    assert "demo-01" in caplog.text
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None and row.tg_last_error is None

    # a numeric id and a negative (group) id are still delivered
    await run(session_factory, bot, spec, event(bot, "live", "601", "start"), fake_tg)
    assert len(fake_tg.sent_to(601)) == 1
    await run(session_factory, bot, spec, event(bot, "live", "-100123", "start"), fake_tg)
    assert len(fake_tg.sent_to(-100123)) == 1


async def test_skipping_a_non_numeric_actor_does_not_clear_or_set_the_last_error(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    fake_tg.fail_methods["sendMessage"] = "Forbidden: bot was blocked by the user"
    await run(session_factory, bot, spec, event(bot, "live", "601", "start"), fake_tg)
    fake_tg.fail_methods.clear()
    await run(session_factory, bot, spec, event(bot, "live", "demo-02", "start"), fake_tg)  # sends nothing
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None and row.tg_last_error == "sendMessage: Forbidden: bot was blocked by the user"


async def test_live_delivery_skips_persian_digit_ids(
    session_factory: SessionFactory, bot: LiveBot, spec: BotSpec, fake_tg: FakeTelegramClient
) -> None:
    response = await run(session_factory, bot, spec, event(bot, "live", "۱۲۳", "start"), fake_tg)
    assert response.messages and fake_tg.calls_to("sendMessage") == []
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None and row.tg_last_error is None
