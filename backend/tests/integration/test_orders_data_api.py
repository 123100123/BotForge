"""Orders in the Data API: the ``orders`` collection listing (kind, enabled flag, columns, statuses,
actions), its rows (items summary, customer name) and owner actions through ``data_actions``. The
order is placed by a customer through the real webhook (fake Telegram client). Needs a database."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.models import RecordRow
from app.integrations.telegram.client import FakeTelegramClient
from app.runtime.formatting import to_persian_digits
from app.runtime.pg_store import PgStore
from tests.integration.helpers import SessionFactory
from tests.integration.tg_helpers import ALICE, Chat, LiveBot, make_live_bot

BOB = {"X-Test-User": "bob"}
SHOP = "shop"
OWNER, CUSTOMER = 900, 8401

SHOP_SPEC: dict[str, Any] = {
    "bot": {"name": "کافه نمونه", "welcome_text": "خوش آمدید!"},
    "resources": [
        {
            "key": "product",
            "label": "کالا",
            "label_plural": "کالاها",
            "title_field": "title",
            "fields": [
                {"key": "title", "label": "نام", "type": "text"},
                {"key": "price", "label": "قیمت", "type": "integer"},
            ],
        }
    ],
    "capabilities": [
        {"type": "catalog", "key": "menu_items", "title": "منو", "resource": "product", "detail_fields": []},
        {
            "type": "orders",
            "key": SHOP,
            "title": "سفارش آنلاین",
            "resource": "product",
            "price_field": "price",
            "checkout_fields": [
                {"key": "address", "label": "نشانی", "type": "long_text"},
                {"key": "total", "label": "سایه‌خورده", "type": "text", "required": False},
            ],
            "statuses": [
                {"key": "new", "label": "جدید"},
                {"key": "sent", "label": "ارسال‌شده"},
                {"key": "cancelled", "label": "لغوشده"},
            ],
            "initial_status": "new",
            "owner_actions": [
                {"key": "send", "label": "ارسال", "from_statuses": ["new"], "to_status": "sent"},
                {"key": "drop", "label": "رد سفارش", "from_statuses": ["new"], "to_status": "cancelled"},
            ],
            "cancellable_statuses": ["new"],
        },
    ],
    "menu": [
        {"key": "menu_list", "label": "منو", "capability": "menu_items"},
        {"key": "shop_menu", "label": "سفارش", "capability": SHOP},
        {"key": "my_orders", "label": "سفارش‌های من", "capability": SHOP, "view": "mine"},
    ],
}


@pytest.fixture
async def bot(session_factory: SessionFactory, tg_env: None) -> LiveBot:
    return await make_live_bot(session_factory, SHOP_SPEC, owner_actor_id=str(OWNER))


async def place_order(client: httpx.AsyncClient, bot: LiveBot, fake: FakeTelegramClient) -> int:
    """Two coffees through the webhook: add, add, checkout, answer the form (address, skip the rest)."""
    created = await client.post(
        f"/bots/{bot.id}/data/product", json={"data": {"title": "قهوه", "price": 120000}}, headers=ALICE
    )
    assert created.status_code == 201, created.text
    product = created.json()["id"]
    chat = Chat(client, bot, fake, CUSTOMER)
    await chat.say("/start")
    await chat.press(f"{SHOP}:add:{product}")
    await chat.press(f"{SHOP}:add:{product}")
    await chat.press(f"{SHOP}:chk:")
    assert "نشانی" in chat.last_text()
    await chat.say("تهران، خیابان انقلاب")
    await chat.press(f"{SHOP}:skip:")  # the optional field
    listing = await client.get(f"/bots/{bot.id}/data/{SHOP}", headers=ALICE)
    assert listing.status_code == 200 and listing.json()["total"] == 1, listing.text
    return int(listing.json()["items"][0]["id"])


async def order_status(session_factory: SessionFactory, order_id: int) -> str | None:
    async with session_factory() as session:
        return (await session.execute(select(RecordRow.status).where(RecordRow.id == order_id))).scalar_one()


async def test_the_orders_collection_is_listed_with_its_columns(
    tg_client: httpx.AsyncClient, bot: LiveBot
) -> None:
    response = await tg_client.get(f"/bots/{bot.id}/data", headers=ALICE)
    assert response.status_code == 200, response.text
    collections = {c["key"]: c for c in response.json()["collections"]}
    orders = collections[SHOP]
    assert (orders["kind"], orders["label"], orders["writable"], orders["enabled"]) == (
        "orders",
        "سفارش آنلاین",
        False,
        True,
    )
    assert orders["resource"] == "product"
    # synthetic columns first, then the checkout fields; one named like a system key is shadowed
    assert [f["key"] for f in orders["fields"]] == ["items_summary", "total", "payment_status", "address"]
    assert [c["key"] for c in orders["system_columns"]] == ["actor_id", "status", "created_at"]
    assert [s["key"] for s in orders["statuses"]] == ["new", "sent", "cancelled"]
    assert [(a["key"], a["from_statuses"]) for a in orders["actions"]] == [
        ("send", ["new"]),
        ("drop", ["new"]),
    ]
    assert collections["product"]["kind"] == "resource" and collections["product"]["writable"] is True
    # the helper collections are not listed and stay unknown
    assert not {f"{SHOP}.cart", f"{SHOP}.lines"} & set(collections)
    assert (await tg_client.get(f"/bots/{bot.id}/data/{SHOP}.cart", headers=ALICE)).status_code == 404


async def test_a_disabled_orders_capability_is_listed_as_disabled(
    tg_client: httpx.AsyncClient, bot: LiveBot
) -> None:
    off = await tg_client.post(f"/bots/{bot.id}/capabilities/orders/disable", json={}, headers=ALICE)
    assert off.status_code == 200 and off.json()["applied"] is True, off.text
    collections = {
        c["key"]: c
        for c in (await tg_client.get(f"/bots/{bot.id}/data", headers=ALICE)).json()["collections"]
    }
    assert collections[SHOP]["kind"] == "orders" and collections[SHOP]["enabled"] is False
    assert collections["product"]["enabled"] is True  # resources are always enabled


async def test_order_rows_and_owner_actions(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    order_id = await place_order(tg_client, bot, fake_tg)
    [row] = (await tg_client.get(f"/bots/{bot.id}/data/{SHOP}", headers=ALICE)).json()["items"]
    assert (row["status"], row["actor_id"], row["actor_name"], row["item_id"]) == (
        "new",
        str(CUSTOMER),
        "کاربر",
        None,
    )
    assert row["data"]["items_summary"] == "قهوه × 2"
    assert row["data"]["total"] == 240000 and row["data"]["payment_status"] == "unpaid"
    assert row["data"]["address"] == "تهران، خیابان انقلاب"
    async with session_factory() as session:  # items_summary is computed for the response, never stored
        stored = await PgStore(session, bot.id, "live").get_record(SHOP, order_id)
    assert stored is not None and "items_summary" not in stored.data

    url = f"/bots/{bot.id}/data/{SHOP}/{order_id}/actions"
    sent_before = len(fake_tg.sent_to(CUSTOMER))
    done = await tg_client.post(f"{url}/send", headers=ALICE)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["ok"] is True and body["outcome"]["action"] == "owner_action"
    assert body["outcome"]["record_id"] == order_id
    assert await order_status(session_factory, order_id) == "sent"
    # the customer hears about the status change in Telegram
    notices = [m["text"] for m in fake_tg.sent_to(CUSTOMER)[sent_before:]]
    assert any("وضعیت جدید: ارسال‌شده" in t and to_persian_digits(order_id) in t for t in notices), notices
    listed = (await tg_client.get(f"/bots/{bot.id}/data/{SHOP}", headers=ALICE)).json()["items"]
    assert listed[0]["status"] == "sent"

    # not allowed from the current status: a rejected outcome, nothing changes
    again = await tg_client.post(f"{url}/drop", headers=ALICE)
    assert again.status_code == 200 and again.json()["ok"] is False
    assert again.json()["outcome"]["result"] == "rejected"
    assert await order_status(session_factory, order_id) == "sent"


async def test_owner_action_errors(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    order_id = await place_order(tg_client, bot, fake_tg)
    base = f"/bots/{bot.id}/data/{SHOP}"
    unknown = await tg_client.post(f"{base}/{order_id}/actions/teleport", headers=ALICE)
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "invalid_action"
    missing = await tg_client.post(f"{base}/{order_id + 10_000}/actions/send", headers=ALICE)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "record_not_found"
    foreign = await tg_client.post(f"{base}/{order_id}/actions/send", headers=BOB)
    assert foreign.status_code == 404
    # orders are read-only in the Data API: no create, edit or delete
    created = await tg_client.post(base, json={"data": {"total": 1}}, headers=ALICE)
    assert created.status_code == 405 and created.json()["error"]["code"] == "read_only_collection"
    edited = await tg_client.patch(f"{base}/{order_id}", json={"data": {"total": 1}}, headers=ALICE)
    assert edited.status_code == 405
    assert (await tg_client.delete(f"{base}/{order_id}", headers=ALICE)).status_code == 405
