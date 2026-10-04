"""Telegram token encryption and webhook-secret helpers."""

import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.security.crypto import (
    WEBHOOK_SECRET_PATTERN,
    TokenDecryptError,
    TokenKeyError,
    decrypt_token,
    encrypt_token,
    generate_webhook_secret,
    main,
    verify_webhook_secret,
)

BACKEND = Path(__file__).resolve().parents[3]
TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
SetKey = Callable[[str | None], None]


@pytest.fixture
def set_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[SetKey]:
    def apply(key: str | None) -> None:
        monkeypatch.setenv("TOKEN_ENC_KEY", key or "")
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


@pytest.fixture
def key(set_key: SetKey) -> str:
    value = Fernet.generate_key().decode()
    set_key(value)
    return value


def test_round_trip(key: str) -> None:
    stored = encrypt_token(TOKEN)
    assert decrypt_token(stored) == TOKEN
    assert TOKEN not in stored and TOKEN.split(":")[1] not in stored
    assert encrypt_token(TOKEN) != stored  # random IV: equal tokens do not look equal at rest


def test_wrong_key_fails_closed(key: str, set_key: SetKey) -> None:
    stored = encrypt_token(TOKEN)
    set_key(Fernet.generate_key().decode())
    with pytest.raises(TokenDecryptError) as info:
        decrypt_token(stored)
    assert TOKEN not in str(info.value) and stored not in str(info.value)


@pytest.mark.parametrize("value", ["", "garbage", "gAAAAA" + "A" * 80, "تو‌کن"])
def test_corrupted_values_fail_closed(key: str, value: str) -> None:
    with pytest.raises(TokenDecryptError):
        decrypt_token(value)


def test_tampered_ciphertext_fails_closed(key: str) -> None:
    stored = encrypt_token(TOKEN)
    tampered = stored[:-5] + ("A" if stored[-5] != "A" else "B") + stored[-4:]
    with pytest.raises(TokenDecryptError):
        decrypt_token(tampered)


def test_missing_key_fails_closed(set_key: SetKey) -> None:
    set_key(None)
    with pytest.raises(TokenKeyError, match="TOKEN_ENC_KEY is not set"):
        encrypt_token(TOKEN)
    with pytest.raises(TokenKeyError):
        decrypt_token("gAAAAA")


@pytest.mark.parametrize(
    "bad_key", ["not-a-fernet-key", "c2hvcnQ=", "A" * 43, Fernet.generate_key().decode()[:-2]]
)
def test_invalid_key_fails_closed_without_echoing_it(set_key: SetKey, bad_key: str) -> None:
    set_key(bad_key)
    with pytest.raises(TokenKeyError) as info:
        encrypt_token(TOKEN)
    assert bad_key not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_empty_token_is_refused(key: str) -> None:
    with pytest.raises(ValueError):
        encrypt_token("")


def test_generate_key_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate-key"]) == 0
    printed = capsys.readouterr().out.strip()
    Fernet(printed)  # a valid key
    assert main(["generate-key"]) == 0
    assert capsys.readouterr().out.strip() != printed


def test_generate_key_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.security.crypto", "generate-key"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    Fernet(result.stdout.strip())
    missing = subprocess.run(
        [sys.executable, "-m", "app.security.crypto"], cwd=BACKEND, capture_output=True, text=True, timeout=60
    )
    assert missing.returncode == 2  # a subcommand is required


def test_webhook_secret_fits_telegrams_charset_and_length() -> None:
    values = {generate_webhook_secret() for _ in range(200)}
    assert len(values) == 200
    for value in values:
        assert WEBHOOK_SECRET_PATTERN.fullmatch(value)
        assert re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value)


def test_verify_webhook_secret() -> None:
    secret = generate_webhook_secret()
    assert verify_webhook_secret(secret, secret)
    assert verify_webhook_secret(secret, str(secret))  # equal value, different object
    assert not verify_webhook_secret(secret, generate_webhook_secret())
    assert not verify_webhook_secret(secret, secret[:-1])
    assert not verify_webhook_secret(secret, secret + "x")
    assert not verify_webhook_secret(secret, secret.upper() if secret.upper() != secret else secret + "a")


@pytest.mark.parametrize(
    ("expected", "provided"),
    [
        (None, "x"),
        ("x", None),
        (None, None),
        ("", ""),
        ("", "x"),
        ("x", ""),
        ("abc", "é" * 3),
        ("abc", "\udcff"),
    ],
)
def test_verify_webhook_secret_is_false_for_missing_or_odd_values(
    expected: str | None, provided: str | None
) -> None:
    assert verify_webhook_secret(expected, provided) is False


def test_verify_webhook_secret_rejects_non_strings() -> None:
    assert verify_webhook_secret("abc", b"abc") is False  # type: ignore[arg-type]
    assert verify_webhook_secret(b"abc", "abc") is False  # type: ignore[arg-type]
