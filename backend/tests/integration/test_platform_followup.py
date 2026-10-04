"""Platform follow-up: data enrichment, field errors, rollback/test-run details, bot deletion,
request admin actions, id bounds, Telegram status. Needs a database."""

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Bot, RecordRow, Revision
from app.integrations.telegram.client import FakeTelegramClient
from app.runtime.pg_store import PgStore
from tests.integration.conftest import MakeBot
from tests.integration.helpers import NOW, REPO, SessionFactory
from tests.integration.test_webhook import WORKSHOP
from tests.integration.tg_helpers import (
    ALICE,
    CAP,
    Chat,
    LiveBot,
    capacity_spec,
    make_live_bot,
    new_token,
)

OWNER_TG_ID = 900
BIG = 2**63


@pytest.fixture
async def bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    return await make_live_bot(
        session_factory, capacity_spec(golden_spec, 1), owner_actor_id=str(OWNER_TG_ID)
    )


@pytest.fixture
async def repair_bot(session_factory: SessionFactory, tg_env: None) -> LiveBot:
    spec = json.loads((REPO / "examples" / "repair.botspec.json").read_text(encoding="utf-8"))
    return await make_live_bot(session_factory, spec, owner_actor_id=str(OWNER_TG_ID))


async def add_workshop(client: httpx.AsyncClient, bot: LiveBot) -> int:
    response = await client.post(f"/bots/{bot.id}/data/workshop", json={"data": WORKSHOP}, headers=ALICE)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- 1. data enrichment ---------------------------------------------------------------------------


async def test_collections_carry_timezone_statuses_and_actions(
    tg_client: httpx.AsyncClient, bot: LiveBot
) -> None:
    body = (await tg_client.get(f"/bots/{bot.id}/data", headers=ALICE)).json()
    by_key = {c["key"]: c for c in body["collections"]}
    booking = by_key[CAP]
    assert booking["timezone"] == "Asia/Tehran"
    assert booking["statuses"] == [
        {"key": "confirmed", "label": "قطعی"},
        {"key": "waitlisted", "label": "در لیست انتظار"},
        {"key": "cancelled", "label": "لغو شده"},
    ]
    assert booking["actions"] == [
        {"key": "cancel", "label": "لغو ثبت‌نام", "from_statuses": ["confirmed", "waitlisted"]}
    ]
    resource = by_key["workshop"]
    assert resource["timezone"] == "Asia/Tehran"
    assert resource["statuses"] == [] and resource["actions"] == []


async def test_request_collection_statuses_and_actions_come_from_the_spec(
    tg_client: httpx.AsyncClient, repair_bot: LiveBot
) -> None:
    body = (await tg_client.get(f"/bots/{repair_bot.id}/data", headers=ALICE)).json()
    repair = next(c for c in body["collections"] if c["key"] == "repair")
    assert repair["kind"] == "request" and repair["timezone"] == "Asia/Tehran"
    assert [s["key"] for s in repair["statuses"]] == ["new", "approved", "rejected", "done"]
    assert repair["statuses"][1] == {"key": "approved", "label": "تأیید شده"}
    assert repair["actions"][0] == {"key": "approve", "label": "تأیید", "from_statuses": ["new"]}
    assert [a["key"] for a in repair["actions"]] == ["approve", "reject", "mark_done"]


