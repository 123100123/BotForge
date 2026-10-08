"""Telegram polling mode (TELEGRAM_MODE=polling) end to end: the poller, its offset, its error handling,
connect and disconnect, the lifespan and the re-registration script. Needs a database. Telegram is the
fake client, or the real client over a stub transport: never the network. The poller's waits are
injected, so no test sleeps for a backoff."""

import asyncio
import importlib.util
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Bot, TgUpdate
from app.integrations.telegram import poller as poller_module
from app.integrations.telegram import texts
from app.integrations.telegram.client import FakeTelegramClient, TelegramApi, TelegramClient, TelegramError
from app.integrations.telegram.poller import TelegramPoller
from app.main import create_app
from app.security.crypto import encrypt_token
from tests.integration.conftest import MakeBot
from tests.integration.helpers import BACKEND, SessionFactory
from tests.integration.tg_helpers import (
    ALICE,
    LiveBot,
    capacity_spec,
    make_live_bot,
    message_update,
    new_token,
)

NETWORK = TelegramError("getUpdates", "network error (ConnectError)", network=True)


class Telegram:
    """One fake Telegram client per token, like the real Bot API (each bot has its own update queue)."""

    def __init__(self) -> None:
        self.by_token: dict[str, FakeTelegramClient] = {}

    def __call__(self, token: str) -> FakeTelegramClient:
        if token not in self.by_token:
            fake = FakeTelegramClient()
            fake.poll_wait = 0.02
            self.by_token[token] = fake
        return self.by_token[token]


class Sleeps:
    """The poller's injected sleep: records each wait and returns at once."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        await asyncio.sleep(0)


async def eventually(check: Callable[[], Any], timeout: float = 10.0) -> None:
    """Wait (real time, the test's own clock) until ``check()`` is truthy."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        result = check()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        assert loop.time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


async def row(session_factory: SessionFactory, bot_id: uuid.UUID) -> Bot:
    async with session_factory() as session:
        found = (await session.execute(select(Bot).where(Bot.id == bot_id))).scalar_one()
        session.expunge(found)
        return found


async def seen_updates(session_factory: SessionFactory, bot_id: uuid.UUID) -> set[int]:
    async with session_factory() as session:
        rows = await session.execute(select(TgUpdate.update_id).where(TgUpdate.bot_id == bot_id))
        return set(rows.scalars())


@pytest.fixture
async def bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, capacity_spec(golden_spec, 1))


@pytest.fixture
def telegram() -> Telegram:
    return Telegram()


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest_asyncio.fixture
async def make_poller(
    session_factory: SessionFactory, telegram: Telegram, sleeps: Sleeps
) -> AsyncIterator[Callable[..., TelegramPoller]]:
    """Pollers limited to the given bots (other tests leave connected bots in the database); every
    poller made here is stopped after the test."""
    made: list[TelegramPoller] = []

    def make(
        *bot_ids: uuid.UUID, provider: Callable[[str], TelegramApi] | None = None, **options: Any
    ) -> TelegramPoller:
        poller = TelegramPoller(
            session_factory,
            provider or telegram,
            sleep=sleeps,
            rng=lambda: 1.0,
            stop_grace=5.0,
            bot_ids=bot_ids,
            **options,
        )
        made.append(poller)
        return poller

    yield make
    for poller in made:
        await poller.stop()


def polls(fake: FakeTelegramClient) -> list[dict[str, Any]]:
    return fake.calls_to("getUpdates")


def sent_texts(fake: FakeTelegramClient, chat_id: int) -> list[str]:
    return [call["text"] for call in fake.sent_to(chat_id)]


# --- the shared path, order and offset ------------------------------------------------------------


