"""The Business OS demo path end to end, through the real API (cookie sessions, CSRF, ownership), the
real webhook with the fake Telegram client, the sandbox simulator, the notification ticker (one
``tick()`` at a time, never the background loop) and a scripted ``FakeLLM``. Needs a database.

Story 1, one live bot that starts as the workshop example: the owner enables events, adds an event,
a customer RSVPs in Telegram and gets a reminder, a colleague joins through the staff link, the shop
goes in (catalog revision, then orders from the Capability Center), orders are placed in the
simulator and in Telegram and moved along by the owner persona, the staff member and the web admin,
the Copilot reads the events report, and the Overview shows it all. Story 2: spreadsheet intelligence,
from the first upload to a renamed column, from the web and from a staff member in Telegram.
"""

import copy
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent.llm import FakeLLM, ToolCall
from app.api import analysis as analysis_api
from app.api.copilot import get_copilot_llm
from app.config import get_settings
from app.db.models import Bot, OutboundMessageRow, Revision
from app.integrations.telegram.client import FakeTelegramClient, get_telegram_provider
from app.main import create_app
from app.notifications.ticker import NotificationTicker
from app.revisions.service import activate, create_draft
from app.roles.service import STAFF_JOINED
from app.runtime.pg_store import PgStore
from app.spreadsheets.telegram_ingest import NO_PROFILE
from tests.integration.helpers import SessionFactory, signed_in_client
from tests.integration.test_outbox import FakeClock
from tests.integration.tg_helpers import Chat, LiveBot, make_live_bot, user
from tests.unit.spreadsheets.test_profile_run import COLUMNS, good_draft, sales_rows, sales_workbook
from tests.unit.spreadsheets.workbooks import make_xlsx

OWNER, CUSTOMER, STAFF = 8100, 8201, 8301
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --- helpers -------------------------------------------------------------------------------------


@dataclass
class Demo:
    client: httpx.AsyncClient
    bot: LiveBot
    fake: FakeTelegramClient
    sessions: SessionFactory
    llm: FakeLLM = field(default_factory=FakeLLM)

    async def call(self, method: str, rest: str, expect: int = 200, **kw: Any) -> Any:
        response = await self.client.request(method, f"/bots/{self.bot.id}{rest}", **kw)
        assert response.status_code == expect, f"{method} {rest}: {response.status_code} {response.text}"
        return response.json() if response.content else None

    async def get(self, rest: str, **params: Any) -> Any:
        return await self.call("GET", rest, params=params)

    async def post(self, rest: str, body: dict[str, Any] | None = None, expect: int = 200) -> Any:
        return await self.call("POST", rest, expect, json=body if body is not None else {})

    async def toggle(self, cap: str, action: str = "enable") -> dict[str, Any]:
        body: dict[str, Any] = await self.post(f"/capabilities/{cap}/{action}")
        assert body["applied"] is True, body
        return body

    async def report(self, key: str, env: str = "live") -> dict[str, Any]:
        body = await self.get(f"/reports/{key}", period="7d", env=env)
        return {m["id"]: m for m in body["metrics"]}

    async def sim(self, persona: str, data: str) -> dict[str, Any]:
        body = {"revision_id": None, "persona": persona, "kind": "callback", "data": data}
        result: dict[str, Any] = await self.post("/simulator/events", body)
        return result

    def chat(self, tg_id: int) -> Chat:
        return Chat(self.client, self.bot, self.fake, tg_id)

    async def put_xlsx(self, data: bytes, name: str) -> dict[str, Any]:
        response = await self.client.put(
            f"/uploads/bots/{self.bot.id}", params={"filename": name}, content=data,
            headers={"Content-Type": XLSX},
        )  # fmt: skip
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    async def send_document(self, tg_id: int, data: bytes, name: str) -> str:
        """A file sent to the bot in Telegram; the bot's reply to the sender."""
        file_id = f"doc-{uuid.uuid4().hex[:8]}"
        self.fake.files[file_id] = data
        before = len(self.fake.sent_to(tg_id))
        document = {"file_id": file_id, "file_unique_id": f"u-{file_id}", "file_name": name}
        update = {
            "update_id": uuid.uuid4().int % 10**9,
            "message": {
                "message_id": 5, "from": user(tg_id), "chat": {"id": tg_id, "type": "private"},
                "date": 1, "document": document,
            },
        }  # fmt: skip
        assert (await self.chat(tg_id).post(update)).status_code == 200
        [reply] = self.fake.sent_to(tg_id)[before:]
        return str(reply["text"])

    async def join_as_staff(self, tg_id: int) -> None:
        code = (await self.post("/team/staff-link"))["staff_link_code"]
        chat = self.chat(tg_id)
        await chat.say(f"/start staff_{code}")
        assert STAFF_JOINED in [m["text"] for m in chat.shown()]
        members = (await self.get("/team"))["members"]
        assert {"actor_id": str(tg_id), "role": "staff"}.items() <= next(
            m for m in members if m["actor_id"] == str(tg_id)
        ).items()

    async def orders(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = (await self.get("/data/orders"))["items"]
        return items


def caps_by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for cat in body["categories"] for c in cat["capabilities"]}


