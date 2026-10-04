"""Log redaction: Telegram bot tokens, ``Bearer`` credentials and JWTs never reach log output.

``install_log_redaction()`` (called by ``create_app``) wraps the log-record factory, so
``RedactingFilter`` runs on every record of every logger at the moment the record is created. That
covers records propagating to handlers configured later (uvicorn's ``dictConfig``) and third-party
loggers such as ``httpx``, whose request lines contain ``/bot<token>/`` URLs. A filter attached to a
logger would miss propagated records; one attached to handlers would miss handlers added later.

This is a safety net. Code must still never log tokens, secrets, or headers: values without a
recognizable shape (webhook secrets, Fernet keys, an opaque credential logged apart from the word
"Bearer") cannot be caught here.
"""

import logging
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

# "Authorization: Bearer <credential>" (RFC 6750 b64token characters), any capitalization.
_BEARER = re.compile(r"\b(bearer)\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
# JWS compact serialization: a base64url header starting with '{"' ("eyJ"), payload, signature.
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
# Telegram bot token "<bot id>:<secret>", also inside /bot<token>/ URLs and with the colon encoded.
_TELEGRAM_TOKEN = re.compile(r"\d{6,}(?::|%3[Aa])[A-Za-z0-9_-]{30,}")

_formatter = logging.Formatter()


def redact(text: str) -> str:
    """``text`` with every token-shaped substring replaced by ``[REDACTED]``."""
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    return _TELEGRAM_TOKEN.sub(REDACTED, text)


def _redact_arg(value: Any) -> Any:
    """A redacted string argument; an object whose ``str()`` holds a secret (e.g. an ``httpx.URL``
    with ``/bot<token>/``) becomes its redacted string; anything else is returned unchanged."""
    if isinstance(value, str):
        return redact(value)
    if value is None or isinstance(value, int | float):
        return value
    try:
        text = str(value)
    except Exception:
        return value  # getMessage() fails the same way; the malformed-call path handles it
    clean = redact(text)
    return clean if clean != text else value


def _redact_args(args: Any) -> Any:
    """Arguments redacted one by one. The container keeps its shape and length because custom
    formatters read it directly (uvicorn's access formatter unpacks the args tuple)."""
    if isinstance(args, tuple):
        return tuple(_redact_arg(a) for a in args)
    if isinstance(args, Mapping):
        return {k: _redact_arg(v) for k, v in args.items()}
    return args


def _printable(value: Any) -> str:
    try:
        return redact(str(value))
    except Exception:
        return "<unprintable>"


def _stringified_args(args: Any) -> Any:
    if isinstance(args, tuple):
        return tuple(_printable(a) for a in args)
    if isinstance(args, Mapping):
        return {k: _printable(v) for k, v in args.items()}
    return args


class RedactingFilter(logging.Filter):
    """Redacts a record's message, arguments, exception text and stack text. Never drops records."""

    def filter(self, record: logging.LogRecord) -> bool:
        # getMessage() would apply str() to a non-string message anyway; doing it here lets it be
        # redacted like any other message.
        record.msg = redact(record.msg if isinstance(record.msg, str) else _printable(record.msg))
        record.args = _redact_args(record.args)
        try:
            message = record.getMessage()
        except Exception:
            # A malformed logging call: Handler.handleError later prints msg and args verbatim.
            record.args = _stringified_args(record.args)
        else:
            # A JWT or bot token assembled from several pieces only shows in the formatted message;
            # then the record is collapsed to that message. Only these whitespace-free patterns are
            # checked here: the Bearer pattern spans whitespace and would match across arguments
            # (uvicorn's access line '"BEARER /x HTTP/1.1"'), and collapsing those arguments breaks
            # uvicorn's access formatter, so it is applied to each piece above instead.
            if _JWT.search(message) or _TELEGRAM_TOKEN.search(message):
                record.msg, record.args = redact(message), ()
        if record.exc_info and not record.exc_text:
            try:
                record.exc_text = _formatter.formatException(record.exc_info)
            except Exception:
                record.exc_text = "<traceback unavailable>"
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


_FILTER = RedactingFilter()


def install_log_redaction() -> None:
    """Redact every LogRecord created from now on, from any logger. Idempotent."""
    current = logging.getLogRecordFactory()
    if getattr(current, "_botforge_redacting", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        try:
            _FILTER.filter(record)
        except Exception:  # fail closed: lose the message rather than risk leaking it
            record.msg, record.args = "<log message dropped: redaction failed>", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return record

    factory._botforge_redacting = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
