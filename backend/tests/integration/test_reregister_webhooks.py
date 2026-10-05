"""scripts/reregister_webhooks.py: moves connected bots' webhooks to a new PUBLIC_BASE_URL and keeps
each bot's webhook secret, owner and owner-link code. Needs a database. Telegram is the fake client,
or the real client over a stub transport: never the network."""

import importlib.util
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Bot
from app.integrations.telegram import onboarding
from app.integrations.telegram.client import FakeTelegramClient, TelegramClient, TelegramError
from app.integrations.telegram.onboarding import OnboardingError, webhook_url
from app.revisions.service import activate, create_draft
from app.security.crypto import encrypt_token, generate_webhook_secret
from tests.integration.helpers import BACKEND, SessionFactory, user_id
from tests.integration.tg_helpers import new_token

NEW_BASE = "https://203-0-113-7.sslip.io"
COLUMNS = (
    "status",
    "active_revision_id",
    "tg_bot_id",
    "tg_username",
    "tg_token_enc",
    "tg_webhook_secret",
    "owner_actor_id",
    "owner_link_code",
    "tg_last_error",
)
REVOKED = TelegramError("setWebhook", "Unauthorized", error_code=401)
UNREACHABLE = TelegramError("setWebhook", "network error (ConnectError)", network=True)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "reregister_webhooks", BACKEND / "scripts" / "reregister_webhooks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


@pytest_asyncio.fixture
async def db(migrated_db: str, tg_env: None) -> AsyncIterator[SessionFactory]:
    """Sessions inside one transaction that is rolled back after the test.

    The script sweeps every connected bot in the database, and other tests leave connected bots
    behind (with tokens under other keys). Inside this transaction those are disconnected first, so
    a run sees only this test's bots; the rollback restores them and drops what the test wrote. The
    script's commits become savepoints of the transaction.
    """
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text("SET LOCAL lock_timeout = '10s'"))  # fail, never hang
        factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            async with factory() as session:
                await session.execute(
                    update(Bot).where(Bot.tg_token_enc.is_not(None)).values(tg_token_enc=None)
                )
                await session.commit()
            yield factory
        finally:
            await transaction.rollback()
    await engine.dispose()


@dataclass
class Seeded:
    id: uuid.UUID
    token: str
    secret: str


def ordered_ids(count: int) -> list[uuid.UUID]:
    """Fresh bot ids in ascending order. Bots made in one transaction share ``created_at``, so the
    script (oldest first) processes them in this order."""
    return sorted(uuid.uuid4() for _ in range(count))


async def seed(
    db: SessionFactory,
    *,
    bot_id: uuid.UUID | None = None,
    connected: bool = True,
    spec: dict[str, Any] | None = None,
    paused: bool = False,
    owner_actor_id: str | None = None,
    owner_link_code: str | None = None,
    last_error: str | None = None,
) -> Seeded:
    """A bot as ``connect`` leaves it (encrypted token, webhook secret), with an active revision when
    ``spec`` is given. A disconnected bot has neither."""
    tg_id, token = new_token()
    secret = generate_webhook_secret()
    owner = await user_id(db, "rereg-owner")  # owners are real accounts now
    async with db() as session:
        bot = Bot(
            id=bot_id or uuid.uuid4(),
            owner_id=owner,
            name="ربات",
            status="draft",
            owner_actor_id=owner_actor_id,
            owner_link_code=owner_link_code,
            tg_last_error=last_error,
        )
        if connected:
            bot.tg_bot_id, bot.tg_username = tg_id, f"bot_{tg_id}"
            bot.tg_token_enc, bot.tg_webhook_secret = encrypt_token(token), secret
        session.add(bot)
        await session.flush()
        if spec is not None:
            revision = await create_draft(session, bot.id, spec=spec)
            await activate(session, revision.id)  # live when connected
        if paused:
            bot.status = "paused"
        await session.commit()
        return Seeded(bot.id, token, secret)


async def snapshot(db: SessionFactory, bot_id: uuid.UUID) -> dict[str, Any]:
    async with db() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        return {column: getattr(bot, column) for column in COLUMNS}