def texts(response: dict[str, Any], persona: str) -> str:
    return "\n".join(m["text"] for m in response["messages"] if m["to_actor_id"] == persona)


async def agent_adds_a_catalog(demo: Demo) -> None:
    """Stands in for an agent run (the catalog has no default ops): a new ACTIVE revision with a
    product resource and a catalog capability, on top of the current one."""
    async with demo.sessions() as session:
        bot = await session.get(Bot, demo.bot.id)
        assert bot is not None and bot.active_revision_id is not None
        current = await session.get(Revision, bot.active_revision_id)
        assert current is not None
        spec = copy.deepcopy(current.spec)
        spec["resources"].append(
            {
                "key": "product", "label": "کالا", "label_plural": "کالاها", "title_field": "title",
                "fields": [
                    {"key": "title", "label": "نام", "type": "text"},
                    {"key": "price", "label": "قیمت", "type": "integer"},
                ],
            }
        )  # fmt: skip
        spec["capabilities"].append(
            {
                "type": "catalog",
                "key": "products",
                "title": "محصولات",
                "resource": "product",
                "detail_fields": [],
            }
        )
        spec["menu"].append({"key": "products", "label": "محصولات", "capability": "products"})
        revision = await create_draft(session, demo.bot.id, spec=spec, parent_id=current.id)
        await activate(session, revision.id)
        await session.commit()


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    yield tmp_path / "uploads"
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def demo(
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
    fake_tg: FakeTelegramClient,
    tg_env: None,
    upload_dir: Path,
) -> AsyncIterator[Demo]:
    """A connected bot (workshop example active, owner linked) and the full app around it."""
    bot = await make_live_bot(session_factory, golden_spec, owner_actor_id=str(OWNER))
    app = create_app()
    holder = Demo(client=None, bot=bot, fake=fake_tg, sessions=session_factory)  # type: ignore[arg-type]
    app.dependency_overrides[get_telegram_provider] = lambda: fake_tg.provider
    app.dependency_overrides[analysis_api.get_llm_optional] = lambda: holder.llm
    app.dependency_overrides[get_copilot_llm] = lambda: holder.llm
    async with signed_in_client(app, session_factory) as client:
        holder.client = client
        yield holder


# --- story 1: events, staff, notifications, orders, copilot, overview ------------------------------


