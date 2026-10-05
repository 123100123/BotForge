"""Re-register every connected bot's Telegram webhook at the current PUBLIC_BASE_URL.

Usage (from backend/, with DATABASE_URL, TOKEN_ENC_KEY and the new PUBLIC_BASE_URL set):
    uv run python scripts/reregister_webhooks.py --dry-run          # show what would change
    uv run python scripts/reregister_webhooks.py                    # every connected bot
    uv run python scripts/reregister_webhooks.py --bot-id <uuid>    # one bot
In the backend container, which has the server's environment:
    docker compose exec backend python scripts/reregister_webhooks.py [--dry-run] [--bot-id <uuid>]

Run it after PUBLIC_BASE_URL changes (for example from an sslip.io host name to the real domain) and
the server runs with the new value. A bot's webhook is ``{PUBLIC_BASE_URL}/tg/{bot_id}`` and only
``connect`` registers it; reconnecting would also rotate the webhook secret and unlink the bot's
owner. This script moves the webhooks instead: for every bot with a stored Telegram token it calls
setWebhook with the new URL and the bot's EXISTING webhook secret. It never writes the token, the
secret, the linked owner or the owner-link code.

One line per bot: the bot id, the new webhook URL, then "ok" or the error. (The previous URL is not
shown: the Telegram client has no getWebhookInfo.) setWebhook is sent exactly as ``connect`` sends
it, so updates Telegram still holds for the old address are dropped.

* Success: ``bots.tg_last_error`` is cleared and the status is set the way ``connect`` sets it (a
  paused bot stays paused; otherwise live with an active revision, draft without one).
* Failure (revoked token, Telegram unreachable, unreadable stored token): reported, and stored in
  ``bots.tg_last_error`` like a delivery error so the owner sees it in Settings; the status is not
  changed and the script goes on with the next bot.
* A bot its owner disconnects or reconnects while the script runs is left as that action left it
  and reported as failed; run the script again for it if it is still connected.

Exit status: 0 every bot ok (or none connected); 1 at least one bot failed; 2 refused to run because
PUBLIC_BASE_URL is not an https URL on a public host, TOKEN_ENC_KEY is unusable or decrypts none of
the stored tokens, DATABASE_URL is not set, or no HTTP client for Telegram can be created (proxy
settings). Nothing is called or written when the run is refused. Tokens and webhook secrets never
appear in the output or the log.
"""

import argparse
import asyncio
import logging
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Bot
from app.db.session import DatabaseNotConfigured, dispose_engine, get_sessionmaker
from app.integrations.telegram.client import (
    TIMEOUT,
    TelegramApi,
    TelegramClient,
    TelegramError,
    TelegramProvider,
)
from app.integrations.telegram.onboarding import (
    OnboardingError,
    status_after_connect,
    webhook_base_url,
    webhook_url,
)
from app.security.crypto import TokenCryptoError, TokenDecryptError, TokenKeyError, decrypt_token
from app.security.redact import install_log_redaction, redact
from app.services.dispatch import MAX_ERROR_CHARS

EXIT_OK = 0
EXIT_FAILED = 1  # at least one bot was not re-registered
EXIT_REFUSED = 2  # unusable configuration: nothing was called or written

# Stored in bots.tg_last_error, which the owner reads in Settings ("آخرین خطا: ..."), hence Persian.
# A Telegram error is stored as "<method>: <description>", exactly like a delivery error.
TOKEN_UNREADABLE = (
    "توکن تلگرام در دسترس نیست؛ آدرس جدید سرور در تلگرام ثبت نشد. ربات را دوباره به تلگرام متصل کنید."
)
SECRET_MISSING = (
    "اتصال تلگرام کامل نیست؛ آدرس جدید سرور در تلگرام ثبت نشد. ربات را دوباره به تلگرام متصل کنید."
)
UNEXPECTED = "خطای غیرمنتظره در ثبت آدرس جدید سرور در تلگرام"

CHANGED = (
    "the bot was disconnected, reconnected or deleted during the run, so nothing was stored; "
    "if it is still connected, run again with --bot-id {bot_id}"
)


@dataclass(frozen=True)
class Target:
    """A connected bot as read at the start of the run. The token and the secret stay out of repr."""

    id: uuid.UUID
    token_enc: str = field(repr=False)
    secret: str | None = field(repr=False)


@dataclass(frozen=True)
class Failure:
    report: str  # printed for the operator
    record: str  # stored in bots.tg_last_error for the owner


@dataclass(frozen=True)
class Outcome:
    ok: bool
    text: str  # what the bot's line says after the URL


def _say(line: str, *, err: bool = False) -> None:
    """Print through the log redaction: a safety net, nothing printed here should hold a secret."""
    print(redact(line), file=sys.stderr if err else sys.stdout)