async def set_token_enc(db: SessionFactory, bot_id: uuid.UUID, token_enc: str) -> None:
    async with db() as session:
        await session.execute(update(Bot).where(Bot.id == bot_id).values(tg_token_enc=token_enc))
        await session.commit()


def fake() -> FakeTelegramClient:
    # A Telegram bot id of its own: a simulated reconnect's getMe must not match another test's bot.
    return FakeTelegramClient(bot_id=uuid.uuid4().int % 10**9 + 10**9)


class ScriptedFake(FakeTelegramClient):
    """The shared fake with a per-bot script for ``setWebhook``. ``fail`` maps a bot id to the error
    its call raises; ``meanwhile`` maps a bot id to what happens during its call (the owner acting
    in the web app while the script waits for Telegram). Both apply once; calls are always recorded."""

    def __init__(
        self,
        *,
        fail: dict[uuid.UUID, Exception] | None = None,
        meanwhile: dict[uuid.UUID, Callable[[], Awaitable[None]]] | None = None,
    ) -> None:
        super().__init__(bot_id=uuid.uuid4().int % 10**9 + 10**9)
        self.fail = dict(fail or {})
        self.meanwhile = dict(meanwhile or {})

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await super().set_webhook(url, secret_token)
        bot_id = uuid.UUID(url.rsplit("/", 1)[-1])
        action, error = self.meanwhile.pop(bot_id, None), self.fail.pop(bot_id, None)
        if action is not None:
            await action()
        if error is not None:
            raise error


async def rereg(db: SessionFactory, telegram: FakeTelegramClient, **options: Any) -> int:
    options.setdefault("public_base_url", NEW_BASE)
    return await script.reregister_webhooks(db, lambda: telegram.provider, **options)


def no_telegram() -> Any:
    raise AssertionError("no Telegram client may be set up here")


def use_database(monkeypatch: pytest.MonkeyPatch, db: SessionFactory) -> None:
    """Point the command (``run``) at the test transaction."""

    async def no_dispose() -> None:
        return None

    monkeypatch.setattr(script, "get_sessionmaker", lambda: db)
    monkeypatch.setattr(script, "dispose_engine", no_dispose)


# --- moving the webhooks ---------------------------------------------------------------------------


