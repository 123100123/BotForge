"""Telegram polling mode (``TELEGRAM_MODE=polling``): updates fetched with ``getUpdates``, outbound only.

For servers Telegram cannot reach (inbound connections from Telegram are blocked where the owner's
servers run; outbound calls work through ``HTTPS_PROXY``/``ALL_PROXY``). The webhook stays the
default. Started and stopped by the app lifespan (``app.main``); one backend process only, because
Telegram allows one ``getUpdates`` consumer per bot (the older of two gets 409).

Supervisor: every ``interval`` seconds it reads the bots with a stored token and keeps exactly one
poll task per bot and token. A bot that was disconnected, or whose stored token changed (every
connect re-encrypts, so a reconnect counts as a change), has its task stopped; the new token gets a
new task. A task that stopped on purpose (token revoked, token unreadable, parked) is not restarted until
the stored token changes (a parked one also when the owner retries, which clears the stored error to
NULL); one that crashed is restarted on the next pass. A parked task stays parked while any error is
stored: only the retry (error cleared), a token change or a process restart ends the park, never a
different error that overwrote the conflict one. The same loop deletes ``tg_updates`` rows older than
``UPDATES_KEEP`` once per ``PRUNE_INTERVAL``.

Per bot: ``deleteWebhook(drop_pending_updates=False)`` once (a leftover webhook makes getUpdates
fail with 409, and queued updates are kept), then sequential long polls. Every update goes through
``app.api.webhook.process_update``, the webhook's own path after authentication, strictly in order.

Offset (``bots.tg_poll_offset``): after an update has been handled (``process_update`` commits the
dedupe record and the dispatch before it returns), ``update_id + 1`` is saved, compare-and-set on
the token the task polls with, so a task whose bot was reconnected or disconnected meanwhile writes
nothing and stops. Telegram drops an update only when a later call passes a larger offset, and a
restart resumes from the saved offset. Replays are harmless: a crash between the handling and the
offset save makes Telegram return that update again, and ``process_update`` drops it as a
duplicate (``tg_updates``, committed before any work). The inherited limit is the webhook's: an
update whose processing dies half way (process killed) is recorded as seen and not retried.

Errors: network errors, 5xx and other failures back off exponentially with jitter (1 s doubling to
``BACKOFF_CAP``); 429 waits ``retry_after`` clamped to [1 s, 5 min] (a non-finite or invalid value is
an ordinary backoff step); 401 and 404 (token revoked or invalid) are recorded in
``bots.tg_last_error`` like delivery errors and stop the bot's polling until its token changes.

409 is told apart by Telegram's description. "Terminated by other getUpdates request" means another
consumer (typically a second BotForge server holding the same token) is polling: the two would take
turns serving updates, each against its own spec. The bot's task keeps the times of its recent
conflicts and parks at ``PARK_AFTER`` of them within ``PARK_WINDOW`` seconds (a sliding window, not
reset by successful polls: two competing servers each often get a good poll between two conflicts,
so a reset would let them keep splitting the updates; a successful poll only drops timestamps older
than the window, and a single stray 409, e.g. a previous process's long poll still open after a
restart, never parks). At the limit it parks:
it records ``tg_last_error = POLLING_CONFLICT: ...`` (Persian text, stable prefix the web app matches),
stops, and is not restarted until the stored token changes or the owner retries
(``POST /bots/{id}/telegram/retry`` clears the error; the next pass respawns the task). It never
calls ``deleteWebhook`` for this case: that would only help the other consumer. A 409 saying a
webhook is active keeps removing the webhook and backing off. A restarted process tries parked bots
again and clears a stale conflict error on its first successful poll.

Shutdown (``stop``): every task is asked to stop; a long poll or a wait is abandoned at once, an
update being handled is finished (up to ``stop_grace`` seconds, then the task is cancelled).

Secrets: the token is in every request URL. It is decrypted per task, handed only to the client
(which never logs it and keeps httpx's request logging at WARNING), and nothing here logs a URL,
a token or update content: only bot ids, update ids, method names and Telegram's descriptions.
"""

