"""End-to-end smoke test of the real HTTP stack, with no external service and no LLM.

Usage (from backend/):
    uv run python scripts/dev_db.py start
    $env:DATABASE_URL = '<printed url>'          # optional: the running dev database is found itself
    uv run python scripts/smoke_local.py --local-defaults
    uv run python scripts/dev_db.py stop

What runs: the real FastAPI app (all middleware, real JWT verification, real ownership checks, real
PgStore, the real Telegram webhook) is driven in-process through ``httpx.ASGITransport``; no server
port is opened. Only two things are replaced: access tokens are minted locally (HS256, like
``dev_token.py``) and the Telegram client is the in-memory ``FakeTelegramClient`` (the app's
``get_telegram_provider`` dependency is overridden), so nothing leaves the machine.

``--local-defaults`` fills in SUPABASE_JWT_SECRET, TOKEN_ENC_KEY, PUBLIC_BASE_URL and FRONTEND_ORIGIN
with process-local values when they are unset. SUPABASE_JWKS_URL must be unset (the smoke test signs
its own tokens). The test creates one bot (and deletes it at the end); it refuses a DATABASE_URL on a
non-local host unless ``--allow-remote`` is given. Exit code 0 only if every step passes.
"""

import argparse
import asyncio
import os
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
    "SUPABASE_JWT_SECRET": "smoke-local-secret-not-for-production-0123456789",
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
    missing = [
        n
        for n in ("SUPABASE_JWT_SECRET", "TOKEN_ENC_KEY", "PUBLIC_BASE_URL", "FRONTEND_ORIGIN")
        if not getattr(settings, n)
    ]
    if missing:
        raise SystemExit(f"unset: {', '.join(missing)} (use --local-defaults for local values)")
    if settings.SUPABASE_JWKS_URL:
        raise SystemExit("SUPABASE_JWKS_URL is set; unset it (the smoke test signs its own HS256 tokens)")


