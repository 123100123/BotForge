"""End-to-end smoke test of the real HTTP stack, with no external service and no LLM.

Usage (from backend/):
    uv run python scripts/dev_db.py start
    $env:DATABASE_URL = '<printed url>'          # optional: the running dev database is found itself
    uv run python scripts/smoke_local.py --local-defaults
    uv run python scripts/dev_db.py stop

What runs: the real FastAPI app (all middleware, real cookie sessions and CSRF checks, real
ownership checks, real PgStore, the real Telegram webhook) is driven in-process through
``httpx.ASGITransport``; no server port is opened. Two throw-away accounts sign up through
``POST /auth/signup`` (or, when AUTH_ALLOW_SIGNUP is false, are created directly and log in through
``POST /auth/login``) and keep their session cookies in their own client's cookie jar. Only the
Telegram client is replaced, by the in-memory ``FakeTelegramClient`` (the app's
``get_telegram_provider`` dependency is overridden), so nothing leaves the machine.

``--local-defaults`` fills in TOKEN_ENC_KEY, PUBLIC_BASE_URL and FRONTEND_ORIGIN with process-local
values when they are unset. The test creates one bot and two accounts and deletes them at the end; it
refuses a DATABASE_URL on a non-local host unless ``--allow-remote`` is given. Exit code 0 only if
every step passes.
"""

import argparse
import asyncio
import os
import secrets
import sys
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

LOCAL_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}
LOCAL_DEFAULTS = {
    "PUBLIC_BASE_URL": "https://bots.example.test",  # the fake Telegram client never calls it
    "FRONTEND_ORIGIN": "http://localhost:3000",
}

Step = Callable[[], Awaitable[str | None]]


