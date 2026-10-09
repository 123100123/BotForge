"""Small async Telegram Bot API client (roadmap K15: httpx directly, a handful of methods, no framework).

Security: the bot token lives in the request URL (``/bot<token>/<method>``, and for file downloads
``/file/bot<token>/<path>``). It is held only in a private attribute of the client, is never part of
an exception message or a log line written here, and exception text for transport failures is built
from the exception *type* only (httpx messages can echo the URL). The ``httpx`` loggers are raised to
WARNING because their INFO lines contain the URL; the log-redaction filter (``app.security.redact``)
is the second line of defense.

Behavior: short timeouts; one retry on a network error and on HTTP 429 (sleeping ``retry_after``
seconds, only when it is small enough not to stall a webhook request). Telegram's ``description``
travels in ``TelegramError`` so callers can show or record it. ``get_updates`` (polling mode, see
``poller.py``) is the exception: a long poll whose read timeout exceeds its ``timeout``, with no
retry of its own, because the poller owns the backoff and ``retry_after`` handling for it.

File downloads (``get_file`` + ``download_file``, the Telegram document path): the file path that
``getFile`` returns is checked against a strict pattern before it is put into a URL (so it can never
reach another API path with the token), the download goes through the same pooled httpx client (and
so the same proxy settings) to the fixed API host, never follows a redirect, asks for and accepts only
an unencoded body (no decompression bombs), is refused on a declared ``Content-Length`` over the cap,
is cut off as soon as the streamed bytes pass the cap (``TelegramFileTooLarge``), and is bounded by
one wall-clock timeout. Nothing of the content is logged.
"""

import asyncio
import contextlib
import logging
import math
import re
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.integrations.telegram.platforms import API_BASES, DEFAULT_PLATFORM, Platform, as_platform

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_RETRY_AFTER = 5.0  # seconds; a longer 429 is raised instead of stalling the caller
# The update types BotForge handles (app.api.webhook); setWebhook and getUpdates ask for exactly these.
# ``my_chat_member``: the bot was added to or removed from a group or channel (``bot_chats``).
ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]
# Lower-cased part of Telegram's 409 description when a second getUpdates consumer ended this one
# ("Conflict: terminated by other getUpdates request; make sure that only one bot instance is
# running"). The other 409, "can't use getUpdates method while webhook is active", is not a competitor.
COMPETING_POLLER = "terminated by other getupdates request"
# getUpdates holds the request open for up to its ``timeout``; the read timeout must exceed that.
LONG_POLL_GRACE = 15.0
# answerCallbackQuery allows 200 characters of toast text; stay below it.
MAX_TOAST_CHARS = 180
# File downloads: one wall-clock limit for the whole transfer (connect, headers and every chunk).
DOWNLOAD_TIMEOUT_SECONDS = 60.0
DOWNLOAD_TIMEOUT = httpx.Timeout(DOWNLOAD_TIMEOUT_SECONDS, connect=5.0)
DOWNLOAD_METHOD = "downloadFile"  # the name download errors carry (not a Bot API method)
MAX_FILE_PATH_CHARS = 256
# What getFile returns, e.g. "documents/file_12.xlsx": relative segments of a conservative alphabet.
_FILE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")

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


class TelegramFileTooLarge(TelegramError):
    """A download refused or cut off because the file is larger than the caller's ``max_bytes``."""


def toast_text(text: str | None) -> str | None:
    """Toast text for ``answerCallbackQuery``: ``None`` for nothing to show, else at most
    ``MAX_TOAST_CHARS`` characters (plain text: the toast has no parse mode, nothing is escaped)."""
    if text is None or not text.strip():
        return None
    text = text.strip()
    return text if len(text) <= MAX_TOAST_CHARS else text[: MAX_TOAST_CHARS - 1] + "…"


def valid_file_path(path: object) -> bool:
    """Whether ``path`` (from ``getFile``) is safe to put after ``/file/bot<token>/``: relative, of
    the conservative alphabet, no empty, ``.`` or ``..`` segment, bounded length."""
    return (
        isinstance(path, str)
        and len(path) <= MAX_FILE_PATH_CHARS
        and _FILE_PATH.fullmatch(path) is not None
        and all(segment not in (".", "..") for segment in path.split("/"))
    )