async def smoke() -> int:
    import httpx
    from dev_token import mint_token
    from load_spec import load_spec

    from app.config import get_settings
    from app.db.models import Revision
    from app.db.session import dispose_engine, get_sessionmaker
    from app.integrations.telegram.client import FakeTelegramClient, get_telegram_provider
    from app.main import create_app
    from app.security.auth import reset_verifier

    settings = get_settings()
    reset_verifier()
    app = create_app()
    fake = FakeTelegramClient(bot_id=uuid.uuid4().int % 10**9 + 10**9, username="smoke_workshop_bot")
    app.dependency_overrides[get_telegram_provider] = lambda: fake.provider
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    owner_id = str(uuid.uuid4())
    stranger_id = str(uuid.uuid4())
    secret = settings.SUPABASE_JWT_SECRET or ""
    owner_token = mint_token(
        secret, user_id=owner_id, email="owner@example.com", supabase_url=settings.SUPABASE_URL
    )
    stranger_token = mint_token(
        secret, user_id=stranger_id, email="stranger@example.com", supabase_url=settings.SUPABASE_URL
    )
    auth = {"Authorization": f"Bearer {owner_token}"}
    stranger = {"Authorization": f"Bearer {stranger_token}"}

    h = Harness()
    state: dict[str, Any] = {}
    now = datetime.now(UTC)

    async with httpx.AsyncClient(transport=transport, base_url="http://smoke.local", timeout=30) as c:
        bot_url = ""

        async def healthz() -> str:
            expect(await c.get("/healthz"), 200)
            return "status ok"

        async def unauthenticated() -> str:
            r = await c.get("/bots")
            check(r.status_code == 401, f"expected 401, got {r.status_code}")
            check(error_code(r) == "auth_required", f"unexpected error code {error_code(r)}")
            return "401 auth_required"

        async def token() -> str:
            me = expect(await c.get("/me", headers=auth), 200).json()
            check(me["id"] == owner_id, "token subject was not accepted as the user id")
            return f"user {owner_id}"

        async def create_bot() -> str:
            nonlocal bot_url
            r = expect(await c.post("/bots", headers=auth, json={"name": "Smoke workshop bot"}), 201)
            state["bot_id"] = r.json()["id"]
            bot_url = f"/bots/{state['bot_id']}"
            return f"bot {state['bot_id']}"

        async def load_revision() -> str:
            code = await load_spec(
                REPO / "examples" / "workshop.botspec.json", owner_id, uuid.UUID(state["bot_id"]), None
            )
            check(code == 0, "load_spec reported an error")
            bot = expect(await c.get(bot_url, headers=auth), 200).json()
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
            bad = await c.post(f"{bot_url}/data/workshop", headers=auth, json={"data": {"title": "x"}})
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
                created = expect(
                    await c.post(f"{bot_url}/data/workshop", headers=auth, json={"data": payload}), 201
                )
                ids.append(created.json()["id"])
            state["workshops"] = ids
            return f"invalid -> invalid_record with {len(body['field_errors'])} field error(s); created {ids}"

        async def simulator() -> str:
            booked = []
            expect(await c.post(f"{bot_url}/simulator/reset", headers=auth, json={}), 200)
            for persona in ("ali", "sara"):

                async def send(kind: str, data: str | None = None, persona: str = persona) -> list[list[str]]:
                    body: dict[str, Any] = {"persona": persona, "kind": kind}
                    if data is not None:
                        body["data"] = data
                    resp = expect(
                        await c.post(f"{bot_url}/simulator/events", headers=auth, json=body), 200
                    ).json()
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
            r = expect(
                await c.post(f"{bot_url}/telegram/connect", headers=auth, json={"token": token_value}), 200
            )
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
                expect(await c.post(f"/tg/{state['bot_id']}", json=update, headers=headers), 200)

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
                    await c.post(
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
            page = expect(await c.get(f"{bot_url}/data/book_workshop", headers=auth), 200).json()
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
            r = expect(await c.post(url, headers=auth), 200).json()
            check(r["ok"] is True, f"cancel answered {r}")
            page = expect(await c.get(f"{bot_url}/data/book_workshop", headers=auth), 200).json()
            check(
                sorted(row["status"] for row in page["items"]) == ["cancelled", "confirmed"],
                "statuses after cancel",
            )
            return "booking cancelled, the other one is unchanged"

        async def revisions() -> str:
            rows = expect(await c.get(f"{bot_url}/revisions", headers=auth), 200).json()
            check(len(rows) == 1 and rows[0]["status"] == "active", f"revisions: {rows}")
            return "1 revision, active"

        async def tests_run() -> str:
            r = expect(await c.post(f"/revisions/{state['revision_id']}/tests/run", headers=auth), 200).json()
            check(r["total"] > 0 and r["failed"] == 0, f"report: total {r['total']}, failed {r['failed']}")
            return f"{r['passed']}/{r['total']} scenarios passed"

        async def other_user() -> str:
            r = await c.get(bot_url, headers=stranger)
            check(r.status_code == 404, f"expected 404, got {r.status_code}")
            check(error_code(r) == "bot_not_found", f"error code {error_code(r)}")
            return "404 bot_not_found"

        async def delete_bot() -> str:
            expect(await c.delete(bot_url, headers=auth), 204)
            check((await c.get(bot_url, headers=auth)).status_code == 404, "bot still readable after delete")
            check(fake.calls_to("deleteWebhook"), "the webhook was not dropped")
            return "bot deleted, webhook dropped"

        steps: list[tuple[str, Step]] = [
            ("GET /healthz", healthz),
            ("unauthenticated call is 401", unauthenticated),
            ("minted token is accepted (/me)", token),
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
        ]
        try:
            for name, step in steps:
                await h.run(name, step)
        finally:
            if state.get("bot_id") and not any(n == "delete bot" and ok for n, ok in h.results):
                await c.delete(bot_url, headers=auth)  # do not leave the smoke bot behind
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
