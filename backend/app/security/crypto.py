"""Telegram bot-token encryption and webhook-secret helpers (roadmap: Security, Telegram).

Bot tokens are stored Fernet-encrypted with ``TOKEN_ENC_KEY`` and decrypted only inside the Telegram
client. A missing or invalid key fails closed with ``TokenKeyError``; a token is never stored or
returned in plaintext as a fallback. Error messages never contain key or token material.

Generate a key once per deployment and keep it with the other secrets::

    python -m app.security.crypto generate-key

Losing or changing the key makes the stored tokens undecryptable; owners then reconnect their bots.

Webhook secrets go to ``setWebhook(secret_token=...)`` and come back in the
``X-Telegram-Bot-Api-Secret-Token`` header; compare them only with ``verify_webhook_secret``.
"""

import argparse
import hmac
import re
import secrets
import sys

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken as FernetInvalidToken

from app.config import get_settings

# Telegram's allowed secret_token: 1-256 characters of A-Z, a-z, 0-9, "_" and "-".
WEBHOOK_SECRET_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,256}")


class TokenCryptoError(RuntimeError):
    """Base class. Messages never contain key or token material."""


class TokenKeyError(TokenCryptoError):
    """``TOKEN_ENC_KEY`` is missing or is not a valid Fernet key."""


class TokenDecryptError(TokenCryptoError):
    """The stored value was not produced with the configured key, or it is corrupted."""


def _fernet() -> Fernet:
    key = (get_settings().TOKEN_ENC_KEY or "").strip()
    if not key:
        raise TokenKeyError(
            "TOKEN_ENC_KEY is not set; generate one with `python -m app.security.crypto generate-key`"
        )
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise TokenKeyError("TOKEN_ENC_KEY is not a valid Fernet key (32 url-safe base64 bytes)") from None


def encrypt_token(token: str) -> str:
    """Encrypt a Telegram bot token for storage in ``bots.tg_token_enc``."""
    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(token_enc: str) -> str:
    """Decrypt a value produced by ``encrypt_token``; ``TokenDecryptError`` if it cannot be."""
    fernet = _fernet()
    if not isinstance(token_enc, str) or not token_enc:
        raise TokenDecryptError("stored Telegram token is empty or not a string")
    try:
        return fernet.decrypt(token_enc.encode("ascii")).decode("utf-8")
    except (FernetInvalidToken, UnicodeError):
        raise TokenDecryptError(
            "stored Telegram token cannot be decrypted with TOKEN_ENC_KEY (wrong key or corrupted value)"
        ) from None


def generate_webhook_secret() -> str:
    """A fresh per-bot webhook secret: 43 characters of ``A-Za-z0-9_-`` (256 random bits)."""
    return secrets.token_urlsafe(32)


def verify_webhook_secret(expected: str | None, provided: str | None) -> bool:
    """Constant-time check of the ``X-Telegram-Bot-Api-Secret-Token`` header against the stored
    secret. False when either value is missing or empty."""
    if not isinstance(expected, str) or not isinstance(provided, str) or not expected or not provided:
        return False
    try:
        # Bytes, not str: compare_digest rejects non-ASCII str, and the header is attacker-controlled.
        return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))
    except UnicodeError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.security.crypto", description="Telegram token encryption helpers."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate-key", help="print a new random TOKEN_ENC_KEY (a Fernet key)")
    args = parser.parse_args(argv)
    if args.command == "generate-key":
        print(Fernet.generate_key().decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