class Harness:
    """Runs named steps, prints PASS/FAIL for each and remembers the failures."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool]] = []

    async def run(self, name: str, step: Step) -> bool:
        try:
            detail = await step()
        except AssertionError as exc:
            self._report(name, False, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self._report(name, False, f"{type(exc).__name__}: {exc}")
        else:
            self._report(name, True, detail or "")
        return self.results[-1][1]

    def _report(self, name: str, ok: bool, detail: str) -> None:
        self.results.append((name, ok))
        line = f"{'PASS' if ok else 'FAIL'}  {name}"
        if detail:
            line += f"  ({detail})"
        # Persian text in a detail must not crash a cp1252 console.
        print(line.encode("ascii", "backslashreplace").decode("ascii"), flush=True)

    @property
    def failed(self) -> int:
        return sum(1 for _, ok in self.results if not ok)


def check(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def error_code(response: Any) -> str | None:
    try:
        return response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None


def expect(response: Any, status: int) -> Any:
    check(
        response.status_code == status,
        f"expected HTTP {status}, got {response.status_code}: {response.text[:300]}",
    )
    return response


def button_data(rows: list[list[str]], cap: str, action: str, arg: str | None = None) -> str:
    """The callback data of the button with this capability, action (and arg), found by parsing."""
    from app.runtime.callbacks import CallbackError, parse_callback

    for row in rows:
        for data in row:
            try:
                c, a, g = parse_callback(data)
            except CallbackError:
                continue
            if c == cap and a == action and (arg is None or g == arg):
                return data
    raise AssertionError(f"no {cap}:{action}:{arg or '*'} button among {[d for r in rows for d in r]}")


def flatten(rows: list[list[str]]) -> list[str]:
    return [d for r in rows for d in r]


def configure_environment(local_defaults: bool, allow_remote: bool) -> None:
    from app.config import Settings, get_settings

    settings = get_settings()
    if local_defaults:
        from cryptography.fernet import Fernet

        for name, value in LOCAL_DEFAULTS.items():
            # "Unset" includes a setting that still has its built-in default (http://localhost...),
            # which could not register a Telegram webhook anyway.
            if name not in os.environ and getattr(settings, name) in (
                None,
                "",
                Settings.model_fields[name].default,
            ):
                os.environ[name] = value
        if not settings.TOKEN_ENC_KEY:
            os.environ["TOKEN_ENC_KEY"] = Fernet.generate_key().decode()
        get_settings.cache_clear()
        settings = get_settings()

    if not settings.DATABASE_URL:
        from dev_db import running_url

        url = running_url()
        if url is None:
            raise SystemExit(
                "DATABASE_URL is not set and the dev database is not running (scripts/dev_db.py start)"
            )
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        settings = get_settings()
        print(f"using the running dev database ({urlsplit(url).hostname}:{urlsplit(url).port})")

    host = urlsplit(settings.DATABASE_URL or "").hostname
    if host not in LOCAL_HOSTS and not allow_remote:
        raise SystemExit(
            f"DATABASE_URL points at {host}, not a local database; pass --allow-remote to proceed"
        )
    missing = [n for n in ("TOKEN_ENC_KEY", "PUBLIC_BASE_URL", "FRONTEND_ORIGIN") if not getattr(settings, n)]
    if missing:
        raise SystemExit(f"unset: {', '.join(missing)} (use --local-defaults for local values)")


async def smoke() -> int:
    import httpx
    from load_spec import load_spec
    from sqlalchemy import delete

    from app.db.models import Revision, User
    from app.db.session import dispose_engine, get_sessionmaker
    from app.integrations.telegram.client import FakeTelegramClient, get_telegram_provider
    from app.main import create_app
    from app.security.accounts import create_user
    from app.security.sessions import SESSION_COOKIE

    app = create_app()
    fake = FakeTelegramClient(bot_id=uuid.uuid4().int % 10**9 + 10**9, username="smoke_workshop_bot")
    app.dependency_overrides[get_telegram_provider] = lambda: fake.provider
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    def client(**headers: str) -> httpx.AsyncClient:
        # https, so the cookie jar returns the Secure session cookie; one client is one browser.
        return httpx.AsyncClient(
            transport=transport, base_url="https://smoke.local", timeout=30, headers=headers
        )

    run_tag = uuid.uuid4().hex[:12]
    accounts = {
        role: (f"smoke-{role}-{run_tag}@example.com", secrets.token_urlsafe(18))
        for role in ("owner", "stranger")
    }
    csrf = {"X-BotForge-CSRF": "1"}

    h = Harness()
    state: dict[str, Any] = {}
    now = datetime.now(UTC)

    async def sign_in(c: httpx.AsyncClient, role: str) -> str:
        """Sign up through the API (or, with signup disabled, create the account and log in)."""
        email, password = accounts[role]
        r = await c.post("/auth/signup", json={"email": email, "password": password})
        how = "signed up"
        if r.status_code == 403 and error_code(r) == "signup_disabled":
            async with get_sessionmaker()() as session:
                await create_user(session, email, password)
                await session.commit()
            r = await c.post("/auth/login", json={"email": email, "password": password})
            how = "created directly, logged in"
        check(r.status_code in (200, 201), f"{role}: HTTP {r.status_code}: {r.text[:300]}")
        check(c.cookies.get(SESSION_COOKIE), f"{role}: no {SESSION_COOKIE} cookie was set")
        state[f"{role}_id"] = r.json()["user"]["id"]
        return how

    async with client(**csrf) as c, client(**csrf) as other, client() as anon:
        bot_url = ""

        async def healthz() -> str:
            expect(await c.get("/healthz"), 200)
            return "status ok"

        async def unauthenticated() -> str:
            r = await anon.get("/bots")
            check(r.status_code == 401, f"expected 401, got {r.status_code}")
            check(error_code(r) == "auth_required", f"unexpected error code {error_code(r)}")
            return "401 auth_required"

        async def accounts_sign_in() -> str:
            how = await sign_in(c, "owner")
            await sign_in(other, "stranger")
            me = expect(await c.get("/me"), 200).json()
            check(me == {"id": state["owner_id"], "email": accounts["owner"][0]}, f"/me answered {me}")
            return f"owner {state['owner_id']} ({how})"

        async def csrf_required() -> str:
            r = await c.post("/bots", json={"name": "x"}, headers={"X-BotForge-CSRF": ""})
            check(r.status_code == 403, f"expected 403, got {r.status_code}")
            check(error_code(r) == "csrf_failed", f"unexpected error code {error_code(r)}")
            return "403 csrf_failed without the header"

        async def create_bot() -> str:
            nonlocal bot_url
            r = expect(await c.post("/bots", json={"name": "Smoke workshop bot"}), 201)
            state["bot_id"] = r.json()["id"]
            bot_url = f"/bots/{state['bot_id']}"
            return f"bot {state['bot_id']}"

        async def load_revision() -> str:
            code = await load_spec(
                REPO / "examples" / "workshop.botspec.json",
                uuid.UUID(state["owner_id"]),
                uuid.UUID(state["bot_id"]),
                None,
            )
            check(code == 0, "load_spec reported an error")
            bot = expect(await c.get(bot_url), 200).json()
            check(bot["active_revision_number"] == 1, f"active revision is {bot['active_revision_number']}")
            state["revision_id"] = bot["active_revision_id"]
            # load_spec stores no sample data, so the simulator sandbox would be empty. Give the
            # revision two sample workshops (the same field the agent fills) for the simulator step.
            sample = [
                {
                    "ref": f"w{n}",
                    "collection": "workshop",
                    "values": [
                        {"key": "title", "value": title},
                        {"key": "description", "value": "توضیحات نمونه"},
                        {"key": "teacher", "value": "مدرس نمونه"},
                        {"key": "starts_at", "value": f"+{48 * n}h"},
                    ],
                }
                for n, title in ((1, "کارگاه نمونهٔ اول"), (2, "کارگاه نمونهٔ دوم"))
            ]
            async with get_sessionmaker()() as session:
                revision = await session.get(Revision, uuid.UUID(state["revision_id"]))
                check(revision is not None, "revision row not found")
                revision.sample_data = sample
                await session.commit()
            return "revision 1 is active"

        async def data_api_create() -> str:
            bad = await c.post(f"{bot_url}/data/workshop", json={"data": {"title": "x"}})
            check(bad.status_code == 400, f"invalid payload: expected 400, got {bad.status_code}")
            body = bad.json()["error"]
            check(body["code"] == "invalid_record", f"invalid payload: code {body['code']}")
            check(body.get("field_errors"), "invalid payload: field_errors is empty")
            ids = []
            for n, title in enumerate(["کارگاه عکاسی موبایل", "کارگاه خوشنویسی"]):
                payload = {
                    "title": title,
                    "description": "توضیحات کارگاه",
                    "teacher": "مدرس نمونه",
                    "starts_at": (now + timedelta(days=30 + n)).isoformat(),
                    "price": 500000,
                }
                created = expect(await c.post(f"{bot_url}/data/workshop", json={"data": payload}), 201)
                ids.append(created.json()["id"])
            state["workshops"] = ids
            return f"invalid -> invalid_record with {len(body['field_errors'])} field error(s); created {ids}"

        async def simulator() -> str:
            booked = []
            expect(await c.post(f"{bot_url}/simulator/reset", json={}), 200)
            for persona in ("ali", "sara"):

                async def send(kind: str, data: str | None = None, persona: str = persona) -> list[list[str]]:
                    body: dict[str, Any] = {"persona": persona, "kind": kind}
                    if data is not None:
                        body["data"] = data
                    resp = expect(await c.post(f"{bot_url}/simulator/events", json=body), 200).json()
                    state["last_outcomes"] = resp["outcomes"]
                    return [
                        [b["data"] for b in row]
                        for m in resp["messages"]
                        if m["to_actor_id"] == persona
                        for row in m["buttons"]
                    ]

                rows = await send("start")
                rows = await send("callback", button_data(rows, "menu", "open", "workshops"))
                item = button_data(rows, "book_workshop", "item")  # the first workshop in the list
                item_id = item.rsplit(":", 1)[1]
                rows = await send("callback", item)
                await send("callback", button_data(rows, "book_workshop", "book", item_id))
                outcome = state["last_outcomes"][-1]
                check(outcome["result"] == "confirmed", f"{persona}: booking result {outcome['result']}")
                booked.append(persona)
            return "confirmed for " + " and ".join(booked)

        async def telegram_connect() -> str:
            tg_id = fake.bot_id
            token_value = f"{tg_id}:AA{uuid.uuid4().hex}{uuid.uuid4().hex[:6]}"
            r = expect(await c.post(f"{bot_url}/telegram/connect", json={"token": token_value}), 200)
            status = r.json()
            check(status["connected"] and status["username"] == "smoke_workshop_bot", f"status {status}")
            check(token_value not in r.text, "the response contains the bot token")
            hook = fake.calls_to("setWebhook")
            check(
                len(hook) == 1 and hook[0]["url"].endswith(f"/tg/{state['bot_id']}"),
                f"setWebhook calls: {hook}",
            )
            state["webhook_secret"] = hook[0]["secret_token"]
            return "webhook registered with the fake client"

        async def telegram_customers() -> str:
            counter = iter(range(1, 1000))

            async def post(update: dict[str, Any], secret_header: str | None = None) -> None:
                headers = {"X-Telegram-Bot-Api-Secret-Token": secret_header or state["webhook_secret"]}
                expect(await anon.post(f"/tg/{state['bot_id']}", json=update, headers=headers), 200)

            def shown_rows(chat_id: int) -> list[list[str]]:
                calls = [
                    k
                    for n, k in fake.calls
                    if n in ("sendMessage", "editMessageText") and k["chat_id"] == chat_id
                ]
                markup = calls[-1].get("reply_markup") or {}
                return [[b["callback_data"] for b in row] for row in markup.get("inline_keyboard", [])]

            def user(uid: int, name: str) -> dict[str, Any]:
                return {"id": uid, "is_bot": False, "first_name": name}

            check(
                (
                    await anon.post(
                        f"/tg/{state['bot_id']}",
                        json={"update_id": 1},
                        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                    )
                ).status_code
                == 403,
                "a wrong webhook secret was not rejected with 403",
            )
            first_workshop = str(state["workshops"][0])
            for uid, name in ((7001, "علی"), (7002, "سارا")):

                async def press(data: str, uid: int = uid, name: str = name) -> None:
                    n = next(counter)
                    await post(
                        {
                            "update_id": uid * 100 + n,
                            "callback_query": {
                                "id": f"cb-{uid}-{n}",
                                "from": user(uid, name),
                                "message": {
                                    "message_id": n,
                                    "chat": {"id": uid, "type": "private"},
                                    "date": 1,
                                },
                                "data": data,
                            },
                        }
                    )

                n = next(counter)
                await post(
                    {
                        "update_id": uid * 100 + n,
                        "message": {
                            "message_id": n,
                            "from": user(uid, name),
                            "chat": {"id": uid, "type": "private"},
                            "date": 1,
                            "text": "/start",
                        },
                    }
                )
                await press(button_data(shown_rows(uid), "menu", "open", "workshops"))
                await press(button_data(shown_rows(uid), "book_workshop", "item", first_workshop))
                await press(button_data(shown_rows(uid), "book_workshop", "book", first_workshop))
            return "two Telegram users booked workshop " + first_workshop + " through the webhook"

        async def data_lists_bookings() -> str:
            page = expect(await c.get(f"{bot_url}/data/book_workshop"), 200).json()
            check(page["total"] == 2, f"expected 2 bookings, got {page['total']}")
            names = sorted(row["actor_name"] or "" for row in page["items"])
            check(
                all(row["actor_name"] and row["item_title"] for row in page["items"]),
                f"missing names/titles: {page['items']}",
            )
            check(names == sorted(["علی", "سارا"]), f"actor names {names}")
            check({row["status"] for row in page["items"]} == {"confirmed"}, "bookings are not confirmed")
            state["booking_id"] = page["items"][0]["id"]
            return "2 bookings with actor_name and item_title"

        async def admin_cancel() -> str:
            url = f"{bot_url}/data/book_workshop/{state['booking_id']}/actions/cancel"
            r = expect(await c.post(url), 200).json()
            check(r["ok"] is True, f"cancel answered {r}")
            page = expect(await c.get(f"{bot_url}/data/book_workshop"), 200).json()
            check(
                sorted(row["status"] for row in page["items"]) == ["cancelled", "confirmed"],
                "statuses after cancel",
            )
            return "booking cancelled, the other one is unchanged"

        async def revisions() -> str:
            rows = expect(await c.get(f"{bot_url}/revisions"), 200).json()
            check(len(rows) == 1 and rows[0]["status"] == "active", f"revisions: {rows}")
            return "1 revision, active"

        async def tests_run() -> str:
            r = expect(await c.post(f"/revisions/{state['revision_id']}/tests/run"), 200).json()
            check(r["total"] > 0 and r["failed"] == 0, f"report: total {r['total']}, failed {r['failed']}")
            return f"{r['passed']}/{r['total']} scenarios passed"

        async def other_user() -> str:
            r = await other.get(bot_url)
            check(r.status_code == 404, f"expected 404, got {r.status_code}")
            check(error_code(r) == "bot_not_found", f"error code {error_code(r)}")
            return "404 bot_not_found"

        async def delete_bot() -> str:
            expect(await c.delete(bot_url), 204)
            check((await c.get(bot_url)).status_code == 404, "bot still readable after delete")
            check(fake.calls_to("deleteWebhook"), "the webhook was not dropped")
            return "bot deleted, webhook dropped"

        async def logout() -> str:
            expect(await c.post("/auth/logout"), 204)
            check(not c.cookies.get(SESSION_COOKIE), "the session cookie was not cleared")
            r = await c.get("/me")
            check(r.status_code == 401, f"/me after logout: expected 401, got {r.status_code}")
            return "204, cookie cleared, /me is 401"

        steps: list[tuple[str, Step]] = [
            ("GET /healthz", healthz),
            ("unauthenticated call is 401", unauthenticated),
            ("two accounts sign in; session cookie set; /me", accounts_sign_in),
            ("state change without the CSRF header is 403", csrf_required),
            ("create bot", create_bot),
            ("load workshop spec as active revision", load_revision),
            ("data API: invalid payload rejected, 2 workshops created", data_api_create),
            ("simulator: two personas book", simulator),
            ("telegram connect (fake client)", telegram_connect),
            ("telegram webhook: two customers book (live)", telegram_customers),
            ("data API lists bookings with names and titles", data_lists_bookings),
            ("admin cancel through the data-action endpoint", admin_cancel),
            ("revisions list shows one active revision", revisions),
            ("tests/run reports zero failures", tests_run),
            ("another user gets 404 on the bot", other_user),
            ("delete bot", delete_bot),
            ("log out ends the session", logout),
        ]
        try:
            for name, step in steps:
                await h.run(name, step)
        finally:
            # Do not leave the smoke accounts behind; their bots go with them (ON DELETE CASCADE).
            emails = [email for email, _ in accounts.values()]
            async with get_sessionmaker()() as session:
                await session.execute(delete(User).where(User.email.in_(emails)))
                await session.commit()
    await dispose_engine()

    total = len(h.results)
    print(f"\n{total - h.failed}/{total} steps passed")
    return 1 if h.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--local-defaults", action="store_true", help="fill unset secrets with local values")
    parser.add_argument("--allow-remote", action="store_true", help="allow a non-local DATABASE_URL")
    args = parser.parse_args()
    configure_environment(args.local_defaults, args.allow_remote)
    return asyncio.run(smoke())


if __name__ == "__main__":
    raise SystemExit(main())