import asyncio
import logging
import random
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.webhook import process_update
from app.db.models import Bot, TgUpdate
from app.integrations.telegram import texts
from app.integrations.telegram.client import (
    ALLOWED_UPDATES,
    COMPETING_POLLER,
    TIMEOUT,
    TelegramApi,
    TelegramClient,
    TelegramError,
    TelegramProvider,
    parse_retry_after,
)
from app.security.crypto import TokenDecryptError, TokenKeyError, decrypt_token
from app.security.redact import redact
from app.services.dispatch import MAX_ERROR_CHARS

log = logging.getLogger(__name__)

POLL_TIMEOUT = 25  # seconds Telegram holds a getUpdates request open when there is nothing new
SUPERVISOR_INTERVAL = 10.0
BACKOFF_BASE = 1.0
BACKOFF_CAP = 60.0
STOP_GRACE = 15.0  # seconds a stopping task may take to finish the update it is handling
REVOKED = (401, 404)  # Telegram's answers for an invalid or revoked token
# A 429's retry_after is honoured within these bounds. The floor keeps a 0 from becoming a tight loop.
# The cap bounds how long one bot stays deaf to its customers: Telegram's flood waits for a single
# getUpdates consumer are seconds, a larger value is more likely a bad or hostile answer (it comes
# through the proxy), and asking again after 5 minutes costs one request, which just gets a new 429.
RETRY_AFTER_MIN = 1.0
RETRY_AFTER_CAP = 300.0
# Competing consumers: this many "terminated by other getUpdates request" 409s within PARK_WINDOW
# seconds park the bot, whatever successful polls happen in between (see the module docstring).
PARK_AFTER = 3
PARK_WINDOW = 60.0
# tg_updates is the webhook/poller dedupe record: Telegram never redelivers an update that old.
UPDATES_KEEP = timedelta(days=3)
PRUNE_INTERVAL = 3600.0

# Shown to the owner in Settings ("آخرین خطا: ..."), hence Persian.
TOKEN_UNREADABLE = (
    "توکن تلگرام در دسترس نیست؛ پیام‌های ربات دریافت نمی‌شوند. ربات را دوباره به تلگرام متصل کنید."
)

Sleep = Callable[[float], Awaitable[None]]
Outcome = Literal["crashed", "stopped", "parked"]


class _Parked(Exception):
    """Another consumer polls this bot's token: the task recorded the conflict and stops."""


class _Stale(Exception):
    """The bot was disconnected, reconnected or deleted: this task's token is no longer the stored one."""


class Backoff:
    """Exponential backoff with jitter: the n-th delay is between half and all of
    ``min(cap, base * 2**n)``. ``rng`` returns a float in [0, 1)."""

    def __init__(self, rng: Callable[[], float], *, base: float = BACKOFF_BASE, cap: float = BACKOFF_CAP):
        self._rng, self._base, self._cap = rng, base, cap
        self.failures = 0

    def next(self) -> float:
        ceiling = min(self._cap, self._base * 2**self.failures)
        self.failures = min(self.failures + 1, 32)
        return ceiling / 2 + self._rng() * ceiling / 2

    def reset(self) -> None:
        self.failures = 0


@dataclass
class _Run:
    """One bot's poll task and the stored token (encrypted) it polls with. The task's result is
    ``"crashed"`` (restart it), ``"stopped"`` (on purpose: wait for a new token) or ``"parked"``
    (a competing consumer: wait for a new token or the owner's retry)."""

    token_enc: str
    task: "asyncio.Task[Outcome]"
    stop: asyncio.Event

    def _outcome(self) -> Outcome | None:
        return self.task.result() if self.task.done() and not self.task.cancelled() else None

    @property
    def crashed(self) -> bool:
        return self._outcome() == "crashed"

    @property
    def parked(self) -> bool:
        return self._outcome() == "parked"