async def test_booking_records_carry_actor_name_and_item_title(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    await Chat(tg_client, bot, fake_tg, 601).press(f"{CAP}:book:{item}")
    await Chat(tg_client, bot, fake_tg, 602).press(f"{CAP}:book:{item}")
    page = (await tg_client.get(f"/bots/{bot.id}/data/{CAP}", headers=ALICE)).json()
    assert page["total"] == 2
    row = page["items"][0]
    assert set(row) == {
        "id",
        "collection",
        "data",
        "status",
        "actor_id",
        "item_id",
        "created_at",
        "updated_at",
        "actor_name",
        "item_title",
    }
    assert row["actor_name"] == "کاربر" and row["item_title"] == "کارگاه عکاسی"
    assert row["item_id"] == item
    assert {r["actor_id"] for r in page["items"]} == {"601", "602"}

    resources = (await tg_client.get(f"/bots/{bot.id}/data/workshop", headers=ALICE)).json()
    assert resources["items"][0]["actor_name"] is None and resources["items"][0]["item_title"] is None


async def test_unknown_actor_and_missing_item_give_nulls(
    tg_client: httpx.AsyncClient, bot: LiveBot, session_factory: SessionFactory
) -> None:
    async with session_factory() as session:
        await PgStore(session, bot.id, "live", None).create_record(
            CAP, {}, status="confirmed", actor_id="777", item_id=None, now=NOW
        )
        await PgStore(session, bot.id, "live", None).create_record(
            CAP, {}, status="confirmed", actor_id="778", item_id=424242, now=NOW
        )
        await session.commit()
    page = (await tg_client.get(f"/bots/{bot.id}/data/{CAP}", headers=ALICE)).json()
    assert len(page["items"]) == 2
    assert all(r["actor_name"] is None and r["item_title"] is None for r in page["items"])


async def test_listing_enrichment_uses_a_constant_number_of_queries(
    tg_client: httpx.AsyncClient, bot: LiveBot, session_factory: SessionFactory
) -> None:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    async with session_factory() as session:
        store = PgStore(session, bot.id, "live", None)
        for n in range(30):
            item = await store.create_record("workshop", {"title": f"w{n}"}, now=NOW)
            await store.create_record(CAP, {}, status="confirmed", actor_id=str(n), item_id=item.id, now=NOW)
        await session.commit()
    seen: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", count)
    try:
        page = (await tg_client.get(f"/bots/{bot.id}/data/{CAP}?limit=50", headers=ALICE)).json()
    finally:
        event.remove(Engine, "before_cursor_execute", count)
    assert len(page["items"]) == 30 and all(r["item_title"] for r in page["items"])
    assert len(seen) < 12  # bot, revision, count, page, names, items: not one query per row


# --- 2. field errors ------------------------------------------------------------------------------


async def test_invalid_record_has_details_and_field_errors(
    tg_client: httpx.AsyncClient, bot: LiveBot
) -> None:
    response = await tg_client.post(
        f"/bots/{bot.id}/data/workshop", json={"data": {"title": "x", "price": "abc"}}, headers=ALICE
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_record" and error["message"]
    assert all(isinstance(d, str) for d in error["details"])
    fields = [e["field"] for e in error["field_errors"]]
    assert "price" in fields and "teacher" in fields and "title" not in fields
    assert [e["message"] for e in error["field_errors"]] == error["details"]
    assert all(set(e) == {"field", "message"} for e in error["field_errors"])


async def test_patch_validation_errors_also_have_field_errors(
    tg_client: httpx.AsyncClient, bot: LiveBot
) -> None:
    item = await add_workshop(tg_client, bot)
    response = await tg_client.patch(
        f"/bots/{bot.id}/data/workshop/{item}", json={"data": {"price": "abc"}}, headers=ALICE
    )
    assert response.status_code == 400
    assert [e["field"] for e in response.json()["error"]["field_errors"]] == ["price"]


def test_validate_record_detailed_and_validate_record_agree() -> None:
    from app.botspec.models import FieldDef
    from app.botspec.records import validate_record, validate_record_detailed

    fields = [
        FieldDef(key="a", label="الف", type="text"),
        FieldDef(key="b", label="ب", type="integer"),
        FieldDef(key="c", label="ج", type="text", required=False),
    ]
    cleaned, detailed = validate_record_detailed(fields, {"b": "x"})
    assert [k for k, _ in detailed] == ["a", "b"]
    assert validate_record(fields, {"b": "x"}) == (cleaned, [m for _, m in detailed])


# --- 3. revisions ---------------------------------------------------------------------------------


async def test_detail_lists_are_empty_not_null_and_tests_run_derives_scenarios(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, revision_id = await make_bot("alice")  # no stored scenarios (like load_spec.py)
    detail = (await tg_client.get(f"/revisions/{revision_id}", headers=ALICE)).json()
    assert detail["scenarios"] == [] and detail["superseded"] == []
    assert detail["test_report"] is None

    response = await tg_client.post(f"/revisions/{revision_id}/tests/run", headers=ALICE)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["total"] > 0 and report["failed"] == 0 and report["passed"] == report["total"]

    after = (await tg_client.get(f"/revisions/{revision_id}", headers=ALICE)).json()
    assert len(after["scenarios"]) == report["total"]
    assert after["test_report"]["total"] == report["total"]
    listed = (await tg_client.get(f"/bots/{bot_id}/revisions", headers=ALICE)).json()
    assert listed[0]["tests"] == {"total": report["total"], "passed": report["total"], "failed": 0}
    async with session_factory() as session:
        row = await session.get(Revision, revision_id)
        assert row is not None and len(row.scenarios or []) == report["total"]


# --- 4. deleting a connected bot ------------------------------------------------------------------


async def test_deleting_a_connected_bot_removes_its_webhook_first(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    response = await tg_client.delete(f"/bots/{bot.id}", headers=ALICE)
    assert response.status_code == 204
    assert len(fake_tg.calls_to("deleteWebhook")) == 1 and fake_tg.tokens == [bot.token]
    async with session_factory() as session:
        assert await session.get(Bot, bot.id) is None


async def test_webhook_removal_failure_never_blocks_the_delete(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    fake_tg.fail_methods["deleteWebhook"] = "Unauthorized"
    assert (await tg_client.delete(f"/bots/{bot.id}", headers=ALICE)).status_code == 204
    async with session_factory() as session:
        assert await session.get(Bot, bot.id) is None


async def test_deleting_an_unconnected_bot_calls_nothing(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    assert (await tg_client.delete(f"/bots/{bot_id}", headers=ALICE)).status_code == 204
    assert fake_tg.calls == []


# --- 5. request admin actions end to end ---------------------------------------------------------


async def submit_request(
    client: httpx.AsyncClient, bot: LiveBot, fake: FakeTelegramClient
) -> tuple[Chat, int]:
    customer = Chat(client, bot, fake, 601)
    await customer.press("menu:open:new_request")
    await customer.press(customer.data_with("repair:new:"))
    for answer in ("یخچال", "صدا می‌دهد", "09123456789", "تهران، خیابان آزادی"):
        await customer.say(answer)
    page = (await client.get(f"/bots/{bot.id}/data/repair", headers=ALICE)).json()
    assert page["total"] == 1, page
    return customer, page["items"][0]["id"]


def action_url(bot: LiveBot, record_id: int, name: str) -> str:
    return f"/bots/{bot.id}/data/repair/{record_id}/actions/{name}"


async def test_approve_changes_status_notifies_the_customer_and_reports_ok(
    tg_client: httpx.AsyncClient,
    repair_bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    customer, record_id = await submit_request(tg_client, repair_bot, fake_tg)
    listed = (await tg_client.get(f"/bots/{repair_bot.id}/data/repair", headers=ALICE)).json()["items"][0]
    assert listed["status"] == "new" and listed["actor_name"] == "کاربر" and listed["item_title"] is None

    before = len(customer.shown())
    response = await tg_client.post(action_url(repair_bot, record_id, "approve"), headers=ALICE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["message"]
    assert body["outcome"]["action"] == "owner_action" and body["outcome"]["result"] == "ok"
    assert body["outcome"]["record_id"] == record_id

    async with session_factory() as session:
        row = (
            await session.execute(
                select(RecordRow).where(RecordRow.id == record_id, RecordRow.bot_id == repair_bot.id)
            )
        ).scalar_one()
    assert row.status == "approved"
    assert len(customer.shown()) == before + 1  # the customer was notified in Telegram
    assert fake_tg.sent_to(OWNER_TG_ID) == [] or all(
        k["text"] != body["message"] for k in fake_tg.sent_to(OWNER_TG_ID)
    )  # the owner's reply goes to the web admin only


async def test_an_action_not_allowed_from_the_current_status_is_not_ok(
    tg_client: httpx.AsyncClient, repair_bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    customer, record_id = await submit_request(tg_client, repair_bot, fake_tg)
    first = await tg_client.post(action_url(repair_bot, record_id, "approve"), headers=ALICE)
    assert first.json()["ok"] is True
    before = len(customer.shown())
    again = await tg_client.post(
        action_url(repair_bot, record_id, "approve"), headers=ALICE
    )  # approved -> approve
    assert again.status_code == 200
    body = again.json()
    assert body["ok"] is False and body["outcome"]["result"] == "rejected" and body["message"]
    assert len(customer.shown()) == before  # a refused action notifies nobody
    done = await tg_client.post(action_url(repair_bot, record_id, "mark_done"), headers=ALICE)
    assert done.json()["ok"] is True


async def test_unknown_request_action_is_a_400(
    tg_client: httpx.AsyncClient, repair_bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    _, record_id = await submit_request(tg_client, repair_bot, fake_tg)
    response = await tg_client.post(action_url(repair_bot, record_id, "explode"), headers=ALICE)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_action"


# --- 6. id bounds ---------------------------------------------------------------------------------


@pytest.mark.parametrize("record_id", [BIG, BIG * 1000, 0, -1])
async def test_out_of_range_record_ids_are_rejected_at_the_edge(
    tg_client: httpx.AsyncClient, bot: LiveBot, record_id: int
) -> None:
    calls = [
        tg_client.patch(f"/bots/{bot.id}/data/workshop/{record_id}", json={"data": {}}, headers=ALICE),
        tg_client.delete(f"/bots/{bot.id}/data/workshop/{record_id}", headers=ALICE),
        tg_client.post(f"/bots/{bot.id}/data/{CAP}/{record_id}/actions/cancel", headers=ALICE),
    ]
    for call in calls:
        response = await call
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"


async def test_largest_valid_id_is_a_plain_404(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    top = 2**63 - 1
    assert (await tg_client.delete(f"/bots/{bot.id}/data/workshop/{top}", headers=ALICE)).status_code == 404
    assert (
        await tg_client.post(f"/bots/{bot.id}/data/{CAP}/{top}/actions/cancel", headers=ALICE)
    ).status_code == 404


async def test_huge_offset_is_rejected(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    response = await tg_client.get(f"/bots/{bot.id}/data/workshop?offset={BIG}", headers=ALICE)
    assert response.status_code == 422


async def test_callback_with_an_oversized_id_is_a_stale_reply_not_an_error(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    chat = Chat(tg_client, bot, fake_tg, 650)
    for data in (f"{CAP}:book:{BIG * 10}", f"{CAP}:item:{BIG}", f"{CAP}:cancel:{BIG}"):
        response = await chat.press(data)
        assert response.status_code == 200
    assert len(chat.shown()) == 3 and all(m["text"] for m in chat.shown())


# --- 7. Telegram status ---------------------------------------------------------------------------


async def test_owner_link_disappears_once_the_owner_is_linked(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot("alice", active=True)
    connected = await tg_client.post(
        f"/bots/{bot_id}/telegram/connect", json={"token": new_token()[1]}, headers=ALICE
    )
    body = connected.json()
    assert body["owner_linked"] is False and body["owner_link"].startswith("https://t.me/")
    code = body["owner_link"].split("owner_")[1]

    # the owner opens the link in Telegram
    async with session_factory() as session:
        row = await session.get(Bot, bot_id)
        assert row is not None
        webhook_secret = row.tg_webhook_secret
    live = LiveBot(bot_id, webhook_secret or "", "", 0, None, code)
    await Chat(tg_client, live, fake_tg, 900).say(f"/start owner_{code}")

    status = (await tg_client.get(f"/bots/{bot_id}/telegram", headers=ALICE)).json()
    assert status["owner_linked"] is True and status["owner_link"] is None
    assert status["connected"] is True and status["bot_link"].startswith("https://t.me/")


async def test_owner_link_is_null_without_an_armed_code(
    tg_client: httpx.AsyncClient, bot: LiveBot, session_factory: SessionFactory
) -> None:
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None
        row.owner_actor_id = None
        row.owner_link_code = None
        await session.commit()
    status = (await tg_client.get(f"/bots/{bot.id}/telegram", headers=ALICE)).json()
    assert status["owner_linked"] is False and status["owner_link"] is None