async def test_events_staff_orders_copilot_and_overview(demo: Demo) -> None:
    # (1) Capability Center: events is off; a dry run plans, enabling makes revision 2 ACTIVE.
    caps = caps_by_id(await demo.get("/capabilities"))
    assert caps["booking"]["enabled"] and not caps["events"]["enabled"]
    dry = await demo.post("/capabilities/events/enable", {"dry_run": True})
    assert dry["applied"] is False and dry["plan"]["will_enable"] == ["events"]
    enabled = await demo.toggle("events")
    assert enabled["revision_number"] == 2
    revisions = {r["number"]: r for r in await demo.get("/revisions")}
    assert revisions[2]["status"] == "active" and revisions[2]["id"] == enabled["revision_id"]
    assert revisions[1]["status"] != "active"
    assert caps_by_id(await demo.get("/capabilities"))["events"]["enabled"]

    # (2) The owner adds an event in the Data API, starting in 23 hours, 10 seats.
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=23)
    event = {"title": "کارگاه عکاسی", "category": "آموزشی", "starts_at": start.isoformat(), "capacity": 10}
    event_id = (await demo.post("/data/event", {"data": event}, expect=201))["id"]

    # (3) A customer RSVPs in Telegram; the events report and the Overview count it.
    customer = demo.chat(CUSTOMER)
    await customer.say("/start")
    assert customer.data_with("nav:go:evt")
    await customer.press("nav:go:evt")
    assert "کارگاه عکاسی" in customer.last_text()
    await customer.press(f"events:book:{event_id}")
    rsvps = (await demo.get("/data/events"))["items"]
    assert [(r["status"], r["item_id"], r["actor_id"]) for r in rsvps] == [
        ("confirmed", event_id, str(CUSTOMER))
    ]
    report = await demo.report("events")
    assert report["rsvp_count"]["value"] == 1 and report["event_count"]["value"] == 1
    assert "events" in (await demo.get("/reports/overview"))["enabled_capabilities"]

    # (7) Reminders: a tick 23 hours before the start queues and sends one; the next adds nothing.
    clock = FakeClock()
    ticker = NotificationTicker(
        demo.sessions, demo.fake.provider, bot_ids={demo.bot.id}, sleep=clock.sleep, clock=clock,
        now=lambda: start - timedelta(hours=23),
    )  # fmt: skip
    await ticker.tick()
    await ticker.tick()
    async with demo.sessions() as session:
        stmt = select(OutboundMessageRow).where(OutboundMessageRow.bot_id == demo.bot.id)
        reminders = [
            r for r in (await session.execute(stmt)).scalars() if (r.dedupe_key or "").startswith("rem:")
        ]
    assert [(r.chat_id, r.status) for r in reminders] == [(CUSTOMER, "sent")]
    assert any(m["text"].startswith("یادآوری: «کارگاه عکاسی»") for m in demo.fake.sent_to(CUSTOMER))

    # (4) A colleague joins through the staff link (their owner action comes with the orders).
    await demo.join_as_staff(STAFF)

    # (8) The shop: a catalog revision, then orders from the Capability Center.
    await agent_adds_a_catalog(demo)
    dry = await demo.post("/capabilities/orders/enable", {"dry_run": True})
    assert dry["plan"]["will_enable"] == ["orders"] and dry["plan"]["needs_agent"] is False
    assert (await demo.toggle("orders"))["revision_number"] == 4
    product = (await demo.post("/data/product", {"data": {"title": "قهوه", "price": 120000}}, expect=201))[
        "id"
    ]

    # ... in the simulator (sandbox): browse, add, cart, checkout; the owner persona confirms.
    async with demo.sessions() as session:  # the sandbox has its own records
        sandbox = PgStore(session, demo.bot.id, "sandbox", "owner")
        item = (await sandbox.create_record("product", {"title": "قهوه", "price": 120000}, now=start)).id
        await session.commit()
    assert "قهوه" in texts(await demo.sim("ali", "nav:go:shop"), "ali")
    await demo.sim("ali", f"orders:add:{item}")
    assert "۱۲۰٬۰۰۰ تومان" in texts(await demo.sim("ali", "orders:cart:"), "ali")
    placed = await demo.sim("ali", "orders:chk:")
    [outcome] = placed["outcomes"]
    assert (outcome["action"], outcome["result"]) == ("order", "submitted")
    confirmed = await demo.sim("owner", f"orders:own:{outcome['record_id']}.confirm")
    assert confirmed["outcomes"][-1]["result"] != "rejected"
    assert "تأییدشده" in texts(confirmed, "ali")  # the customer persona hears about it
    sandbox_report = await demo.report("orders", env="sandbox")
    assert sandbox_report["order_count"]["value"] == 1 and sandbox_report["revenue"]["value"] == 120000

    # ... and live in Telegram: the customer orders, the staff member confirms, the web admin delivers.
    await customer.press(f"orders:add:{product}")
    await customer.press("orders:chk:")
    [order] = await demo.orders()
    assert order["status"] == "new" and order["data"]["total"] == 120000
    await demo.chat(STAFF).press(f"orders:own:{order['id']}.confirm")
    assert (await demo.orders())[0]["status"] == "confirmed"
    delivered = await demo.post(f"/data/orders/{order['id']}/actions/deliver")
    assert delivered["ok"] is True and (await demo.orders())[0]["status"] == "delivered"
    live_report = await demo.report("orders")
    assert live_report["order_count"]["value"] == 1 and live_report["revenue"]["value"] == 120000

    # (6) Copilot: off by default (409); enabled, it answers from the events report.
    ask = {"messages": [{"role": "user", "content": "ثبت‌نام رویدادها این هفته چطور بود؟"}]}
    disabled = await demo.post("/copilot/messages", ask, expect=409)
    assert disabled["error"]["code"] == "capability_disabled"
    await demo.toggle("copilot")
    call = ToolCall("get_capability_report", {"capability_key": "events", "period": "7d"})
    demo.llm = FakeLLM(loops={"copilot": [[[call], [ToolCall("finish", {"reply": "۱ ثبت‌نام قطعی."})]]]})
    answer = await demo.post("/copilot/messages", ask)
    assert answer["reply"] == "۱ ثبت‌نام قطعی."
    assert [c["name"] for c in answer["tool_calls"]] == ["get_capability_report"]
    tool_metrics = {m["id"]: m for m in demo.llm.tool_results[0].content["metrics"]}
    assert tool_metrics["rsvp_count"]["value"] == 1

    # (9) The Overview: every enabled capability, its KPIs, and recent activity.
    overview = await demo.get("/reports/overview", period="7d")
    assert {"booking", "events", "info", "catalog", "orders"} <= set(overview["enabled_capabilities"])
    kpis = {k["id"]: k for k in overview["kpis"]}
    assert kpis["rsvp_count"]["value"] == 1 and kpis["order_count"]["value"] == 1
    assert kpis["revenue"]["value"] == 120000 and {"booking_count", "event_count", "customers"} <= set(kpis)
    activity = [a["text"] for a in overview["activity"]]
    assert any("سفارش" in t for t in activity) and any("کارگاه عکاسی" in t for t in activity)