def _refuse(reason: str) -> int:
    _say(f"refusing to run: {reason}. Nothing was called or changed.", err=True)
    return EXIT_REFUSED


async def reregister_webhooks(
    sessions: async_sessionmaker[AsyncSession],
    telegram: Callable[[], TelegramProvider],
    *,
    public_base_url: str,
    bot_id: uuid.UUID | None = None,
    dry_run: bool = False,
) -> int:
    """Move the webhooks of the connected bots (only ``bot_id``, if given) to ``public_base_url``.

    Prints one line per bot and returns the exit status. ``telegram()`` returns the provider that
    builds a Telegram client for a token (tests return the fake's); it is called once, after every
    check has passed, and never in a dry run. ``dry_run`` calls nothing and writes nothing.
    """
    try:
        base = webhook_base_url(public_base_url)
    except OnboardingError:
        return _refuse(f"PUBLIC_BASE_URL must be an https URL on a public host, not {public_base_url!r}")

    targets = await _connected_bots(sessions, bot_id)
    if not targets:
        if bot_id is None:
            _say("no bot is connected to Telegram; nothing to do")
            return EXIT_OK
        _say(f"bot {bot_id} does not exist or is not connected to Telegram; nothing to do", err=True)
        return EXIT_FAILED

    # One key serves every bot. When it opens none of the stored tokens, the key is wrong (or
    # missing), not the bots: refuse, rather than tell every owner to reconnect, which unlinks owners.
    try:
        if not any(_decryptable(target) for target in targets):
            stored = f"{len(targets)} stored token(s)"
            return _refuse(f"TOKEN_ENC_KEY decrypts none of the {stored}; is it the server's key?")
    except TokenKeyError:
        return _refuse("TOKEN_ENC_KEY is missing or is not a valid key")

    provider: TelegramProvider = _no_telegram
    if not dry_run:
        try:
            provider = telegram()
        except Exception as exc:  # e.g. ALL_PROXY=socks5://... without httpx's socks support
            # An environment problem, not a bot's: refuse rather than record it on every bot.
            return _refuse(
                f"cannot create the HTTP client for Telegram ({type(exc).__name__}); "
                "check the proxy settings (HTTPS_PROXY, ALL_PROXY)"
            )

    mode = "dry run: nothing is called or written" if dry_run else "re-registering"
    _say(f"{len(targets)} connected bot(s); new webhook URLs are {base}/tg/<bot id> ({mode})")
    failed = 0
    for target in targets:
        url = webhook_url(base, target.id)
        outcome = await _move(sessions, provider, target, url, dry_run=dry_run)
        failed += not outcome.ok
        _say(f"{target.id}  {url}  {outcome.text}")
    succeeded = len(targets) - failed
    if dry_run:
        _say(f"dry run: {succeeded} would be re-registered, {failed} would fail")
    else:
        _say(f"{succeeded} ok, {failed} failed")
    return EXIT_FAILED if failed else EXIT_OK


async def _connected_bots(
    sessions: async_sessionmaker[AsyncSession], bot_id: uuid.UUID | None
) -> list[Target]:
    """Every bot with a stored token (what ``status_of`` calls connected), oldest first."""
    query = select(Bot.id, Bot.tg_token_enc, Bot.tg_webhook_secret).where(Bot.tg_token_enc.is_not(None))
    if bot_id is not None:
        query = query.where(Bot.id == bot_id)
    async with sessions() as session:
        rows = (await session.execute(query.order_by(Bot.created_at, Bot.id))).all()
    return [Target(row.id, row.tg_token_enc, row.tg_webhook_secret) for row in rows]


def _decryptable(target: Target) -> bool:
    """Whether the stored token decrypts (the plaintext is dropped). ``TokenKeyError`` propagates."""
    try:
        decrypt_token(target.token_enc)
    except TokenDecryptError:
        return False
    return True


def _credentials(target: Target) -> tuple[str, str] | Failure:
    """The decrypted token and the stored webhook secret, or why they cannot be used."""
    try:
        token = decrypt_token(target.token_enc)
    except TokenCryptoError:
        return Failure(
            "the stored token cannot be decrypted with TOKEN_ENC_KEY; the owner must reconnect the bot",
            TOKEN_UNREADABLE,
        )
    if not target.secret:
        return Failure("no webhook secret is stored; the owner must reconnect the bot", SECRET_MISSING)
    return token, target.secret