async def test_connected_bots_move_to_the_new_host_with_their_existing_secrets(
    db: SessionFactory, golden_spec: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, third = ordered_ids(3)
    live = await seed(db, bot_id=first, spec=golden_spec, owner_actor_id="900")  # owner linked
    fresh = await seed(db, bot_id=second, owner_link_code="armed-code-1")  # no owner yet, code armed
    gone = await seed(db, bot_id=third, connected=False, owner_link_code="left-over")
    before = {bot.id: await snapshot(db, bot.id) for bot in (live, fresh, gone)}
    assert before[live.id]["status"] == "live" and before[fresh.id]["status"] == "draft"

    telegram = fake()
    assert await rereg(db, telegram, public_base_url=f" {NEW_BASE}/ ") == 0

    # Only the connected bots, each with its own token and its EXISTING secret; nothing else called.
    assert telegram.calls == [
        ("setWebhook", {"url": f"{NEW_BASE}/tg/{live.id}", "secret_token": live.secret}),
        ("setWebhook", {"url": f"{NEW_BASE}/tg/{fresh.id}", "secret_token": fresh.secret}),
    ]
    assert telegram.tokens == [live.token, fresh.token]

    # Secret, token, owner, owner-link code and status: all as they were, for all three bots.
    for bot in (live, fresh, gone):
        assert await snapshot(db, bot.id) == before[bot.id]
    after_live, after_fresh = await snapshot(db, live.id), await snapshot(db, fresh.id)
    assert after_live["owner_actor_id"] == "900" and after_live["owner_link_code"] is None
    assert after_fresh["owner_actor_id"] is None and after_fresh["owner_link_code"] == "armed-code-1"
    assert after_live["tg_webhook_secret"] == live.secret and after_live["status"] == "live"

    out = capsys.readouterr().out.splitlines()
    assert f"{live.id}  {NEW_BASE}/tg/{live.id}  ok" in out
    assert f"{fresh.id}  {NEW_BASE}/tg/{fresh.id}  ok" in out
    assert not any(str(gone.id) in line for line in out)
    assert out[-1] == "2 ok, 0 failed"


async def test_a_successful_run_leaves_each_status_as_connect_sets_it(
    db: SessionFactory, golden_spec: dict[str, Any]
) -> None:
    ids = ordered_ids(3)
    live = await seed(
        db, bot_id=ids[0], spec=golden_spec, last_error="sendMessage: Forbidden: bot was blocked by the user"
    )
    paused = await seed(db, bot_id=ids[1], spec=golden_spec, paused=True)
    draft = await seed(db, bot_id=ids[2])  # connected, no active revision

    assert await rereg(db, fake()) == 0

    statuses = {bot.id: (await snapshot(db, bot.id))["status"] for bot in (live, paused, draft)}
    assert statuses == {live.id: "live", paused.id: "paused", draft.id: "draft"}
    assert (await snapshot(db, live.id))["tg_last_error"] is None  # a clean registration clears it


async def test_dry_run_calls_nothing_and_writes_nothing(
    db: SessionFactory, golden_spec: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = ordered_ids(2)
    live = await seed(db, bot_id=first, spec=golden_spec, last_error="setWebhook: Bad Gateway")
    fresh = await seed(db, bot_id=second, owner_link_code="armed-code-2")
    before = {bot.id: await snapshot(db, bot.id) for bot in (live, fresh)}

    telegram = fake()
    assert await rereg(db, telegram, dry_run=True) == 0
    assert telegram.calls == [] and telegram.tokens == []  # no client was even built
    # nor was the provider asked for
    assert await script.reregister_webhooks(db, no_telegram, public_base_url=NEW_BASE, dry_run=True) == 0

    for bot in (live, fresh):
        assert await snapshot(db, bot.id) == before[bot.id]  # the old error is still there
    out = capsys.readouterr().out.splitlines()
    assert f"{live.id}  {NEW_BASE}/tg/{live.id}  dry run: would re-register" in out
    assert f"{fresh.id}  {NEW_BASE}/tg/{fresh.id}  dry run: would re-register" in out
    assert out.count("dry run: 2 would be re-registered, 0 would fail") == 2


async def test_bot_id_limits_the_run_to_that_bot(
    db: SessionFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    await seed(db)
    chosen = await seed(db)
    gone = await seed(db, connected=False)

    telegram = fake()
    assert await rereg(db, telegram, bot_id=chosen.id) == 0
    assert telegram.calls == [
        ("setWebhook", {"url": f"{NEW_BASE}/tg/{chosen.id}", "secret_token": chosen.secret})
    ]

    for missing in (gone.id, uuid.uuid4()):  # not connected; does not exist
        assert await rereg(db, telegram, bot_id=missing) == 1
    assert len(telegram.calls) == 1
    assert f"bot {gone.id} does not exist or is not connected" in capsys.readouterr().err


# --- failures ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("error", [REVOKED, UNREACHABLE], ids=["revoked-token", "network-error"])
async def test_one_bots_failure_is_recorded_and_the_next_bot_still_moves(
    db: SessionFactory, golden_spec: dict[str, Any], capsys: pytest.CaptureFixture[str], error: TelegramError
) -> None:
    first, second = ordered_ids(2)
    broken = await seed(db, bot_id=first, spec=golden_spec, owner_actor_id="900")
    healthy = await seed(db, bot_id=second, spec=golden_spec, last_error="setWebhook: Bad Gateway")
    before = await snapshot(db, broken.id)

    telegram = ScriptedFake(fail={broken.id: error})
    assert await rereg(db, telegram) == 1

    # The failing bot came first and the run went on to the next one.
    assert [call["url"] for call in telegram.calls_to("setWebhook")] == [
        f"{NEW_BASE}/tg/{broken.id}",
        f"{NEW_BASE}/tg/{healthy.id}",
    ]
    after = await snapshot(db, broken.id)
    assert after["tg_last_error"] == f"setWebhook: {error.description}"  # stored like a delivery error
    assert after == {**before, "tg_last_error": after["tg_last_error"]}  # status, secret, owner kept
    assert after["status"] == "live"
    assert (await snapshot(db, healthy.id))["tg_last_error"] is None

    out = capsys.readouterr().out.splitlines()
    assert any(
        line.startswith(f"{broken.id}  {NEW_BASE}/tg/{broken.id}  error: setWebhook: {error.description}")
        for line in out
    )
    assert f"{healthy.id}  {NEW_BASE}/tg/{healthy.id}  ok" in out
    assert out[-1] == "1 ok, 1 failed"


async def test_an_unreadable_stored_token_is_reported_without_calling_telegram(
    db: SessionFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = ordered_ids(2)
    unreadable = await seed(db, bot_id=first)
    healthy = await seed(db, bot_id=second)
    # stored under a key the server does not have
    await set_token_enc(db, unreadable.id, Fernet(Fernet.generate_key()).encrypt(b"x").decode())
    before = await snapshot(db, unreadable.id)

    telegram = fake()
    assert await rereg(db, telegram, dry_run=True) == 1
    assert telegram.calls == []
    assert f"{unreadable.id}  {NEW_BASE}/tg/{unreadable.id}  dry run: would fail" in capsys.readouterr().out

    assert await rereg(db, telegram) == 1
    assert telegram.tokens == [healthy.token]  # never a client for the unreadable bot
    assert telegram.calls_to("setWebhook") == [
        {"url": f"{NEW_BASE}/tg/{healthy.id}", "secret_token": healthy.secret}
    ]
    assert await snapshot(db, unreadable.id) == {**before, "tg_last_error": script.TOKEN_UNREADABLE}
    assert "cannot be decrypted" in capsys.readouterr().out


@pytest.mark.parametrize("key", ["", "not-a-fernet-key", "another-valid-key"])
async def test_a_key_that_reads_no_stored_token_refuses_the_run(
    db: SessionFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], key: str
) -> None:
    bots = [await seed(db), await seed(db)]
    before = [await snapshot(db, bot.id) for bot in bots]
    if key == "another-valid-key":  # a valid key, but not the one the tokens were stored with
        key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENC_KEY", key)
    get_settings.cache_clear()

    telegram = fake()
    for dry_run in (True, False):
        assert await rereg(db, telegram, dry_run=dry_run) == 2
    assert telegram.calls == [] and telegram.tokens == []
    assert [await snapshot(db, bot.id) for bot in bots] == before  # no owner is told to reconnect
    captured = capsys.readouterr()
    assert "refusing to run: TOKEN_ENC_KEY" in captured.err and captured.out == ""


@pytest.mark.parametrize(
    "base", ["", "http://bots.example.test", "https://localhost:8000", "https://127.0.0.1/botforge"]
)
@pytest.mark.parametrize("dry_run", [False, True], ids=["run", "dry-run"])
async def test_an_invalid_public_base_url_is_refused(
    db: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    base: str,
    dry_run: bool,
) -> None:
    bot = await seed(db)
    before = await snapshot(db, bot.id)
    use_database(monkeypatch, db)
    monkeypatch.setenv("PUBLIC_BASE_URL", base)
    get_settings.cache_clear()

    telegram = fake()
    assert await script.run(None, dry_run, provider=telegram.provider) == 2

    assert telegram.calls == [] and telegram.tokens == []
    assert await snapshot(db, bot.id) == before
    captured = capsys.readouterr()
    assert "refusing to run: PUBLIC_BASE_URL" in captured.err and captured.out == ""


async def test_the_command_uses_the_configured_public_base_url(
    db: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await seed(db)
    use_database(monkeypatch, db)
    monkeypatch.setenv("PUBLIC_BASE_URL", f"{NEW_BASE}/")
    get_settings.cache_clear()

    telegram = fake()
    assert await script.run(None, False, provider=telegram.provider) == 0
    assert telegram.calls_to("setWebhook") == [{"url": f"{NEW_BASE}/tg/{bot.id}", "secret_token": bot.secret}]


async def test_a_dry_run_from_the_command_line_builds_no_http_client(
    db: SessionFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bot = await seed(db)
    use_database(monkeypatch, db)
    monkeypatch.setenv("PUBLIC_BASE_URL", NEW_BASE)
    get_settings.cache_clear()

    def no_http_client(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a dry run must not build an HTTP client")

    monkeypatch.setattr(script, "httpx", SimpleNamespace(AsyncClient=no_http_client))
    assert await script.run(None, True) == 0  # the real command: no provider passed in
    assert f"{bot.id}  {NEW_BASE}/tg/{bot.id}  dry run: would re-register" in capsys.readouterr().out


async def test_a_run_whose_http_client_cannot_be_built_is_refused(
    db: SessionFactory, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bot = await seed(db)
    before = await snapshot(db, bot.id)
    use_database(monkeypatch, db)

    def socks_proxy_without_socksio(*args: Any, **kwargs: Any) -> Any:
        raise ImportError("Using SOCKS proxy, but the 'socksio' package is not installed.")

    monkeypatch.setattr(script, "httpx", SimpleNamespace(AsyncClient=socks_proxy_without_socksio))

    # The settings are checked first: a wrong PUBLIC_BASE_URL is reported as such.
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    get_settings.cache_clear()
    assert await script.run(None, False) == 2
    assert "refusing to run: PUBLIC_BASE_URL" in capsys.readouterr().err

    monkeypatch.setenv("PUBLIC_BASE_URL", NEW_BASE)
    get_settings.cache_clear()
    assert await script.run(None, False) == 2
    assert "cannot create the HTTP client for Telegram (ImportError)" in capsys.readouterr().err
    assert await snapshot(db, bot.id) == before  # an environment problem is not recorded on a bot


# --- the owner acting while the script runs --------------------------------------------------------


async def test_a_bot_disconnected_during_the_run_is_not_marked_live(
    db: SessionFactory, golden_spec: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = ordered_ids(2)
    raced = await seed(db, bot_id=first, spec=golden_spec, owner_actor_id="900")
    other = await seed(db, bot_id=second, spec=golden_spec)

    async def owner_disconnects() -> None:
        async with db() as session:
            bot = await session.get(Bot, raced.id)
            assert bot is not None
            await onboarding.disconnect(session, bot, telegram.provider)

    telegram = ScriptedFake(meanwhile={raced.id: owner_disconnects})
    assert await rereg(db, telegram) == 1

    after = await snapshot(db, raced.id)
    assert after["tg_token_enc"] is None and after["tg_webhook_secret"] is None
    # Still what disconnect left: draft (although it has an active revision), nothing recorded.
    assert after["status"] == "draft" and after["tg_last_error"] is None
    assert after["owner_actor_id"] is None and after["owner_link_code"] is None
    assert (await snapshot(db, other.id))["status"] == "live"  # the run went on
    assert f"run again with --bot-id {raced.id}" in capsys.readouterr().out


async def test_a_bot_reconnected_during_the_run_keeps_the_new_connection(
    db: SessionFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    raced = await seed(db, owner_actor_id="900")
    _, replacement = new_token()

    async def owner_reconnects() -> None:  # new token and secret, owner unlinked, fresh code armed
        async with db() as session:
            bot = await session.get(Bot, raced.id)
            assert bot is not None
            await onboarding.connect(session, bot, replacement, telegram.provider, public_base_url=NEW_BASE)

    # The script's own setWebhook (old token, old secret) fails; that stale error must not land on
    # the bot the owner has just reconnected.
    telegram = ScriptedFake(fail={raced.id: REVOKED}, meanwhile={raced.id: owner_reconnects})
    assert await rereg(db, telegram) == 1

    after = await snapshot(db, raced.id)
    assert after["tg_webhook_secret"] not in (None, raced.secret)  # connect's new secret stays
    assert after["tg_last_error"] is None
    assert after["owner_actor_id"] is None and after["owner_link_code"]  # as connect left it
    assert f"run again with --bot-id {raced.id}" in capsys.readouterr().out


# --- secrets ----------------------------------------------------------------------------------------


async def test_no_token_or_secret_reaches_the_output_or_the_log(
    db: SessionFactory, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    ids = ordered_ids(4)
    ok, echoed, unreachable, crashing = [await seed(db, bot_id=bot_id) for bot_id in ids]
    telegram = ScriptedFake(
        fail={
            # a description that (unlike Telegram's) echoes the token: the output redaction catches it
            echoed.id: TelegramError("setWebhook", f"Unauthorized: {echoed.token}", error_code=401),
            unreachable.id: UNREACHABLE,
            # an unexpected exception whose message holds the secret: only its type is reported
            crashing.id: RuntimeError(f"boom {crashing.secret} {crashing.token}"),
        }
    )
    assert await rereg(db, telegram, dry_run=True) == 0
    assert await rereg(db, telegram) == 1

    captured = capsys.readouterr()
    shown = captured.out + captured.err + caplog.text
    stored = {bot.id: await snapshot(db, bot.id) for bot in (ok, echoed, unreachable, crashing)}
    for bot in (ok, echoed, unreachable, crashing):
        assert bot.token not in shown and bot.secret not in shown
        assert stored[bot.id]["tg_token_enc"] not in shown
        assert bot.token not in (stored[bot.id]["tg_last_error"] or "")
    assert "setWebhook: Unauthorized: [REDACTED]" in captured.out
    assert stored[echoed.id]["tg_last_error"] == "setWebhook: Unauthorized: [REDACTED]"
    assert "setWebhook: unexpected RuntimeError" in captured.out
    assert stored[crashing.id]["tg_last_error"] == script.UNEXPECTED


async def test_the_real_client_sends_the_existing_secret_and_leaks_nothing(
    db: SessionFactory, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    ids = ordered_ids(3)
    ok, revoked, unreachable = [await seed(db, bot_id=bot_id) for bot_id in ids]
    requests: list[httpx.Request] = []

    def telegram_api(request: httpx.Request) -> httpx.Response:  # a stub: no network
        requests.append(request)
        if revoked.token in request.url.path:
            return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})
        if unreachable.token in request.url.path:
            raise httpx.ConnectError(f"cannot reach {request.url}", request=request)  # holds the token
        return httpx.Response(200, json={"ok": True, "result": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(telegram_api)) as http:

        def real_client(token: str) -> TelegramClient:
            return TelegramClient(token, http=http)

        code = await script.reregister_webhooks(db, lambda: real_client, public_base_url=NEW_BASE)
    assert code == 1

    assert requests[0].url.path == f"/bot{ok.token}/setWebhook"
    assert json.loads(requests[0].content) == {
        "url": f"{NEW_BASE}/tg/{ok.id}",
        "secret_token": ok.secret,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    }
    assert len(requests) == 4  # ok, revoked, and the unreachable one tried twice (one retry)
    assert (await snapshot(db, revoked.id))["tg_last_error"] == "setWebhook: Unauthorized"
    assert (await snapshot(db, unreachable.id))["tg_last_error"] == "setWebhook: network error (ConnectError)"

    captured = capsys.readouterr()
    shown = captured.out + captured.err + caplog.text
    for bot in (ok, revoked, unreachable):
        assert bot.token not in shown and bot.secret not in shown


# --- the command line and the shared URL helper ------------------------------------------------------


def test_the_command_line_passes_its_options_to_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, ...]] = []

    async def recording_run(bot_id: uuid.UUID | None, dry_run: bool, provider: Any = None) -> int:
        seen.append((bot_id, dry_run, provider))
        return 0

    monkeypatch.setattr(script, "run", recording_run)
    chosen = uuid.uuid4()
    assert script.main(["--dry-run", "--bot-id", str(chosen)]) == 0
    assert script.main([]) == 0
    assert seen == [(chosen, True, None), (None, False, None)]  # None: the real client, real database
    with pytest.raises(SystemExit) as refused:
        script.main(["--bot-id", "not-a-uuid"])
    assert refused.value.code == 2


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://bots.example.test", "https://bots.example.test/tg/B"),
        ("  https://bots.example.test//  ", "https://bots.example.test/tg/B"),
        ("https://bots.example.test:8443/botforge/", "https://bots.example.test:8443/botforge/tg/B"),
    ],
)
def test_webhook_url_is_the_one_connect_registers(base: str, expected: str) -> None:
    assert webhook_url(base, "B") == expected


@pytest.mark.parametrize(
    "base",
    [
        "",
        "   ",
        "http://bots.example.test",
        "https://",
        "https://localhost",
        "https://LOCALHOST:8443/x",
        "https://127.0.0.1",
        "https://0.0.0.0:443",
    ],
)
def test_webhook_url_refuses_what_telegram_cannot_reach(base: str) -> None:
    with pytest.raises(OnboardingError) as refused:
        webhook_url(base, "B")
    assert (refused.value.status, refused.value.code) == (503, "public_url_missing")
