"""Log redaction of Telegram tokens, Bearer credentials and JWTs."""

import io
import logging
import sys
from collections.abc import Iterator

import pytest
from uvicorn.logging import AccessFormatter

from app.main import create_app
from app.security.redact import REDACTED, RedactingFilter, install_log_redaction, redact
from tests.unit.security.tokens import mint, new_secret

TG_TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
JWT = mint(new_secret(), "HS256")


def record(msg: object, *args: object, exc_info: object = None) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args or None, exc_info)  # type: ignore[arg-type]


def filtered(rec: logging.LogRecord) -> logging.LogRecord:
    assert RedactingFilter().filter(rec) is True  # never drops a record
    return rec


def test_telegram_tokens() -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    assert redact(url) == f"https://api.telegram.org/bot{REDACTED}/sendMessage"
    assert redact(f"token={TG_TOKEN}") == f"token={REDACTED}"
    encoded = TG_TOKEN.replace(":", "%3A")
    assert redact(f"/connect?token={encoded}") == f"/connect?token={REDACTED}"


def test_bearer_credentials_any_case() -> None:
    assert redact("Authorization: Bearer abc.DEF-ghi_~+/=") == f"Authorization: Bearer {REDACTED}"
    assert redact("authorization: bearer opaque-refresh-token") == f"authorization: bearer {REDACTED}"
    assert (
        redact(f"headers={{'authorization': 'Bearer {JWT}'}}")
        == f"headers={{'authorization': 'Bearer {REDACTED}'}}"
    )


def test_jwts() -> None:
    assert redact(f"token {JWT} rejected") == f"token {REDACTED} rejected"
    header, payload, _ = JWT.split(".")
    assert redact(f"{header}.{payload}.") == REDACTED  # unsigned (alg: none) shape too


@pytest.mark.parametrize(
    "text",
    [
        "GET /bots/1b4e28ba-2fa1-11d2-883f-0016d3cca427/data/workshop 200",
        "module app.api.deps loaded; version 1.2.3",
        "12:30:45 bot 123456:short",
        "Persian: ربات پیدا نشد.",
        "",
    ],
)
def test_ordinary_text_is_untouched(text: str) -> None:
    assert redact(text) == text


def test_string_args_are_redacted_and_the_args_shape_is_kept() -> None:
    rec = filtered(record('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", f"/x?t={JWT}", "1.1", 200))
    assert isinstance(rec.args, tuple) and len(rec.args) == 5  # uvicorn's access formatter unpacks these
    assert rec.getMessage() == f'127.0.0.1:5000 - "GET /x?t={REDACTED} HTTP/1.1" 200'


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/connect?token={TG_TOKEN}"),
        ("GET", f"/r?jwt={JWT}"),
        ("BEARER", "/bots"),  # Bearer-looking text spanning two arguments must not break the line
        ("GET", "/x/bearer"),
    ],
)
def test_uvicorn_access_lines_keep_working(method: str, path: str) -> None:
    formatter = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    rec = filtered(record('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", method, path, "1.1", 404))
    line = formatter.format(rec)  # unpacks exactly five args
    assert line.startswith(f'127.0.0.1:5000 - "{method} /')
    assert line.endswith('HTTP/1.1" 404 Not Found')
    assert TG_TOKEN not in line and JWT not in line


def test_objects_holding_secrets_become_redacted_strings() -> None:
    class Url:  # like httpx.URL, which httpx logs at INFO for every request
        def __str__(self) -> str:
            return f"https://api.telegram.org/bot{TG_TOKEN}/getMe"

    rec = filtered(record("HTTP Request: %s %s %d", "POST", Url(), 200))
    assert isinstance(rec.args, tuple) and len(rec.args) == 3
    assert rec.getMessage() == f"HTTP Request: POST https://api.telegram.org/bot{REDACTED}/getMe 200"
    rec = filtered(record("headers=%s", {"authorization": f"Bearer {JWT}", "x": "1"}))
    assert JWT not in rec.getMessage() and "Bearer [REDACTED]" in rec.getMessage()
    rec = filtered(record({"token": TG_TOKEN}))  # a non-string message
    assert TG_TOKEN not in rec.getMessage()
    plain = object()
    assert filtered(record("value %s", plain)).args == (plain,)  # nothing secret: left alone


def test_tokens_assembled_from_several_pieces() -> None:
    bot_id, secret_part = TG_TOKEN.split(":")
    rec = filtered(record("token=%s:%s", bot_id, secret_part))
    assert rec.getMessage() == f"token={REDACTED}"
    header, payload, signature = JWT.split(".")
    rec = filtered(record("jwt=%s.%s.%s", header, payload, signature))
    assert JWT not in rec.getMessage()
    # Known limit: an opaque (non-JWT) credential passed separately from the word "Bearer" is not
    # recognizable as a secret. Supabase access tokens are JWTs and are caught on their own.
    rec = filtered(record("Bearer %s", JWT))
    assert rec.getMessage() == f"Bearer {REDACTED}"


def test_mapping_args() -> None:
    rec = filtered(record("token=%(token)s", {"token": TG_TOKEN}))
    assert rec.getMessage() == f"token={REDACTED}"


def test_malformed_logging_call_does_not_leak() -> None:
    class Opaque:
        def __str__(self) -> str:
            return TG_TOKEN

    rec = filtered(record("%d %d", JWT, Opaque()))
    assert rec.args is not None and TG_TOKEN not in repr(rec.args) and JWT not in repr(rec.args)


def test_exception_and_stack_text() -> None:
    try:
        raise ValueError(f"bad token {TG_TOKEN}")
    except ValueError:
        rec = record("failed", exc_info=sys.exc_info())
    rec.stack_info = f"Stack (most recent call last):\n  token={JWT}"
    filtered(rec)
    assert (
        rec.exc_text and "ValueError: bad token [REDACTED]" in rec.exc_text and TG_TOKEN not in rec.exc_text
    )
    assert JWT not in rec.stack_info
    output = logging.Formatter("%(message)s").format(rec)
    assert TG_TOKEN not in output and JWT not in output


@pytest.fixture
def pristine_factory() -> Iterator[None]:
    original = logging.getLogRecordFactory()
    logging.setLogRecordFactory(logging.LogRecord)
    try:
        yield
    finally:
        logging.setLogRecordFactory(original)


def test_install_covers_every_logger_and_is_idempotent(pristine_factory: None) -> None:
    install_log_redaction()
    factory = logging.getLogRecordFactory()
    install_log_redaction()
    assert logging.getLogRecordFactory() is factory

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    loggers = [logging.getLogger("httpx"), logging.getLogger("uvicorn.access"), logging.getLogger("app.x.y")]
    saved = [(lg.handlers[:], lg.level, lg.propagate) for lg in loggers]
    try:
        for lg in loggers:
            lg.handlers, lg.propagate = [handler], False
            lg.setLevel(logging.INFO)
            lg.info("calling https://api.telegram.org/bot%s/getMe with Bearer %s", TG_TOKEN, JWT)
        try:
            raise RuntimeError(TG_TOKEN)
        except RuntimeError:
            loggers[2].exception("boom")
    finally:
        for lg, (handlers, level, propagate) in zip(loggers, saved, strict=True):
            lg.handlers, lg.propagate = handlers, propagate
            lg.setLevel(level)
    output = stream.getvalue()
    assert output.count(REDACTED) >= 7
    assert TG_TOKEN not in output and JWT not in output


def test_create_app_installs_redaction(pristine_factory: None) -> None:
    create_app()
    assert getattr(logging.getLogRecordFactory(), "_botforge_redacting", False)
