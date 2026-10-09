"""The notification ticker: one in-process task (``NOTIFICATIONS_TICKER=true``; off by default) that
every ``NOTIFICATIONS_TICK_SECONDS`` seconds

1. runs every generator (``generators.discover()``), each in its own transaction; a generator that
   raises is logged and rolled back and does not affect the others;
2. delivers due outbox rows: it claims a batch (``outbox.claim_due``, ``FOR UPDATE SKIP LOCKED``),
   sends it, records each result on its row and commits the batch, then claims the next, until
   nothing is due or the tick's time budget (one interval) is used up.

Throttling: at most ``NOTIFICATIONS_SEND_RATE_PER_SECOND`` sends per second over all bots, and at
most one per second to the same chat of the same bot (Telegram's per-chat limit). A 429 pauses that
bot for ``retry_after`` seconds (the row is requeued after it and the bot's other rows are not
claimed meanwhile).

Results (``outbox.mark_sent`` / ``mark_failed``): sandbox rows are marked sent without any Telegram
call, so the simulator never reaches Telegram. 400 and 403 (chat not found, bot blocked) fail the
row at once; other failures are retried with exponential backoff up to ``outbox.MAX_ATTEMPTS``.
Errors are logged (bot id, row id, ``<method>: <description>``) and kept in the row's
``last_error``; ``bots.tg_last_error`` is never written, because it reports the owner's own
interaction with the bot in Settings, not background sends.

One process only, like the poller: a second ticker would not double-send (claims skip locked rows)
but would double the throttle budgets. The bot token is decrypted per batch and handed only to the
client; nothing here logs a token or message text.
"""

import asyncio
import contextlib
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import Bot, OutboundMessageRow
from app.integrations.telegram.adapter import client_platform, render_text, reply_markup
from app.integrations.telegram.client import (
    TelegramApi,
    TelegramError,
    TelegramProvider,
    default_provider,
    parse_retry_after,
)
from app.integrations.telegram.platforms import as_platform
from app.notifications import outbox
from app.notifications.generators import Generator, discover
from app.runtime.contracts import OutMessage
from app.security.crypto import TokenCryptoError, decrypt_token
from app.security.redact import redact

log = logging.getLogger(__name__)

PER_CHAT_INTERVAL = 1.0  # seconds between two sends to one chat
PERMANENT = (400, 403)  # retrying cannot help: bad chat or text, bot blocked or kicked
RETRY_AFTER_MIN = 1.0
RETRY_AFTER_CAP = 300.0
STOP_GRACE = 15.0
NO_TOKEN = "توکن تلگرام در دسترس نیست"
UNEXPECTED = "خطای غیرمنتظره در ارسال پیام"