class TelegramApi(Protocol):
    """What the rest of the backend needs from Telegram (or Bale, ``platform``). Implemented by the
    real and fake clients."""

    platform: Platform

    async def get_me(self) -> dict[str, Any]: ...

    async def set_webhook(
        self, url: str, secret_token: str | None, *, drop_pending_updates: bool = True
    ) -> None: ...

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None: ...

    async def get_webhook_info(self) -> dict[str, Any]: ...

    async def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: list[str], limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def send_message(
        self, chat_id: int | str, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def edit_message_text(
        self, chat_id: int | str, message_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None: ...

    async def set_my_commands(
        self, commands: list[dict[str, str]], scope: dict[str, Any] | None = None
    ) -> None: ...

    async def set_chat_menu_button(
        self, chat_id: int | None = None, menu_button: dict[str, Any] | None = None
    ) -> None: ...

    async def get_file(self, file_id: str) -> str: ...

    async def download_file(self, file_path: str, max_bytes: int) -> bytes: ...


# Builds a client for a bot token on a platform: ``provider(token, platform)``. Dependency-injected so
# tests can substitute the fake.
TelegramProvider = Callable[[str, Platform], TelegramApi]

_shared_http: httpx.AsyncClient | None = None


def shared_http_client() -> httpx.AsyncClient:
    """One pooled httpx client for all bots (the token is per request, never per client)."""
    global _shared_http
    if _shared_http is None or _shared_http.is_closed:
        _shared_http = httpx.AsyncClient(timeout=TIMEOUT)
    return _shared_http


class TelegramClient:
    """The Bot API client for Telegram and for Bale (``platform``; see ``platforms.py`` for what
    differs: the host, ``setWebhook``'s parameters, no ``parse_mode``)."""

    def __init__(
        self, token: str, *, platform: Platform = DEFAULT_PLATFORM, http: httpx.AsyncClient | None = None
    ) -> None:
        self.__token = token  # name-mangled on purpose: keeps it out of casual vars() dumps
        self.platform: Platform = as_platform(platform)
        self._api = API_BASES[self.platform]
        self._http = http

    @property
    def _bale(self) -> bool:
        return self.platform == "bale"

    def __repr__(self) -> str:
        return f"TelegramClient({self.platform}, <token hidden>)"

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
        url = f"{self._api}/bot{self.__token}/{method}"
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
            retry_after = parse_retry_after(params.get("retry_after"))
            if response.status_code == 429 and attempt == 1:
                wait = retry_after if retry_after is not None else 1.0
                if wait <= MAX_RETRY_AFTER:
                    log.warning("telegram %s rate limited; retrying after %.1fs", method, wait)
                    await asyncio.sleep(wait)
                    continue
            raise TelegramError(
                method,
                description,
                error_code=_error_code(body.get("error_code"), response.status_code),
                retry_after=retry_after,
            )
        raise AssertionError("unreachable")  # pragma: no cover

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe")

    async def set_webhook(
        self, url: str, secret_token: str | None, *, drop_pending_updates: bool = True
    ) -> None:
        """Connect keeps the default (a fresh connect must not replay old updates); moving a bot to a
        new hostname passes False so updates queued meanwhile are delivered afterwards. Bale takes
        ``url`` only: its secret is part of the URL and nothing else is sent."""
        if self._bale:
            await self._call("setWebhook", {"url": url})
            return
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
        connect passes True, as the webhook-mode connect's setWebhook drops them. Bale: no parameters."""
        if self._bale:
            await self._call("deleteWebhook")
            return
        await self._call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    async def get_webhook_info(self) -> dict[str, Any]:
        """The bot's webhook as Telegram holds it; ``url`` is empty when none is set. Used by connect to
        see whether another server already serves the bot."""
        result = await self._call("getWebhookInfo")
        return result if isinstance(result, dict) else {}

    async def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: list[str], limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Long poll: Telegram answers when an update arrives or after ``timeout`` seconds. Passing
        ``offset`` confirms every update below it (connect's probe passes none, so nothing is
        confirmed, and ``limit=1``). Fails with error code 409 while a webhook is set, and for the
        older of two concurrent consumers ("terminated by other getUpdates request")."""
        payload: dict[str, Any] = {"timeout": timeout}
        if not self._bale:  # not documented by Bale
            payload["allowed_updates"] = allowed_updates
        if offset is not None:
            payload["offset"] = offset
        if limit is not None:
            payload["limit"] = limit
        read_timeout = httpx.Timeout(timeout + LONG_POLL_GRACE, connect=5.0)
        result = await self._call("getUpdates", payload, timeout=read_timeout, retry=False)
        return [u for u in result if isinstance(u, dict)] if isinstance(result, list) else []

    async def send_message(
        self, chat_id: int | str, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if not self._bale:  # Bale has no parse_mode (always Markdown; see render_text)
            payload["parse_mode"] = "HTML"
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
        }
        if not self._bale:
            payload["parse_mode"] = "HTML"
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._call("editMessageText", payload)

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        """Stop the button's spinner; with ``text``, show it as a toast (or an alert) to the presser
        only. The text is cut to ``MAX_TOAST_CHARS``."""
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        toast = toast_text(text)
        if toast is not None:
            payload["text"] = toast
            if show_alert:
                payload["show_alert"] = True
        await self._call("answerCallbackQuery", payload)

    async def set_my_commands(
        self, commands: list[dict[str, str]], scope: dict[str, Any] | None = None
    ) -> None:
        """``setMyCommands``: the command list Telegram shows in the chat's command menu. ``commands``
        are ``{"command", "description"}`` dicts; ``scope`` is a ``BotCommandScope`` object (for
        example ``{"type": "chat", "chat_id": 1}``), ``None`` meaning the default scope."""
        payload: dict[str, Any] = {"commands": commands}
        if scope is not None:
            payload["scope"] = scope
        await self._call("setMyCommands", payload)

    async def set_chat_menu_button(
        self, chat_id: int | None = None, menu_button: dict[str, Any] | None = None
    ) -> None:
        """``setChatMenuButton``: the button next to the message box. Without ``chat_id`` it is the
        default for every private chat; ``menu_button`` defaults to ``{"type": "commands"}`` (opens the
        command list)."""
        payload: dict[str, Any] = {"menu_button": menu_button or {"type": "commands"}}
        if chat_id is not None:
            payload["chat_id"] = chat_id
        await self._call("setChatMenuButton", payload)

    async def get_file(self, file_id: str) -> str:
        """The ``file_path`` to download ``file_id`` with. ``TelegramError`` when Telegram has none
        (for example a file over the 20 MB bot download limit) or it is not a safe relative path."""
        result = await self._call("getFile", {"file_id": file_id})
        path = result.get("file_path") if isinstance(result, dict) else None
        if not valid_file_path(path):
            raise TelegramError("getFile", "no usable file path")
        return path  # type: ignore[return-value]  # checked by valid_file_path

    async def download_file(self, file_path: str, max_bytes: int) -> bytes:
        """The bytes of ``file_path`` (from ``get_file``), at most ``max_bytes`` of them (see the
        module docstring). Raises ``TelegramFileTooLarge`` past the cap and ``TelegramError`` for
        anything else; neither carries the token or the URL."""
        if not valid_file_path(file_path):
            raise TelegramError(DOWNLOAD_METHOD, "invalid file path")
        http = self._http or shared_http_client()
        url = f"{self._api}/file/bot{self.__token}/{file_path}"
        chunks: list[bytes] = []
        total = 0
        try:
            async with (
                asyncio.timeout(DOWNLOAD_TIMEOUT_SECONDS),
                http.stream(
                    "GET",
                    url,
                    headers={"Accept-Encoding": "identity"},
                    timeout=DOWNLOAD_TIMEOUT,
                    follow_redirects=False,
                ) as response,
            ):
                if response.status_code != 200:
                    raise TelegramError(
                        DOWNLOAD_METHOD, f"HTTP {response.status_code}", error_code=response.status_code
                    )
                encoding = response.headers.get("content-encoding", "").strip().lower()
                if encoding not in ("", "identity"):
                    raise TelegramError(DOWNLOAD_METHOD, "unexpected content encoding")
                declared = response.headers.get("content-length", "").strip()
                if declared.isascii() and declared.isdigit() and int(declared) > max_bytes:
                    raise TelegramFileTooLarge(DOWNLOAD_METHOD, "file too large", error_code=413)
                # identity only (checked above), so these are the bytes as sent: nothing is inflated
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise TelegramFileTooLarge(DOWNLOAD_METHOD, "file too large", error_code=413)
                    chunks.append(chunk)
        except TimeoutError:
            raise TelegramError(DOWNLOAD_METHOD, "timed out", network=True) from None
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # type name only: httpx messages may include the request URL, which holds the token
            description = f"network error ({type(exc).__name__})"
            raise TelegramError(DOWNLOAD_METHOD, description, network=True) from None
        return b"".join(chunks)


def parse_retry_after(value: Any) -> float | None:
    """Telegram's ``retry_after`` as a finite, non-negative number of seconds, else ``None``.

    The body is untrusted JSON, and ``json.loads`` accepts ``Infinity`` and ``NaN``: ``sleep(nan)``
    never returns, so anything that is not a plain finite number (a bool, a string, inf, nan, a
    negative value) is treated as absent."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    seconds = float(value)
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _error_code(value: Any, status: int) -> int:
    """Telegram's ``error_code`` when it is a plain int, else the HTTP status."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value else status


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def default_provider(token: str, platform: Platform = DEFAULT_PLATFORM) -> TelegramApi:
    return TelegramClient(token, platform=platform)


def get_telegram_provider() -> TelegramProvider:
    """FastAPI dependency; tests override it with ``FakeTelegramClient.provider``."""
    return default_provider


class FakeTelegramClient:
    """Records every call; never touches the network. Shared by all bots in a test.

    ``calls`` holds ``(method, kwargs)`` tuples in order; ``tokens`` the tokens the provider was
    asked for and ``platforms`` the platform of each request; ``platform`` is the latest one (or the
    constructor's), which is what the outbound text is rendered for. ``fail_methods`` maps a method
    name to the ``TelegramError`` description to raise.

    Polling: ``push_updates`` queues updates for ``get_updates``, which behaves like Telegram's
    (an ``offset`` confirms and drops every queued update below it; with nothing queued it waits up
    to ``poll_wait`` seconds for a push, a stand-in for the long poll). ``get_updates_errors`` are
    raised by the next calls, one per call, before anything is returned.

    Files: ``files`` maps a ``file_id`` to the canned bytes ``download_file`` serves (``get_file``
    of an unknown id fails like Telegram's); ``download_file`` enforces ``max_bytes`` like the real
    client (``TelegramFileTooLarge``). Both are recorded (``getFile``, ``downloadFile``).
    """

    def __init__(
        self, *, bot_id: int = 424242, username: str = "fake_bot", platform: Platform = DEFAULT_PLATFORM
    ) -> None:
        self.platform: Platform = platform
        self.platforms: list[str] = []
        self.bot_id = bot_id
        self.username = username
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tokens: list[str] = []
        self.fail_methods: dict[str, str] = {}
        self.get_me_error: TelegramError | None = None
        self.pending_updates: list[dict[str, Any]] = []
        self.get_updates_errors: list[Exception] = []
        self.webhook_url = ""  # what get_webhook_info reports (set by tests; set_webhook leaves it)
        self.poll_wait = 0.05
        self.files: dict[str, bytes] = {}
        self._file_paths: dict[str, str] = {}  # file_path handed out by get_file -> file_id
        self._pushed = asyncio.Event()
        self._message_id = 1000

    def push_updates(self, *updates: dict[str, Any]) -> None:
        self.pending_updates.extend(updates)
        self._pushed.set()

    # --- provider / inspection helpers -------------------------------------------------------

    def provider(self, token: str, platform: Platform = DEFAULT_PLATFORM) -> "FakeTelegramClient":
        self.tokens.append(token)
        self.platforms.append(platform)
        self.platform = platform
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

    async def set_webhook(
        self, url: str, secret_token: str | None, *, drop_pending_updates: bool = True
    ) -> None:
        self._record(
            "setWebhook", url=url, secret_token=secret_token, drop_pending_updates=drop_pending_updates
        )

    async def delete_webhook(self, *, drop_pending_updates: bool = False) -> None:
        self._record("deleteWebhook", drop_pending_updates=drop_pending_updates)

    async def get_webhook_info(self) -> dict[str, Any]:
        self._record("getWebhookInfo")
        return {"url": self.webhook_url, "pending_update_count": 0}

    async def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: list[str], limit: int | None = None
    ) -> list[dict[str, Any]]:
        extra = {} if limit is None else {"limit": limit}
        self._record("getUpdates", offset=offset, timeout=timeout, allowed_updates=allowed_updates, **extra)
        if self.get_updates_errors:
            raise self.get_updates_errors.pop(0)
        if offset is not None:  # confirmed: Telegram forgets them (a malformed id counts as earlier)
            self.pending_updates = [
                u
                for u in self.pending_updates
                if isinstance(u.get("update_id"), int) and u["update_id"] >= offset
            ]
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

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        self._record(
            "answerCallbackQuery",
            callback_query_id=callback_query_id,
            text=toast_text(text),
            show_alert=show_alert,
        )

    async def set_my_commands(
        self, commands: list[dict[str, str]], scope: dict[str, Any] | None = None
    ) -> None:
        self._record("setMyCommands", commands=commands, scope=scope)

    async def set_chat_menu_button(
        self, chat_id: int | None = None, menu_button: dict[str, Any] | None = None
    ) -> None:
        self._record("setChatMenuButton", chat_id=chat_id, menu_button=menu_button or {"type": "commands"})

    async def get_file(self, file_id: str) -> str:
        self._record("getFile", file_id=file_id)
        if file_id not in self.files:
            raise TelegramError("getFile", "Bad Request: invalid file_id", error_code=400)
        path = f"documents/file_{len(self._file_paths)}"
        self._file_paths[path] = file_id
        return path

    async def download_file(self, file_path: str, max_bytes: int) -> bytes:
        self._record(DOWNLOAD_METHOD, file_path=file_path, max_bytes=max_bytes)
        file_id = self._file_paths.get(file_path)
        if file_id is None:
            raise TelegramError(DOWNLOAD_METHOD, "HTTP 404", error_code=404)
        data = self.files[file_id]
        if len(data) > max_bytes:
            raise TelegramFileTooLarge(DOWNLOAD_METHOD, "file too large", error_code=413)
        return data
