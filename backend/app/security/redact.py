"""Log redaction: Telegram bot tokens, session cookies, ``Bearer`` credentials and JWTs never reach
log output.

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
# The login session cookie ("bf_session=<token>", app.security.sessions), in a Cookie or Set-Cookie
# header or a query string.
_SESSION_COOKIE = re.compile(r"\b(bf_session=)[A-Za-z0-9_-]+")
# Telegram bot token "<bot id>:<secret>", also inside /bot<token>/ URLs and with the colon encoded.
# The match starts where the digit run starts and the quantifiers are possessive, so a long run of
# digits costs linear time (the unanchored form was quadratic: 32k digits took seconds).
_BOT_ID = r"(?<!\d)\d{6,}+"
_COLON = r"(?::|%3[Aa])"
_SECRET = r"[A-Za-z0-9_-]{30,}"
# What may sit around the colon when a token is typed or pasted into a sentence ("123456789 : AAH…"):
# horizontal spaces and invisible marks (zero-width characters and the bidi controls common in
# Persian text). Never a line break, so two lines are never joined into a token.
_GAP = r"[ \t\u00a0\u1680\u2000-\u200f\u202a-\u202f\u205f\u2060\u2066-\u2069\u3000\ufeff\u061c]*+"
_TELEGRAM_TOKEN = re.compile(_BOT_ID + _GAP + _COLON + _GAP + _SECRET)
# The same without gaps, for a formatted log message (see RedactingFilter): there a gap could join
# two arguments into a "token", e.g. a crafted request whose uvicorn access line reads
# '"1234567 :AAAA… HTTP/1.1"', and collapsing those arguments breaks uvicorn's access formatter.
_TELEGRAM_TOKEN_COMPACT = re.compile(_BOT_ID + _COLON + _SECRET)

_formatter = logging.Formatter()


def redact(text: str) -> str:
    """``text`` with every token-shaped substring replaced by ``[REDACTED]``."""
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    text = _SESSION_COOKIE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
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
            # A JWT, session cookie or bot token assembled from several pieces only shows in the
            # formatted message;
            # then the record is collapsed to that message. Only whitespace-free patterns are
            # checked here: the Bearer pattern and the spaced form of a bot token ("123456789 : AAH…")
            # span whitespace and would match across arguments (uvicorn's access line
            # '"BEARER /x HTTP/1.1"'), and collapsing those arguments breaks uvicorn's access
            # formatter, so they are applied to each piece above instead.
            if (
                _JWT.search(message)
                or _SESSION_COOKIE.search(message)
                or _TELEGRAM_TOKEN_COMPACT.search(message)
            ):
                record.msg, record.args = redact(message), ()
        if record.exc_info and not record.exc_text:
            try:
                record.exc_text = _formatter.formatException(record.exc_info)
            except Exception:
                record.exc_text = "<traceback unavailable>"
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        # The redacted text replaces the exception itself. Standard formatters print exc_text as is;
        # a formatter or handler that formats exc_info on its own (a JSON formatter, an error tracker
        # that also reads frame locals) would otherwise see the raw message and, say, a client's URL.
        record.exc_info = None
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