class TelegramPoller:
    """Polls every connected bot. ``sleep`` and ``rng`` are injectable so tests run without real waits;
    ``bot_ids`` limits the poller to those bots (tests share one database)."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        provider: TelegramProvider,
        *,
        sleep: Sleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        interval: float = SUPERVISOR_INTERVAL,
        poll_timeout: int = POLL_TIMEOUT,
        stop_grace: float = STOP_GRACE,
        bot_ids: Collection[uuid.UUID] | None = None,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._provider = provider
        self._sleep = sleep
        self._rng = rng
        self._interval = interval
        self._poll_timeout = poll_timeout
        self._stop_grace = stop_grace
        self._only = frozenset(bot_ids) if bot_ids is not None else None
        self._http = http  # owned: closed by ``stop``
        self._clock = clock
        self._last_prune: float | None = None
        self._runs: dict[uuid.UUID, _Run] = {}
        self._closing = asyncio.Event()
        self._supervisor: asyncio.Task[None] | None = None

    # --- supervisor -------------------------------------------------------------------------------

    def start(self) -> None:
        if self._supervisor is None:
            self._supervisor = asyncio.create_task(self._supervise(), name="telegram-poller")

    @property
    def polling(self) -> dict[uuid.UUID, str]:
        """Bot id -> encrypted token of every task still running (for status and tests)."""
        return {bot_id: run.token_enc for bot_id, run in self._runs.items() if not run.task.done()}

    async def _supervise(self) -> None:
        while not self._closing.is_set():
            try:
                await self.sync_once()
            except Exception:
                log.exception("telegram poller: supervisor pass failed; retrying")
            await self.prune_if_due()
            await self._wait(self._closing, self._interval)

    async def sync_once(self) -> None:
        """One supervisor pass: stop the tasks of bots whose stored token changed or went away, then
        start a task for every connected bot without one (or whose task crashed)."""
        connected = await self._connected_bots()
        changed = [
            bot_id
            for bot_id, run in self._runs.items()
            if bot_id not in connected or connected[bot_id][0] != run.token_enc
        ]
        await self._stop_runs(changed)
        for bot_id, (token_enc, last_error) in connected.items():
            run = self._runs.get(bot_id)
            # Only the owner's retry (error cleared) unparks: another error that overwrote the conflict
            # one must not (the parked task does not poll, so nothing would re-record the conflict).
            retried = run is not None and run.parked and last_error is None
            if run is not None and (run.crashed or retried):
                del self._runs[bot_id]
                run = None
            if run is None and not self._closing.is_set():
                self._runs[bot_id] = self._spawn(bot_id, token_enc)

    async def stop(self) -> None:
        """Stop the supervisor and every task (see the module docstring); close the owned client."""
        self._closing.set()
        if self._supervisor is not None:  # it ends its current pass (spawning nothing) and exits
            _, late = await asyncio.wait({self._supervisor}, timeout=2 * self._stop_grace)
            for task in late:
                task.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
        await self._stop_runs(list(self._runs))
        if self._http is not None:
            await self._http.aclose()

    async def prune_if_due(self) -> None:
        """Delete ``tg_updates`` rows older than ``UPDATES_KEEP``, at most once per ``PRUNE_INTERVAL``
        (one cheap indexed DELETE). A failure is logged and tried again on the next pass."""
        now = self._clock()
        if self._last_prune is not None and now - self._last_prune < PRUNE_INTERVAL:
            return
        try:
            async with self._sessions() as session:
                await session.execute(
                    delete(TgUpdate)
                    .where(TgUpdate.received_at < func.now() - UPDATES_KEEP)
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
        except Exception:
            log.exception("telegram poller: could not prune tg_updates")
            return
        self._last_prune = now

    async def _connected_bots(self) -> dict[uuid.UUID, tuple[str, str | None]]:
        """Bot id -> (encrypted token, last error) of every bot with a stored token."""
        query = select(Bot.id, Bot.tg_token_enc, Bot.tg_last_error).where(Bot.tg_token_enc.is_not(None))
        if self._only is not None:
            query = query.where(Bot.id.in_(self._only))
        async with self._sessions() as session:
            rows = (await session.execute(query)).all()
        return {row.id: (row.tg_token_enc, row.tg_last_error) for row in rows}

    def _spawn(self, bot_id: uuid.UUID, token_enc: str) -> _Run:
        stop = asyncio.Event()
        task = asyncio.create_task(self._run_bot(bot_id, token_enc, stop), name=f"telegram-poll-{bot_id}")
        return _Run(token_enc, task, stop)

    async def _stop_runs(self, bot_ids: list[uuid.UUID]) -> None:
        runs = [self._runs.pop(bot_id) for bot_id in bot_ids if bot_id in self._runs]
        for run in runs:
            run.stop.set()
        pending = [run.task for run in runs if not run.task.done()]
        if pending:
            _, late = await asyncio.wait(pending, timeout=self._stop_grace)
            for task in late:
                task.cancel()
            await asyncio.gather(*late, return_exceptions=True)

    # --- one bot ------------------------------------------------------------------------------------

    async def _run_bot(self, bot_id: uuid.UUID, token_enc: str, stop: asyncio.Event) -> Outcome:
        """The bot's task; its result says whether the supervisor may restart it."""
        try:
            await self._poll(bot_id, token_enc, stop)
        except _Parked:
            return "parked"
        except _Stale:
            log.info("bot %s: Telegram connection changed; its polling stopped", bot_id)
        except Exception:
            log.exception("bot %s: polling failed; restarting on the next supervisor pass", bot_id)
            return "crashed"
        return "stopped"

    async def _poll(self, bot_id: uuid.UUID, token_enc: str, stop: asyncio.Event) -> None:
        client = await self._client(bot_id, token_enc)
        if client is None:
            return
        offset = await self._load_offset(bot_id, token_enc)
        if not await self._remove_webhook(bot_id, token_enc, client):
            return
        log.info("bot %s: polling Telegram for updates", bot_id)
        backoff = Backoff(self._rng)
        conflicts: deque[float] = deque()  # when the recent competing-consumer 409s happened
        cleared = False
        while not stop.is_set():
            delay: float | None
            try:
                batch = await self._fetch(client, offset, stop)
            except TelegramError as exc:
                delay = await self._after_error(bot_id, token_enc, client, exc, backoff, conflicts)
                if delay is None:
                    return
            except Exception:
                log.exception("bot %s: getUpdates failed unexpectedly", bot_id)
                delay = backoff.next()
            else:
                if batch is None:  # asked to stop during the long poll
                    return
                if conflicts:  # never reset by success: only conflicts older than the window go
                    self._prune_conflicts(conflicts, self._clock())
                if not cleared:  # polling works: a conflict error left by an earlier run is stale
                    cleared = True
                    await self._clear_conflict(bot_id, token_enc)
                if not batch:  # the long poll ended with nothing new: Telegram already waited
                    backoff.reset()
                    continue
                before = offset
                try:
                    for tg_update in batch:
                        if stop.is_set():
                            return  # not confirmed: Telegram returns the rest after a restart
                        if _update_id(tg_update) is None:
                            # Skipped unhandled; a later valid id in the batch confirms it.
                            log.warning("bot %s: skipped a polled update without a valid update_id", bot_id)
                            continue
                        offset = await self._handle(bot_id, token_enc, tg_update, offset)
                except _Stale:
                    raise
                except Exception:  # the database failed: fetch again from the last saved offset
                    log.exception("bot %s: could not handle a polled update", bot_id)
                    delay = backoff.next()
                else:
                    if offset != before:
                        backoff.reset()
                        continue
                    # Nothing confirmed (no valid id, or only ids below the offset): the same batch
                    # would come straight back, so never poll again without a wait.
                    delay = backoff.next()
                    log.warning("bot %s: a polled batch made no progress; retrying in %.1fs", bot_id, delay)
            if await self._wait(stop, delay):
                return

    async def _client(self, bot_id: uuid.UUID, token_enc: str) -> TelegramApi | None:
        try:
            return self._provider(decrypt_token(token_enc))
        except TokenKeyError:
            log.error("TOKEN_ENC_KEY is missing or invalid; bot %s is not polled", bot_id)
        except TokenDecryptError:
            log.error("bot %s: the stored Telegram token cannot be decrypted; not polled", bot_id)
            await self._record_error(bot_id, token_enc, TOKEN_UNREADABLE)
        return None

    async def _load_offset(self, bot_id: uuid.UUID, token_enc: str) -> int | None:
        async with self._sessions() as session:
            row = (
                await session.execute(select(Bot.tg_token_enc, Bot.tg_poll_offset).where(Bot.id == bot_id))
            ).first()
        if row is None or row.tg_token_enc != token_enc:
            raise _Stale
        return row.tg_poll_offset

    async def _remove_webhook(self, bot_id: uuid.UUID, token_enc: str, client: TelegramApi) -> bool:
        """``deleteWebhook`` keeping queued updates. ``False`` when the token is revoked (recorded)."""
        try:
            await client.delete_webhook(drop_pending_updates=False)
        except TelegramError as exc:
            if exc.error_code in REVOKED:
                await self._revoked(bot_id, token_enc, exc)
                return False
            log.warning("bot %s: deleteWebhook failed: %s", bot_id, exc.description)
        return True

    async def _fetch(
        self, client: TelegramApi, offset: int | None, stop: asyncio.Event
    ) -> list[dict[str, Any]] | None:
        """One long poll; ``None`` when ``stop`` was set first (the request is abandoned)."""
        request = asyncio.ensure_future(
            client.get_updates(offset=offset, timeout=self._poll_timeout, allowed_updates=ALLOWED_UPDATES)
        )
        stopper = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({request, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopper.cancel()
            if not request.done():
                request.cancel()
            await asyncio.gather(request, stopper, return_exceptions=True)
        if request.cancelled():
            return None
        return request.result()

    async def _handle(
        self, bot_id: uuid.UUID, token_enc: str, tg_update: dict[str, Any], offset: int | None
    ) -> int | None:
        """Process one update (with a valid update_id) through the webhook's path, then save the next
        offset. Returns it."""
        update_id = _update_id(tg_update)
        if update_id is None:
            return offset
        async with self._sessions() as session:
            bot = await session.get(Bot, bot_id)
            if bot is None or bot.tg_token_enc != token_enc:
                raise _Stale
            await process_update(session, bot, tg_update, self._provider)  # commits; never raises
            next_offset = max(offset or 0, update_id + 1)
            saved = await session.execute(
                update(Bot)
                .where(Bot.id == bot_id, Bot.tg_token_enc == token_enc)
                .values(tg_poll_offset=next_offset)
                .returning(Bot.id)
                .execution_options(synchronize_session=False)
            )
            current = saved.first() is not None
            await session.commit()
        if not current:
            raise _Stale
        return next_offset

    async def _after_error(
        self,
        bot_id: uuid.UUID,
        token_enc: str,
        client: TelegramApi,
        exc: TelegramError,
        backoff: Backoff,
        conflicts: deque[float],
    ) -> float | None:
        """How long to wait after a failed getUpdates; ``None``: stop polling this bot. Raises
        ``_Parked`` when a competing consumer is confirmed."""
        if exc.error_code in REVOKED:
            await self._revoked(bot_id, token_enc, exc)
            return None
        if exc.error_code == 409 and COMPETING_POLLER in exc.description.lower():
            now = self._clock()
            conflicts.append(now)
            self._prune_conflicts(conflicts, now)
            if len(conflicts) >= PARK_AFTER:
                log.warning("bot %s: another consumer polls this token; parking the bot", bot_id)
                await self._record_error(bot_id, token_enc, texts.POLLING_CONFLICT)
                raise _Parked
            delay = backoff.next()
            log.warning("bot %s: getUpdates conflict with another consumer; retrying in %.1fs", bot_id, delay)
            return delay
        if exc.error_code == 409:  # a webhook is set: remove it
            log.warning("bot %s: getUpdates conflict (%s); deleting the webhook", bot_id, exc.description)
            if not await self._remove_webhook(bot_id, token_enc, client):
                return None
            return backoff.next()
        retry_after = parse_retry_after(exc.retry_after) if exc.error_code == 429 else None
        if retry_after is not None:
            wait = min(max(retry_after, RETRY_AFTER_MIN), RETRY_AFTER_CAP)
            log.warning("bot %s: getUpdates rate limited; waiting %.0fs", bot_id, wait)
            return wait
        delay = backoff.next()  # also a 429 without a usable retry_after
        log.warning("bot %s: getUpdates failed (%s); retrying in %.1fs", bot_id, exc.description, delay)
        return delay

    @staticmethod
    def _prune_conflicts(conflicts: deque[float], now: float) -> None:
        """Drop the conflict times older than ``PARK_WINDOW`` (the window slides; success never resets it)."""
        while conflicts and now - conflicts[0] > PARK_WINDOW:
            conflicts.popleft()

    async def _revoked(self, bot_id: uuid.UUID, token_enc: str, exc: TelegramError) -> None:
        log.warning(
            "bot %s: Telegram rejected the token (%s); polling stops until it is reconnected",
            bot_id,
            exc.description,
        )
        await self._record_error(bot_id, token_enc, redact(str(exc)))  # "<method>: <description>"

    async def _clear_conflict(self, bot_id: uuid.UUID, token_enc: str) -> None:
        """Drop a stale ``POLLING_CONFLICT`` error (one UPDATE per task, after its first good poll)."""
        try:
            async with self._sessions() as session:
                await session.execute(
                    update(Bot)
                    .where(
                        Bot.id == bot_id,
                        Bot.tg_token_enc == token_enc,
                        Bot.tg_last_error.like(f"{texts.POLLING_CONFLICT_PREFIX}%"),
                    )
                    .values(tg_last_error=None)
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
        except Exception:
            log.exception("bot %s: could not clear the polling conflict error", bot_id)

    async def _record_error(self, bot_id: uuid.UUID, token_enc: str, error: str) -> None:
        """Store ``error`` in ``bots.tg_last_error`` unless the bot's token changed meanwhile."""
        try:
            async with self._sessions() as session:
                await session.execute(
                    update(Bot)
                    .where(Bot.id == bot_id, Bot.tg_token_enc == token_enc)
                    .values(tg_last_error=error[:MAX_ERROR_CHARS])
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
        except Exception:
            log.exception("bot %s: could not record the Telegram error", bot_id)

    async def _wait(self, stop: asyncio.Event, seconds: float) -> bool:
        """Sleep ``seconds`` unless ``stop`` is set first. ``True`` when stopped."""
        if stop.is_set():
            return True
        sleeper = asyncio.ensure_future(self._sleep(seconds))
        waiter = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({sleeper, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (sleeper, waiter):
                task.cancel()
            await asyncio.gather(sleeper, waiter, return_exceptions=True)
        return stop.is_set()


def _update_id(tg_update: dict[str, Any]) -> int | None:
    """The update's ``update_id`` when it is a plain non-negative int (the offset is built from it)."""
    value = tg_update.get("update_id")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def start_polling(
    sessions: async_sessionmaker[AsyncSession],
    provider: TelegramProvider | None = None,
    **options: Any,
) -> TelegramPoller:
    """Create and start the poller (the lifespan calls this in polling mode). Without ``provider`` it
    uses the real client over its own httpx client, built like the shared one, so ``HTTPS_PROXY`` and
    ``ALL_PROXY`` apply; creating it raises if the proxy settings are unusable."""
    http: httpx.AsyncClient | None = None
    if provider is None:
        client = httpx.AsyncClient(timeout=TIMEOUT)
        http = client

        def real(token: str) -> TelegramApi:
            return TelegramClient(token, http=client)

        provider = real
    poller = TelegramPoller(sessions, provider, http=http, **options)
    poller.start()
    return poller