# --- story 2: spreadsheet intelligence ----------------------------------------------------------


async def test_spreadsheet_intelligence_from_the_web_and_telegram(demo: Demo) -> None:
    assert (await demo.toggle("spreadsheet_intelligence"))["plan"]["will_enable"] == [
        "spreadsheet_intelligence"
    ]
    await demo.join_as_staff(STAFF)

    # (5) First upload: the inspection; the profile is drafted by the (fake) model.
    first = await demo.put_xlsx(sales_workbook(), "sales-1.xlsx")
    [sheet] = first["inspection"]["sheets"]
    assert (
        sheet["name"] == "Sales" and sheet["rows"] == 30 and [c["name"] for c in sheet["columns"]] == COLUMNS
    )
    demo.llm = FakeLLM(structured={"analysis_profile": [good_draft()]})
    profile = await demo.post("/analysis/profiles", {"upload_id": first["id"]}, expect=201)
    assert profile["sheet"] == "Sales" and profile["expected_columns"] == COLUMNS
    assert [c.task for c in demo.llm.calls] == ["analysis_profile"]
    run_url = f"/analysis/profiles/{profile['id']}/run"

    # The next file with the same layout runs deterministically.
    second = await demo.put_xlsx(sales_workbook(shift=1), "sales-2.xlsx")
    run = await demo.post(run_url, {"upload_id": second["id"]})
    assert run["status"] == "ok" and run["upload_id"] == second["id"]
    metrics = {m["id"]: m for m in run["metrics"]}
    assert metrics["row_count"]["value"] == 30 and metrics["total_revenue"]["value"] > 0

    # A staff member sends the daily file in Telegram: analysed with the matching profile.
    reply = await demo.send_document(STAFF, sales_workbook(shift=2), "sales-3.xlsx")
    assert reply.startswith("فایل «sales-3.xlsx» تحلیل شد ✅") and "موارد غیرعادی" in reply

    # A renamed column: a schema_changed result from the web, the explicit no-profile reply in Telegram.
    renamed = make_xlsx(
        {"Sales": sales_rows(columns=["Employee", "Product", "Qty", "Revenue", "Discount", "Date"])}
    )
    changed = await demo.put_xlsx(renamed, "sales-4.xlsx")
    result = await demo.post(run_url, {"upload_id": changed["id"]})
    assert result["status"] == "schema_changed"
    assert result["schema_diff"] == {"missing": ["Quantity"], "new": ["Qty"]} and result["metrics"] == []
    assert await demo.send_document(STAFF, renamed, "sales-5.xlsx") == NO_PROFILE

    # Who sent today's report; every file is kept.
    submissions = await demo.get(f"/analysis/profiles/{profile['id']}/submissions")
    assert [s["actor_id"] for s in submissions["submitted"]] == [str(STAFF)]
    uploads = await demo.get("/uploads")
    assert sorted(u["filename"] for u in uploads) == [f"sales-{i}.xlsx" for i in range(1, 6)]
    runs = await demo.get("/analysis/runs", profile_id=profile["id"])
    assert sorted(r["status"] for r in runs) == ["ok", "ok", "schema_changed"]