async def _move(
    sessions: async_sessionmaker[AsyncSession],
    provider: TelegramProvider,
    target: Target,
    url: str,
    *,
    dry_run: bool,
) -> Outcome:
    credentials = _credentials(target)
    if dry_run:
        if isinstance(credentials, Failure):
            return Outcome(False, f"dry run: would fail: {credentials.report}")
        return Outcome(True, "dry run: would re-register")

    if isinstance(credentials, Failure):
        failure: Failure | None = credentials
    else:
        failure = await _set_webhook(provider, url, *credentials)

    try:
        stored = await _record(sessions, target, failure)
    except Exception as exc:  # the database failed for this bot; the next one may still work
        done = "the webhook was moved" if failure is None else failure.report
        return Outcome(False, f"error: {done}, but the result could not be stored ({type(exc).__name__})")
    if not stored:
        changed = CHANGED.format(bot_id=target.id)
        detail = changed if failure is None else f"{failure.report}; {changed}"
        return Outcome(False, f"error: {detail}")
    if failure is not None:
        return Outcome(False, f"error: {failure.report}")
    return Outcome(True, "ok")


async def _set_webhook(provider: TelegramProvider, url: str, token: str, secret: str) -> Failure | None:
    """``setWebhook`` with the bot's existing secret; ``None`` on success."""
    try:
        await provider(token).set_webhook(url, secret)
    except TelegramError as exc:
        error = redact(str(exc))  # "setWebhook: <Telegram's description>"; never holds the token
        if exc.network:
            return Failure(f"{error} (Telegram unreachable; run again later)", error)
        if exc.error_code in (401, 404):
            hint = "the token is revoked or invalid; the owner must reconnect the bot"
            return Failure(f"{error} ({hint})", error)
        return Failure(error, error)
    except Exception as exc:  # a bug must not stop the other bots; its message could hold anything
        return Failure(f"setWebhook: unexpected {type(exc).__name__}", UNEXPECTED)
    return None


async def _record(
    sessions: async_sessionmaker[AsyncSession], target: Target, failure: Failure | None
) -> bool:
    """Store the outcome on the bot; ``False``, storing nothing, when its connection changed meanwhile.

    The row is locked and compared with what was read at the start of the run: ``connect`` replaces
    the token and the secret and ``disconnect`` clears them, and the owner's action wins. Without
    this check a bot disconnected during the run would be marked live again. Only ``status`` and
    ``tg_last_error`` are written. The lock covers this read and write only, never a Telegram call.
    """
    async with sessions() as session:
        row = (
            await session.execute(select(Bot).where(Bot.id == target.id).with_for_update())
        ).scalar_one_or_none()
        if row is None or row.tg_token_enc != target.token_enc or row.tg_webhook_secret != target.secret:
            return False
        values: dict[str, str | None]
        if failure is None:
            values = {"status": status_after_connect(row), "tg_last_error": None}
        else:
            values = {"tg_last_error": failure.record[:MAX_ERROR_CHARS]}
        if any(getattr(row, column) != value for column, value in values.items()):
            await session.execute(
                update(Bot)
                .where(Bot.id == target.id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        await session.commit()
        return True


async def run(bot_id: uuid.UUID | None, dry_run: bool, provider: TelegramProvider | None = None) -> int:
    """The command: settings from the environment, the database engine and, when it comes to calling
    Telegram, one HTTP client for every call. ``provider`` replaces the real client (tests)."""
    clients: list[httpx.AsyncClient] = []

    def telegram() -> TelegramProvider:
        if provider is not None:
            return provider
        http = httpx.AsyncClient(timeout=TIMEOUT)  # honors HTTPS_PROXY / ALL_PROXY, like the server
        clients.append(http)
        return _telegram_over(http)

    try:
        return await reregister_webhooks(
            get_sessionmaker(),
            telegram,
            public_base_url=get_settings().PUBLIC_BASE_URL,
            bot_id=bot_id,
            dry_run=dry_run,
        )
    except DatabaseNotConfigured:
        return _refuse("DATABASE_URL is not set")
    finally:
        for http in clients:
            await http.aclose()
        await dispose_engine()


def _telegram_over(http: httpx.AsyncClient) -> TelegramProvider:
    """The existing Telegram client for each token, all on one HTTP client that ``run`` closes."""

    def provider(token: str) -> TelegramApi:
        return TelegramClient(token, http=http)

    return provider


def _no_telegram(token: str) -> TelegramApi:
    """The provider of a dry run, which builds no client: calling it is a bug."""
    raise RuntimeError("a dry run never calls Telegram")


def main(argv: list[str] | None = None) -> int:
    install_log_redaction()  # SECURITY: the server's log safety net (create_app does the same)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print what would change; call nothing, write nothing"
    )
    parser.add_argument("--bot-id", type=uuid.UUID, help="re-register only this bot")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(run(args.bot_id, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