async def test_updates_are_handled_in_order_through_the_webhook_path_and_the_offset_persists(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    fake.push_updates(
        message_update(501, 701, "/start"),
        message_update(502, 701, "سلام"),
        message_update(503, 702, "/start"),
    )
    poller = make_poller(bot.id)
    await poller.sync_once()
    assert set(poller.polling) == {bot.id}

    async def offset_saved() -> bool:
        return (await row(session_factory, bot.id)).tg_poll_offset == 504

    await eventually(offset_saved)
    await eventually(lambda: any(call["offset"] == 504 for call in polls(fake)))  # confirms 501-503

    names = [name for name, _ in fake.calls]
    assert names[0] == "deleteWebhook" and fake.calls[0][1] == {"drop_pending_updates": False}
    assert polls(fake)[0] == {
        "offset": None,
        "timeout": 25,
        "allowed_updates": ["message", "callback_query", "my_chat_member"],
    }
    # the webhook's own path: deduplicated, converted, dispatched and answered, one update at a time
    assert await seen_updates(session_factory, bot.id) == {501, 502, 503}
    chats = [int(call["chat_id"]) for call in fake.calls_to("sendMessage")]
    first_702 = chats.index(702)
    assert first_702 > 0 and set(chats[:first_702]) == {701} and set(chats[first_702:]) == {702}


async def test_a_restart_resumes_from_the_stored_offset_without_replaying(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    fake.push_updates(message_update(601, 711, "/start"))
    first = make_poller(bot.id)
    await first.sync_once()
    await eventually(lambda: sent_texts(fake, 711))

    async def saved() -> bool:
        return (await row(session_factory, bot.id)).tg_poll_offset == 602

    await eventually(saved)
    await first.stop()
    replies_before = len(fake.sent_to(711))
    polls_before = len(polls(fake))

    # Telegram still holds 601 if the process stopped before a later getUpdates confirmed it.
    fake.pending_updates = [message_update(601, 711, "/start")]
    fake.push_updates(message_update(602, 712, "/start"))
    second = make_poller(bot.id)
    await second.sync_once()
    await eventually(lambda: sent_texts(fake, 712))
    after_restart = polls(fake)[polls_before:]
    assert after_restart[0]["offset"] == 602  # resumed at the stored offset, which confirms 601
    assert all(call["offset"] >= 602 for call in after_restart)
    assert len(fake.sent_to(711)) == replies_before  # 601 was not handled again


async def test_a_replayed_update_is_dropped_as_a_duplicate(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    """The replay window: a crash after an update was handled but before its offset was saved. The
    update comes back and the shared path's dedupe (tg_updates) drops it, so no reply is sent twice."""
    fake = telegram(bot.token)
    fake.push_updates(message_update(651, 721, "/start"))
    first = make_poller(bot.id)
    await first.sync_once()
    await eventually(lambda: sent_texts(fake, 721))
    await first.stop()
    replies = len(fake.sent_to(721))

    async with session_factory() as session:  # the offset save "never happened"
        await session.execute(update(Bot).where(Bot.id == bot.id).values(tg_poll_offset=None))
        await session.commit()
    fake.pending_updates = [message_update(651, 721, "/start"), message_update(652, 722, "/start")]
    second = make_poller(bot.id)
    await second.sync_once()
    await eventually(lambda: sent_texts(fake, 722))

    async def saved() -> bool:
        return (await row(session_factory, bot.id)).tg_poll_offset == 653

    await eventually(saved)
    assert len(fake.sent_to(721)) == replies


# --- webhook conflict and errors --------------------------------------------------------------------


async def test_the_webhook_is_deleted_at_start_and_again_on_a_conflict(
    bot: LiveBot, telegram: Telegram, sleeps: Sleeps, make_poller: Callable[..., TelegramPoller]
) -> None:
    fake = telegram(bot.token)
    fake.get_updates_errors.append(
        TelegramError(
            "getUpdates", "Conflict: can't use getUpdates method while webhook is active", error_code=409
        )
    )
    fake.push_updates(message_update(801, 731, "/start"))
    await make_poller(bot.id).sync_once()
    await eventually(lambda: sent_texts(fake, 731))
    deletes = fake.calls_to("deleteWebhook")
    assert deletes == [{"drop_pending_updates": False}, {"drop_pending_updates": False}]
    names = [name for name, _ in fake.calls]
    assert names[:4] == ["deleteWebhook", "getUpdates", "deleteWebhook", "getUpdates"]
    assert sleeps.waits[0] == 1.0  # then backed off


# --- competing consumers: park, retry, prune --------------------------------------------------------

COMPETITOR = TelegramError(
    "getUpdates",
    "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running",
    error_code=409,
)


def conflicts(count: int) -> list[Exception]:
    return [COMPETITOR] * count


async def parked_with_error(session_factory: SessionFactory, bot_id: uuid.UUID) -> bool:
    error = (await row(session_factory, bot_id)).tg_last_error
    return error is not None and error.startswith("POLLING_CONFLICT:")


async def test_three_competing_consumer_conflicts_park_the_bot(
    bot: LiveBot,
    telegram: Telegram,
    sleeps: Sleeps,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    fake.get_updates_errors.extend(conflicts(3))
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: parked_with_error(session_factory, bot.id))
    await eventually(lambda: not poller.polling)

    stored = (await row(session_factory, bot.id)).tg_last_error
    assert stored == texts.POLLING_CONFLICT and "تلاش دوباره" in stored
    assert len(polls(fake)) == 3
    assert fake.calls_to("deleteWebhook") == [{"drop_pending_updates": False}]  # only the one at start
    assert sleeps.waits[:2] == [1.0, 2.0]  # backed off between the conflicts, not after the third

    await poller.sync_once()  # same token, error still set: the supervisor leaves it parked
    await asyncio.sleep(0.05)
    assert not poller.polling and len(polls(fake)) == 3
    assert bot.id in poller._runs


async def test_a_token_change_unparks_the_bot(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    telegram(bot.token).get_updates_errors.extend(conflicts(3))
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: parked_with_error(session_factory, bot.id))
    await eventually(lambda: not poller.polling)

    _, new = new_token()
    async with session_factory() as session:  # what a reconnect stores (and it clears the error)
        await session.execute(
            update(Bot).where(Bot.id == bot.id).values(tg_token_enc=encrypt_token(new), tg_last_error=None)
        )
        await session.commit()
    await poller.sync_once()
    await eventually(lambda: polls(telegram(new)))
    assert bot.id in poller.polling


async def test_the_retry_endpoint_unparks_the_bot(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
    tg_client: httpx.AsyncClient,
) -> None:
    fake = telegram(bot.token)
    fake.get_updates_errors.extend(conflicts(3))
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: parked_with_error(session_factory, bot.id))
    await eventually(lambda: not poller.polling)

    status = await tg_client.get(f"/bots/{bot.id}/telegram", headers=ALICE)
    assert status.json()["last_error"].startswith("POLLING_CONFLICT:")
    response = await tg_client.post(f"/bots/{bot.id}/telegram/retry", headers=ALICE)
    assert response.status_code == 200 and response.json()["last_error"] is None
    assert (await row(session_factory, bot.id)).tg_last_error is None

    fake.push_updates(message_update(901, 741, "/start"))
    await poller.sync_once()
    await eventually(lambda: sent_texts(fake, 741))
    assert bot.id in poller.polling
    assert fake.calls_to("deleteWebhook") == [{"drop_pending_updates": False}] * 2  # start + new task


async def test_retry_leaves_other_errors_alone_and_belongs_to_the_owner(
    bot: LiveBot, session_factory: SessionFactory, tg_client: httpx.AsyncClient
) -> None:
    other = "getUpdates: Unauthorized"
    async with session_factory() as session:
        await session.execute(update(Bot).where(Bot.id == bot.id).values(tg_last_error=other))
        await session.commit()
    response = await tg_client.post(f"/bots/{bot.id}/telegram/retry", headers=ALICE)
    assert response.status_code == 200 and response.json()["last_error"] == other
    stranger = await tg_client.post(f"/bots/{bot.id}/telegram/retry", headers={"X-Test-User": "bob"})
    assert stranger.status_code == 404
    assert (await row(session_factory, bot.id)).tg_last_error == other


class ScriptedTelegram(FakeTelegramClient):
    """getUpdates follows a script: ``"ok"`` returns one new update at once, ``"409"`` is a competing
    consumer, and when the script is spent every poll is an ordinary empty long poll."""

    def __init__(self, script: list[str]) -> None:
        super().__init__()
        self.poll_wait = 0.02
        self.script = list(script)
        self._next_id = 1000

    async def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: list[str], limit: int | None = None
    ) -> list[dict[str, Any]]:
        step = self.script.pop(0) if self.script else None
        if step == "409":
            self._record("getUpdates", offset=offset, timeout=timeout, allowed_updates=allowed_updates)
            raise COMPETITOR
        if step == "ok":
            self._next_id += 1
            self.push_updates(message_update(self._next_id, 750, "/start"))
        return await super().get_updates(
            offset=offset, timeout=timeout, allowed_updates=allowed_updates, limit=limit
        )


async def test_alternating_success_and_competitor_conflicts_still_park_the_bot(
    bot: LiveBot,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    # Two servers sharing a token: each long poll often succeeds (with an update) between conflicts,
    # so "three in a row" would never be reached. The window counts them regardless.
    fake = ScriptedTelegram(["ok", "409", "ok", "409", "ok", "409"])
    poller = make_poller(bot.id, provider=lambda _token: fake, clock=lambda: 100.0)
    await poller.sync_once()
    await eventually(lambda: parked_with_error(session_factory, bot.id))
    await eventually(lambda: not poller.polling)
    assert len(polls(fake)) == 6
    assert (await row(session_factory, bot.id)).tg_last_error == texts.POLLING_CONFLICT
    assert len(sent_texts(fake, 750)) == 3  # the updates between the conflicts were still served


async def test_two_conflicts_with_successful_polls_between_do_not_park(
    bot: LiveBot,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = ScriptedTelegram(["409", "ok", "409", "ok", "ok"])
    poller = make_poller(bot.id, provider=lambda _token: fake, clock=lambda: 100.0)
    await poller.sync_once()
    await eventually(lambda: len(polls(fake)) >= 8)
    assert bot.id in poller.polling and not await parked_with_error(session_factory, bot.id)


async def test_conflicts_spread_wider_than_the_window_with_successes_between_do_not_park(
    bot: LiveBot,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    clock = [0.0]

    def tick() -> float:
        clock[0] += poller_module.PARK_WINDOW / 2 + 1  # any three readings span more than the window
        return clock[0]

    fake = ScriptedTelegram(["ok", "409", "ok", "409", "ok", "409", "ok", "409", "ok"])
    poller = make_poller(bot.id, provider=lambda _token: fake, clock=tick)
    await poller.sync_once()
    await eventually(lambda: len(polls(fake)) >= 12)
    assert bot.id in poller.polling and not await parked_with_error(session_factory, bot.id)


async def test_a_parked_bot_stays_parked_when_another_error_overwrites_the_conflict(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    fake.get_updates_errors.extend(conflicts(3))
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: parked_with_error(session_factory, bot.id))
    await eventually(lambda: not poller.polling)

    other = "sendMessage: Forbidden: bot was blocked by the user"
    async with session_factory() as session:  # some other code path wrote a different error
        await session.execute(update(Bot).where(Bot.id == bot.id).values(tg_last_error=other))
        await session.commit()
    await poller.sync_once()
    await asyncio.sleep(0.05)
    assert not poller.polling and len(polls(fake)) == 3  # still parked: not a retry

    async with session_factory() as session:  # the owner's retry clears the error
        await session.execute(update(Bot).where(Bot.id == bot.id).values(tg_last_error=None))
        await session.commit()
    await poller.sync_once()
    await eventually(lambda: len(polls(fake)) > 3)
    assert bot.id in poller.polling


async def test_a_webhook_is_active_conflict_still_deletes_the_webhook_and_never_parks(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    hook = TelegramError(
        "getUpdates", "Conflict: can't use getUpdates method while webhook is active", error_code=409
    )
    fake.get_updates_errors.extend([hook] * 5)
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: len(polls(fake)) >= 7)
    assert len(fake.calls_to("deleteWebhook")) == 6  # at start and after each of the five
    assert bot.id in poller.polling and not await parked_with_error(session_factory, bot.id)


async def test_a_restarted_process_polls_a_parked_bot_again_and_clears_the_stale_error(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Bot).where(Bot.id == bot.id).values(tg_last_error=texts.POLLING_CONFLICT)
        )
        await session.commit()
    fake = telegram(bot.token)
    poller = make_poller(bot.id)  # a new poller: no memory of the park
    await poller.sync_once()
    await eventually(lambda: polls(fake))

    async def cleared() -> bool:
        return (await row(session_factory, bot.id)).tg_last_error is None

    await eventually(cleared)
    assert bot.id in poller.polling


async def add_update(
    session_factory: SessionFactory, bot_id: uuid.UUID, update_id: int, age: timedelta
) -> None:
    async with session_factory() as session:
        session.add(TgUpdate(bot_id=bot_id, update_id=update_id, received_at=datetime.now(UTC) - age))
        await session.commit()


async def test_pruning_deletes_only_old_updates_and_runs_at_most_hourly(
    bot: LiveBot, make_poller: Callable[..., TelegramPoller], session_factory: SessionFactory
) -> None:
    await add_update(session_factory, bot.id, 1, timedelta(days=4))
    await add_update(session_factory, bot.id, 2, timedelta(days=3, hours=1))
    await add_update(session_factory, bot.id, 3, timedelta(days=2, hours=23))
    await add_update(session_factory, bot.id, 4, timedelta(minutes=1))
    clock = [1000.0]
    poller = make_poller(bot.id, clock=lambda: clock[0])
    await poller.prune_if_due()
    assert await seen_updates(session_factory, bot.id) == {3, 4}

    await add_update(session_factory, bot.id, 5, timedelta(days=10))
    clock[0] += 3599.0
    await poller.prune_if_due()  # not due yet
    assert await seen_updates(session_factory, bot.id) == {3, 4, 5}
    clock[0] += 2.0
    await poller.prune_if_due()
    assert await seen_updates(session_factory, bot.id) == {3, 4}


async def test_the_supervisor_loop_prunes(
    bot: LiveBot, make_poller: Callable[..., TelegramPoller], session_factory: SessionFactory
) -> None:
    await add_update(session_factory, bot.id, 7, timedelta(days=5))
    make_poller(bot.id).start()

    async def pruned() -> bool:
        return 7 not in await seen_updates(session_factory, bot.id)

    await eventually(pruned)


async def test_a_revoked_token_is_recorded_and_polling_stops_until_the_token_changes(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    fake.get_updates_errors.append(TelegramError("getUpdates", "Unauthorized", error_code=401))
    poller = make_poller(bot.id)
    await poller.sync_once()

    async def recorded() -> bool:
        return (await row(session_factory, bot.id)).tg_last_error == "getUpdates: Unauthorized"

    await eventually(recorded)
    await eventually(lambda: not poller.polling)
    await poller.sync_once()  # same token: not restarted
    await asyncio.sleep(0.05)
    assert len(polls(fake)) == 1 and not poller.polling

    _, new = new_token()
    async with session_factory() as session:  # what a reconnect stores
        await session.execute(update(Bot).where(Bot.id == bot.id).values(tg_token_enc=encrypt_token(new)))
        await session.commit()
    await poller.sync_once()
    await eventually(lambda: polls(telegram(new)))
    assert bot.id in poller.polling


async def test_a_token_revoked_before_start_is_recorded_from_delete_webhook(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    class TokenGone(FakeTelegramClient):
        async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
            self.calls.append(("deleteWebhook", {"drop_pending_updates": drop_pending_updates}))
            raise TelegramError("deleteWebhook", "Not Found", error_code=404)

    fake = telegram.by_token[bot.token] = TokenGone()
    poller = make_poller(bot.id)
    await poller.sync_once()

    async def recorded() -> bool:
        return (await row(session_factory, bot.id)).tg_last_error == "deleteWebhook: Not Found"

    await eventually(recorded)
    await eventually(lambda: not poller.polling)
    assert polls(fake) == []


async def test_rate_limit_waits_exactly_retry_after(
    bot: LiveBot, telegram: Telegram, sleeps: Sleeps, make_poller: Callable[..., TelegramPoller]
) -> None:
    fake = telegram(bot.token)
    fake.get_updates_errors.append(
        TelegramError("getUpdates", "Too Many Requests: retry after 37", error_code=429, retry_after=37.0)
    )
    fake.push_updates(message_update(811, 741, "/start"))
    await make_poller(bot.id).sync_once()
    await eventually(lambda: sent_texts(fake, 741))
    assert sleeps.waits[0] == 37.0


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        (1e9, [300.0, 300.0]),  # capped: a bot is never deaf for more than 5 minutes per answer
        (0.0, [1.0, 1.0]),  # floored: never a tight loop
        (float("inf"), [1.0, 2.0]),  # unusable values are an ordinary, growing backoff
        (float("nan"), [1.0, 2.0]),
        (-5.0, [1.0, 2.0]),
        ("10", [1.0, 2.0]),
    ],
)
async def test_rate_limit_retry_after_is_bounded_and_invalid_values_back_off(
    retry_after: Any,
    expected: list[float],
    bot: LiveBot,
    telegram: Telegram,
    sleeps: Sleeps,
    make_poller: Callable[..., TelegramPoller],
) -> None:
    fake = telegram(bot.token)
    limited = TelegramError("getUpdates", "Too Many Requests", error_code=429, retry_after=retry_after)
    fake.get_updates_errors.extend([limited, limited])
    fake.push_updates(message_update(812, 742, "/start"))
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: sent_texts(fake, 742))  # still polling afterwards
    assert sleeps.waits[:2] == expected
    assert bot.id in poller.polling


async def test_a_batch_without_progress_never_spins(
    bot: LiveBot,
    telegram: Telegram,
    sleeps: Sleeps,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    """An update without a usable update_id cannot be confirmed: alone it would come straight back,
    so every refetch is preceded by a growing wait. A later valid id confirms it."""
    fake = telegram(bot.token)
    bad = {"update_id": "x", "message": {"text": "/start"}}
    fake.push_updates(bad)
    await make_poller(bot.id).sync_once()
    await eventually(lambda: len(sleeps.waits) >= 4)
    assert sleeps.waits[:4] == [1.0, 2.0, 4.0, 8.0]
    assert len(polls(fake)) <= len(sleeps.waits) + 1  # never two fetches without a wait between

    fake.push_updates(message_update(1201, 791, "/start"))  # a valid id after it
    await eventually(lambda: sent_texts(fake, 791))

    async def saved() -> bool:
        return (await row(session_factory, bot.id)).tg_poll_offset == 1202

    await eventually(saved)
    waits = len(sleeps.waits)
    await eventually(lambda: any(c["offset"] == 1202 for c in polls(fake)))
    await asyncio.sleep(0.1)  # idle long polls follow, with no further waits
    assert len(sleeps.waits) == waits and fake.pending_updates == []


async def test_network_errors_and_5xx_back_off_exponentially_and_success_resets(
    bot: LiveBot, telegram: Telegram, sleeps: Sleeps, make_poller: Callable[..., TelegramPoller]
) -> None:
    fake = telegram(bot.token)
    server_error = TelegramError("getUpdates", "Bad Gateway", error_code=502)
    fake.get_updates_errors.extend([NETWORK] * 5 + [server_error] * 3)
    fake.push_updates(message_update(821, 751, "/start"))
    await make_poller(bot.id).sync_once()
    await eventually(lambda: sent_texts(fake, 751))
    assert sleeps.waits[:8] == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]  # rng=1.0: the full delay

    fake.get_updates_errors.append(NETWORK)
    await eventually(lambda: len(sleeps.waits) >= 9)
    assert sleeps.waits[8] == 1.0  # the successful poll reset the backoff


# --- connect, disconnect, token change -------------------------------------------------------------


@pytest.fixture
def polling_env(monkeypatch: pytest.MonkeyPatch, tg_env: None) -> Iterator[None]:
    """Polling mode on a machine Telegram cannot reach: PUBLIC_BASE_URL is plain http on localhost."""
    monkeypatch.setenv("TELEGRAM_MODE", "polling")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_connect_in_polling_mode_deletes_the_webhook_and_needs_no_public_url(
    polling_env: None,
    tg_client: httpx.AsyncClient,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot = await make_live_bot(session_factory, capacity_spec(golden_spec, 1))
    async with session_factory() as session:
        await session.execute(
            update(Bot).where(Bot.id == bot.id).values(tg_poll_offset=999, tg_last_error="old error")
        )
        await session.commit()
    _, token = new_token()
    response = await tg_client.post(f"/bots/{bot.id}/telegram/connect", json={"token": token}, headers=ALICE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connected"] is True and body["owner_linked"] is False and body["owner_link"]
    assert fake_tg.calls_to("setWebhook") == []
    assert fake_tg.calls_to("deleteWebhook")[0] == {"drop_pending_updates": True}  # like connect's setWebhook
    stored = await row(session_factory, bot.id)
    assert stored.status == "live" and stored.tg_webhook_secret not in (None, bot.secret)
    assert stored.tg_poll_offset is None and stored.tg_last_error is None
    assert stored.owner_link_code and stored.owner_link_code != bot.owner_link_code


async def test_an_offset_saved_while_a_reconnect_runs_does_not_carry_over_to_the_new_token(
    polling_env: None,
    bot: LiveBot,
    tg_client: httpx.AsyncClient,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The previous token's poller saves an offset after connect has read the bot row; the new token
    must still start from no offset (update ids belong to one Telegram bot)."""
    old_enc = (await row(session_factory, bot.id)).tg_token_enc
    get_me = fake_tg.get_me

    async def poller_saves_meanwhile() -> dict[str, Any]:
        async with session_factory() as session:  # exactly the poller's compare-and-set save
            await session.execute(
                update(Bot).where(Bot.id == bot.id, Bot.tg_token_enc == old_enc).values(tg_poll_offset=777)
            )
            await session.commit()
        return await get_me()

    monkeypatch.setattr(fake_tg, "get_me", poller_saves_meanwhile)
    _, token = new_token()
    response = await tg_client.post(f"/bots/{bot.id}/telegram/connect", json={"token": token}, headers=ALICE)
    assert response.status_code == 200, response.text
    assert (await row(session_factory, bot.id)).tg_poll_offset is None


async def test_connect_in_polling_mode_fails_cleanly_when_delete_webhook_fails(
    polling_env: None,
    tg_client: httpx.AsyncClient,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot = await make_live_bot(session_factory, capacity_spec(golden_spec, 1))
    before = await row(session_factory, bot.id)
    fake_tg.fail_methods["deleteWebhook"] = "Bad Request"
    _, token = new_token()
    response = await tg_client.post(f"/bots/{bot.id}/telegram/connect", json={"token": token}, headers=ALICE)
    assert response.status_code == 502 and response.json()["error"]["code"] == "telegram_error"
    after = await row(session_factory, bot.id)
    assert (after.tg_token_enc, after.tg_webhook_secret) == (before.tg_token_enc, before.tg_webhook_secret)


async def test_webhook_mode_connect_is_unchanged(
    tg_client: httpx.AsyncClient, fake_tg: FakeTelegramClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot("alice")  # never connected: no previous webhook to remove
    _, token = new_token()
    response = await tg_client.post(f"/bots/{bot_id}/telegram/connect", json={"token": token}, headers=ALICE)
    assert response.status_code == 200
    # connect also asks whether another server serves this Telegram bot (webhook info, then a probe)
    assert [name for name, _ in fake_tg.calls] == [
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "setWebhook",
        "setMyCommands",
        "setChatMenuButton",
    ]
    assert fake_tg.calls_to("setWebhook")[0]["drop_pending_updates"] is True


async def test_disconnect_stops_the_poller_and_nothing_more_is_handled(
    polling_env: None,
    bot: LiveBot,
    tg_client: httpx.AsyncClient,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: polls(fake))

    assert (await tg_client.delete(f"/bots/{bot.id}/telegram", headers=ALICE)).status_code == 200
    # An update that reaches the running task before the supervisor's next pass is left alone: the
    # task sees the token is gone and stops.
    fake.push_updates(message_update(901, 761, "/start"))
    await eventually(lambda: not poller.polling)
    await poller.sync_once()
    assert not poller.polling
    assert 901 not in await seen_updates(session_factory, bot.id) and fake.sent_to(761) == []


async def test_disconnect_is_noticed_by_the_supervisor_while_the_bot_is_idle(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    fake.poll_wait = 30  # a long poll in progress
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: polls(fake))
    async with session_factory() as session:
        await session.execute(update(Bot).where(Bot.id == bot.id).values(tg_token_enc=None))
        await session.commit()
    await asyncio.wait_for(poller.sync_once(), 5)  # the long poll is abandoned, not waited for
    assert not poller.polling


async def test_a_reconnect_with_a_new_token_restarts_polling_with_it(
    polling_env: None,
    bot: LiveBot,
    tg_client: httpx.AsyncClient,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    poller = make_poller(bot.id)
    await poller.sync_once()
    await eventually(lambda: polls(telegram(bot.token)))
    old_enc = poller.polling[bot.id]

    _, token = new_token()
    response = await tg_client.post(f"/bots/{bot.id}/telegram/connect", json={"token": token}, headers=ALICE)
    assert response.status_code == 200, response.text
    await poller.sync_once()
    assert poller.polling[bot.id] not in (None, old_enc)
    fresh = telegram(token)
    fresh.push_updates(message_update(5, 771, "/start"))  # the new bot's own, lower update ids
    await eventually(lambda: sent_texts(fresh, 771))
    assert polls(fresh)[0]["offset"] is None and fresh.calls[0][0] == "deleteWebhook"

    async def saved() -> bool:
        return (await row(session_factory, bot.id)).tg_poll_offset == 6

    await eventually(saved)


# --- the owner link through polling ------------------------------------------------------------------


async def test_the_owner_link_works_through_polling_and_a_code_never_replaces_an_owner(
    bot: LiveBot,
    telegram: Telegram,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
) -> None:
    fake = telegram(bot.token)
    fake.push_updates(message_update(1001, 900, f"/start owner_{bot.owner_link_code}"))
    await make_poller(bot.id).sync_once()
    await eventually(lambda: sent_texts(fake, 900))
    assert sent_texts(fake, 900)[-1] == texts.OWNER_LINKED
    linked = await row(session_factory, bot.id)
    assert (linked.owner_actor_id, linked.owner_link_code) == ("900", None)

    fake.push_updates(message_update(1002, 901, f"/start owner_{bot.owner_link_code}"))  # used code
    await eventually(lambda: sent_texts(fake, 901))
    assert sent_texts(fake, 901)[-1] == texts.OWNER_LINK_INVALID

    async with session_factory() as session:  # a code left armed beside a linked owner
        await session.execute(update(Bot).where(Bot.id == bot.id).values(owner_link_code="leftover-code"))
        await session.commit()
    fake.push_updates(message_update(1003, 902, "/start owner_leftover-code"))
    await eventually(lambda: sent_texts(fake, 902))
    assert sent_texts(fake, 902)[-1] == texts.OWNER_LINK_INVALID
    assert (await row(session_factory, bot.id)).owner_actor_id == "900"


# --- secrets -------------------------------------------------------------------------------------------


async def test_a_polling_cycle_logs_no_token(
    bot: LiveBot,
    make_poller: Callable[..., TelegramPoller],
    session_factory: SessionFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The real client over a stub transport, with httpx's request logging forced on (worst case):
    an update, a 5xx, a network error whose message holds the URL, then a revoked token."""
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="httpx")
    script = iter(["update", "5xx", "network", "401"])
    requests: list[httpx.Request] = []

    def telegram_api(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        method = request.url.path.rsplit("/", 1)[-1]
        if method != "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        step = next(script)
        if step == "update":
            return httpx.Response(200, json={"ok": True, "result": [message_update(1101, 781, "/start")]})
        if step == "5xx":
            return httpx.Response(502, json={"ok": False, "error_code": 502, "description": "Bad Gateway"})
        if step == "network":
            raise httpx.ConnectError(f"cannot reach {request.url}", request=request)
        return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(telegram_api)) as http:

        def real_client(token: str) -> TelegramApi:
            return TelegramClient(token, http=http)

        poller = make_poller(bot.id, provider=real_client)
        await poller.sync_once()

        async def stopped() -> bool:
            return (await row(session_factory, bot.id)).tg_last_error == "getUpdates: Unauthorized"

        await eventually(stopped)
        await eventually(lambda: not poller.polling)

    assert any(bot.token in r.url.path for r in requests)  # the token really was in every URL
    assert "HTTP Request" in caplog.text  # httpx did log its request lines...
    assert bot.token not in caplog.text  # ...and none of them kept the token
    assert bot.token.split(":", 1)[1] not in caplog.text
    assert "[REDACTED]" in caplog.text


# --- lifespan and the re-registration script ---------------------------------------------------------


async def test_webhook_mode_starts_no_poller(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch, tg_env: None
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.delenv("TELEGRAM_MODE", raising=False)
    get_settings.cache_clear()

    def no_poller(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("webhook mode must not start the poller")

    monkeypatch.setattr(poller_module, "start_polling", no_poller)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.telegram_poller is None


async def test_polling_mode_starts_the_poller_with_the_app_and_stops_it_on_shutdown(
    bot: LiveBot,
    telegram: Telegram,
    sleeps: Sleeps,
    session_factory: SessionFactory,
    migrated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_db)
    monkeypatch.setenv("TELEGRAM_MODE", "polling")
    get_settings.cache_clear()
    real_start = poller_module.start_polling

    def start_for_this_test(sessions: Any) -> TelegramPoller:
        return real_start(session_factory, telegram, sleep=sleeps, bot_ids=[bot.id])

    monkeypatch.setattr(poller_module, "start_polling", start_for_this_test)
    fake = telegram(bot.token)
    fake.poll_wait = 30  # shutdown must not wait for a long poll
    app = create_app()
    async with app.router.lifespan_context(app):
        poller = app.state.telegram_poller
        assert isinstance(poller, TelegramPoller)
        await eventually(lambda: polls(fake))
        assert bot.id in poller.polling
        tasks = [run.task for run in poller._runs.values()]
        supervisor = poller._supervisor
    assert tasks and all(task.done() for task in tasks)  # every task ended when the app shut down
    assert supervisor is not None and supervisor.done()


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "reregister_webhooks_polling", BACKEND / "scripts" / "reregister_webhooks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_reregister_webhooks_has_nothing_to_do_in_polling_mode(
    polling_env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)  # touching the database would refuse (exit 2)
    get_settings.cache_clear()
    script = _load_script()
    fake = FakeTelegramClient()
    assert await script.run(None, False, provider=fake.provider) == 0
    assert "nothing to re-register" in capsys.readouterr().out
    assert fake.calls == [] and fake.tokens == []


# --- migration 0004 ------------------------------------------------------------------------------------


@pytest.fixture
def scratch_db(test_db_url: str) -> Iterator[str]:
    name = f"migration_{uuid.uuid4().hex[:12]}"

    async def admin(statement: str) -> None:
        engine = create_async_engine(test_db_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.exec_driver_sql(statement)
        await engine.dispose()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(test_db_url).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_migration_0004_adds_and_removes_the_poll_offset(scratch_db: str) -> None:
    async def columns() -> set[str]:
        engine = create_async_engine(scratch_db, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'app' AND table_name = 'bots'"
                )
            )
            found = set(rows.scalars())
        await engine.dispose()
        return found

    _alembic(scratch_db, "upgrade", "head")
    assert "tg_poll_offset" in asyncio.run(columns())
    _alembic(scratch_db, "downgrade", "0003")
    assert "tg_poll_offset" not in asyncio.run(columns())
    _alembic(scratch_db, "upgrade", "head")