Sleep = Callable[[float], Awaitable[None]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class NotificationTicker:
    """See the module docstring. ``sleep``, ``clock`` (monotonic seconds) and ``now`` are injectable
    so tests run without real waits; ``bot_ids`` limits delivery to those bots (tests share one
    database); ``generators`` replaces discovery."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        provider: TelegramProvider,
        settings: Settings | None = None,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utcnow,
        generators: Iterable[Generator] | None = None,
        bot_ids: Collection[uuid.UUID] | None = None,
        stop_grace: float = STOP_GRACE,
    ) -> None:
        settings = settings or get_settings()
        self._sessions = sessions
        self._provider = provider
        self._interval = float(settings.NOTIFICATIONS_TICK_SECONDS)
        self._rate = float(settings.NOTIFICATIONS_SEND_RATE_PER_SECOND)
        self._batch = max(1, int(settings.NOTIFICATIONS_SEND_RATE_PER_SECOND))
        self._sleep = sleep
        self._clock = clock
        self._now = now
        self._generators = list(generators) if generators is not None else discover()
        self._only = frozenset(bot_ids) if bot_ids is not None else None
        self._stop_grace = stop_grace
        self._closing = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._backlog = False  # the last delivery stopped at its time budget with rows still due
        self._next_slot = -math.inf  # earliest monotonic time of the next send (global rate)
        self._last_chat: dict[tuple[uuid.UUID, int], float] = {}
        self._paused: dict[uuid.UUID, float] = {}  # bot -> monotonic time its 429 wait ends

    # --- lifecycle ------------------------------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="notification-ticker")

    async def stop(self) -> None:
        """Finish the current batch (up to ``stop_grace`` seconds, then cancel) and exit."""
        self._closing.set()
        if self._task is None:
            return
        _, late = await asyncio.wait({self._task}, timeout=self._stop_grace)
        for task in late:
            task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while not self._closing.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("notification ticker: tick failed; retrying on the next one")
                self._backlog = False
            if not self._backlog:  # a tick that ran out of time with rows still due goes on at once
                await self._wait(self._interval)

    async def _wait(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._closing.wait(), timeout=seconds)

    # --- one tick -------------------------------------------------------------------------------

    async def tick(self) -> int:
        """Run the generators, then deliver what is due. Returns the number of Telegram sends."""
        await self.run_generators()
        return await self.deliver_due()

    async def run_generators(self) -> None:
        now = self._now()
        for generator in self._generators:
            try:
                async with self._sessions() as session:
                    await generator.generate(session, now)
                    await session.commit()
            except Exception:
                log.exception("notification generator %s failed; skipped this tick", generator.name)

    async def deliver_due(self) -> int:
        """Deliver due rows batch by batch until none is due or one interval has passed (then
        ``_backlog`` is set, so the run loop starts the next tick without waiting)."""
        delivered = 0
        self._backlog = False
        deadline = self._clock() + self._interval
        while not self._closing.is_set():
            async with self._sessions() as session:
                rows = await outbox.claim_due(
                    session, self._batch, only_bots=self._only, skip_bots=self._paused_bots()
                )
                if not rows:
                    break
                clients = await self._clients(session, {r.bot_id for r in rows if r.env == "live"})
                for row in rows:
                    delivered += await self._deliver(row, clients)
                await session.commit()
            if self._clock() >= deadline:
                self._backlog = True
                break
        return delivered

    # --- delivery -------------------------------------------------------------------------------

    def _paused_bots(self) -> set[uuid.UUID]:
        now = self._clock()
        self._paused = {bot_id: until for bot_id, until in self._paused.items() if until > now}
        return set(self._paused)

    async def _clients(
        self, session: AsyncSession, bot_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, TelegramApi | None]:
        """A client per bot, ``None`` (logged) when the bot has no usable token."""
        if not bot_ids:
            return {}
        rows = (
            await session.execute(select(Bot.id, Bot.tg_token_enc, Bot.platform).where(Bot.id.in_(bot_ids)))
        ).all()
        clients: dict[uuid.UUID, TelegramApi | None] = dict.fromkeys(bot_ids)
        for bot_id, token_enc, platform in rows:
            if not token_enc:
                log.warning("bot %s: no Telegram token; outbox messages not sent", bot_id)
                continue
            try:
                clients[bot_id] = self._provider(decrypt_token(token_enc), as_platform(platform))
            except TokenCryptoError as exc:
                log.error("bot %s: Telegram token unusable (%s); outbox not sent", bot_id, type(exc).__name__)
        return clients

    async def _deliver(self, row: OutboundMessageRow, clients: dict[uuid.UUID, TelegramApi | None]) -> int:
        """Send one claimed row and record the result on it. 1 when Telegram accepted it."""
        if row.env != "live":
            outbox.mark_sent(row, now=self._now())  # sandbox: never sent to Telegram
            return 0
        if row.bot_id in self._paused_bots():
            return 0  # left queued untouched; the bot is not claimed again until its wait ends
        client = clients.get(row.bot_id)
        if client is None:
            outbox.mark_failed(row, NO_TOKEN, now=self._now())
            return 0
        await self._throttle(row.bot_id, row.chat_id)
        try:
            message = OutMessage(to_actor_id=str(row.chat_id), text=row.text, buttons=row.buttons or [])
            text = render_text(message.text, client_platform(client))
            await client.send_message(row.chat_id, text, reply_markup(message))
        except TelegramError as exc:
            self._failed(row, exc)
            return 0
        except Exception:
            log.exception("bot %s: outbox message %s could not be sent", row.bot_id, row.id)
            outbox.mark_failed(row, UNEXPECTED, now=self._now())
            return 0
        outbox.mark_sent(row, now=self._now())
        return 1

    def _failed(self, row: OutboundMessageRow, exc: TelegramError) -> None:
        error = redact(str(exc))  # "<method>: <description>"
        log.warning("bot %s: outbox message %s failed: %s", row.bot_id, row.id, error)
        if exc.error_code == 429:
            retry_after = parse_retry_after(exc.retry_after)
            wait = min(max(retry_after if retry_after is not None else 0.0, RETRY_AFTER_MIN), RETRY_AFTER_CAP)
            self._paused[row.bot_id] = self._clock() + wait
            outbox.mark_failed(row, error, now=self._now(), retry_after=wait)
            return
        outbox.mark_failed(row, error, now=self._now(), permanent=exc.error_code in PERMANENT)

    async def _throttle(self, bot_id: uuid.UUID, chat_id: int) -> None:
        """Wait for the global rate and the per-chat interval, then take the send slot."""
        key = (bot_id, chat_id)
        ready = max(self._next_slot, self._last_chat.get(key, -math.inf) + PER_CHAT_INTERVAL)
        now = self._clock()
        if ready > now:
            await self._sleep(ready - now)
            now = max(self._clock(), ready)
        self._next_slot = now + 1.0 / self._rate
        self._last_chat[key] = now
        if len(self._last_chat) > 10_000:  # forget chats whose interval has long passed
            self._last_chat = {k: t for k, t in self._last_chat.items() if t > now - PER_CHAT_INTERVAL}


def start_ticker(
    sessions: async_sessionmaker[AsyncSession],
    provider: TelegramProvider | None = None,
    settings: Settings | None = None,
    **options: object,
) -> NotificationTicker:
    """Create and start the ticker (the lifespan calls this when ``NOTIFICATIONS_TICKER`` is on).
    Without ``provider`` it uses the real client on the shared httpx client, like dispatch."""
    ticker = NotificationTicker(sessions, provider or default_provider, settings, **options)  # type: ignore[arg-type]
    ticker.start()
    return ticker
