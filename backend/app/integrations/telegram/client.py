"""Small async Telegram Bot API client (roadmap K15: httpx directly, seven methods, no framework).

Security: the bot token lives in the request URL (``/bot<token>/<method>``). It is held only in a
private attribute of the client, is never part of an exception message or a log line written here,
and exception text for transport failures is built from the exception *type* only (httpx messages
can echo the URL). The ``httpx`` loggers are raised to WARNING because their INFO lines contain the
URL; the log-redaction filter (``app.security.redact``) is the second line of defense.

Behavior: short timeouts; one retry on a network error and on HTTP 429 (sleeping ``retry_after``
seconds, only when it is small enough not to stall a webhook request). Telegram's ``description``
travels in ``TelegramError`` so callers can show or record it. ``get_updates`` (polling mode, see
``poller.py``) is the exception: a long poll whose read timeout exceeds its ``timeout``, with no
retry of its own, because the poller owns the backoff and ``retry_after`` handling for it.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any, Protocol

import httpx

API_BASE = "https://api.telegram.org"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_RETRY_AFTER = 5.0  # seconds; a longer 429 is raised instead of stalling the caller
# The update types BotForge handles (app.api.webhook); setWebhook and getUpdates ask for exactly these.
ALLOWED_UPDATES = ["message", "callback_query"]
# getUpdates holds the request open for up to its ``timeout``; the read timeout must exceed that.
LONG_POLL_GRACE = 15.0

log = logging.getLogger(__name__)
for _name in ("httpx", "httpcore"):  # their INFO request lines include the token-bearing URL
    logging.getLogger(_name).setLevel(logging.WARNING)


class TelegramError(Exception):
    """A failed Bot API call. ``str()`` is ``"<method>: <description>"``; never contains the token."""

    def __init__(
        self,
        method: str,
        description: str,
        *,
        error_code: int | None = None,
        retry_after: float | None = None,
        network: bool = False,
    ) -> None:
        super().__init__(f"{method}: {description}")
        self.method = method
        self.description = description
        self.error_code = error_code
        self.retry_after = retry_after
        self.network = network  # no HTTP answer from Telegram (timeout, DNS, connection)


class TelegramApi(Protocol):
    """What the rest of the backend needs from Telegram. Implemented by the real and fake clients."""

    async def get_me(self) -> dict[str, Any]: ...

    async def set_webhook(
        self, url: str, secret_token: str, *, drop_pending_updates: bool = True
    ) -> None: ...

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None: ...

    async def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: list[str]
    ) -> list[dict[str, Any]]: ...

    async def send_message(
        self, chat_id: int | str, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def edit_message_text(
        self, chat_id: int | str, message_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def answer_callback_query(self, callback_query_id: str) -> None: ...


# Builds a client for a bot token. Dependency-injected so tests can substitute the fake.
TelegramProvider = Callable[[str], TelegramApi]

_shared_http: httpx.AsyncClient | None = None


def shared_http_client() -> httpx.AsyncClient:
    """One pooled httpx client for all bots (the token is per request, never per client)."""
    global _shared_http
    if _shared_http is None or _shared_http.is_closed:
        _shared_http = httpx.AsyncClient(timeout=TIMEOUT)
    return _shared_http


class TelegramClient:
    def __init__(self, token: str, *, http: httpx.AsyncClient | None = None) -> None:
        self.__token = token  # name-mangled on purpose: keeps it out of casual vars() dumps
        self._http = http

    def __repr__(self) -> str:
        return "TelegramClient(<token hidden>)"

    async def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: httpx.Timeout | None = None,
        retry: bool = True,
    ) -> Any:
        """One Bot API call. ``timeout`` replaces the client's for this request; ``retry=False`` raises
        the first network error or 429 instead of retrying once (the poller backs off by itself)."""
        http = self._http or shared_http_client()
        url = f"{API_BASE}/bot{self.__token}/{method}"
        extra: dict[str, Any] = {"timeout": timeout} if timeout is not None else {}
        for attempt in (1, 2) if retry else (2,):
            try:
                response = await http.post(url, json=payload or {}, **extra)
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                # type name only: httpx messages may include the request URL
                if attempt == 1:
                    log.warning("telegram %s network error (%s); retrying once", method, type(exc).__name__)
                    continue
                raise TelegramError(method, f"network error ({type(exc).__name__})", network=True) from None
            body = _json(response)
            if response.status_code == 200 and body.get("ok") is True:
                return body.get("result")
            description = str(body.get("description") or f"HTTP {response.status_code}")
            params = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
            retry_after = params.get("retry_after")
            if response.status_code == 429 and attempt == 1:
                wait = float(retry_after) if isinstance(retry_after, int | float) else 1.0
                if wait <= MAX_RETRY_AFTER:
                    log.warning("telegram %s rate limited; retrying after %.1fs", method, wait)
                    await asyncio.sleep(wait)
                    continue
            raise TelegramError(
                method,
                description,
                error_code=int(body.get("error_code") or response.status_code),
                retry_after=float(retry_after) if isinstance(retry_after, int | float) else None,
            )
        raise AssertionError("unreachable")  # pragma: no cover

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe")

    async def set_webhook(self, url: str, secret_token: str, *, drop_pending_updates: bool = True) -> None:
        """Connect keeps the default (a fresh connect must not replay old updates); moving a bot to a
        new hostname passes False so updates queued meanwhile are delivered afterwards."""
        await self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ALLOWED_UPDATES,
                "drop_pending_updates": drop_pending_updates,
            },
        )

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        """Keeps queued updates by default (the poller then takes them with getUpdates). A polling-mode
        connect passes True, as the webhook-mode connect's setWebhook drops them."""
        await self._call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    async def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: list[str]
    ) -> list[dict[str, Any]]:
        """Long poll: Telegram answers when an update arrives or after ``timeout`` seconds. Passing
        ``offset`` confirms every update below it. Fails with error code 409 while a webhook is set."""
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": allowed_updates}
        if offset is not None:
            payload["offset"] = offset
        read_timeout = httpx.Timeout(timeout + LONG_POLL_GRACE, connect=5.0)
        result = await self._call("getUpdates", payload, timeout=read_timeout, retry=False)
        return [u for u in result if isinstance(u, dict)] if isinstance(result, list) else []

    async def send_message(
        self, chat_id: int | str, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._call("sendMessage", payload)

    async def edit_message_text(
        self, chat_id: int | str, message_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._call("editMessageText", payload)

    async def answer_callback_query(self, callback_query_id: str) -> None:
        await self._call("answerCallbackQuery", {"callback_query_id": callback_query_id})


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def default_provider(token: str) -> TelegramApi:
    return TelegramClient(token)


def get_telegram_provider() -> TelegramProvider:
    """FastAPI dependency; tests override it with ``FakeTelegramClient.provider``."""
    return default_provider


class FakeTelegramClient:
    """Records every call; never touches the network. Shared by all bots in a test.

    ``calls`` holds ``(method, kwargs)`` tuples in order; ``tokens`` the tokens the provider was
    asked for. ``fail_methods`` maps a method name to the ``TelegramError`` description to raise.

    Polling: ``push_updates`` queues updates for ``get_updates``, which behaves like Telegram's
    (an ``offset`` confirms and drops every queued update below it; with nothing queued it waits up
    to ``poll_wait`` seconds for a push, a stand-in for the long poll). ``get_updates_errors`` are
    raised by the next calls, one per call, before anything is returned.
    """

    def __init__(self, *, bot_id: int = 424242, username: str = "fake_bot") -> None:
        self.bot_id = bot_id
        self.username = username
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tokens: list[str] = []
        self.fail_methods: dict[str, str] = {}
        self.get_me_error: TelegramError | None = None
        self.pending_updates: list[dict[str, Any]] = []
        self.get_updates_errors: list[Exception] = []
        self.poll_wait = 0.05
        self._pushed = asyncio.Event()
        self._message_id = 1000

    def push_updates(self, *updates: dict[str, Any]) -> None:
        self.pending_updates.extend(updates)
        self._pushed.set()

    # --- provider / inspection helpers -------------------------------------------------------

    def provider(self, token: str) -> "FakeTelegramClient":
        self.tokens.append(token)
        return self

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == method]

    def sent_to(self, chat_id: int | str) -> list[dict[str, Any]]:
        return [k for n, k in self.calls if n == "sendMessage" and str(k["chat_id"]) == str(chat_id)]

    def _record(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))
        description = self.fail_methods.get(method)
        if description is not None:
            raise TelegramError(method, description, error_code=400)

    # --- TelegramApi ---------------------------------------------------------------------------

    async def get_me(self) -> dict[str, Any]:
        self.calls.append(("getMe", {}))
        if self.get_me_error is not None:
            raise self.get_me_error
        return {"id": self.bot_id, "is_bot": True, "username": self.username, "first_name": "Fake"}

    async def set_webhook(self, url: str, secret_token: str, *, drop_pending_updates: bool = True) -> None:
        self._record(
            "setWebhook", url=url, secret_token=secret_token, drop_pending_updates=drop_pending_updates
        )

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        self._record("deleteWebhook", drop_pending_updates=drop_pending_updates)

    async def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: list[str]
    ) -> list[dict[str, Any]]:
        self._record("getUpdates", offset=offset, timeout=timeout, allowed_updates=allowed_updates)
        if self.get_updates_errors:
            raise self.get_updates_errors.pop(0)
        if offset is not None:  # confirmed: Telegram forgets them
            self.pending_updates = [u for u in self.pending_updates if u.get("update_id", 0) >= offset]
        if not self.pending_updates:
            self._pushed.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._pushed.wait(), self.poll_wait)
        return list(self.pending_updates)

    async def send_message(
        self, chat_id: int | str, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._record("sendMessage", chat_id=chat_id, text=text, reply_markup=reply_markup)
        self._message_id += 1
        return {"message_id": self._message_id}

    async def edit_message_text(
        self, chat_id: int | str, message_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._record(
            "editMessageText", chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )
        return {"message_id": message_id}

    async def answer_callback_query(self, callback_query_id: str) -> None:
        self._record("answerCallbackQuery", callback_query_id=callback_query_id)
