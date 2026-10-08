"""Event-level tests for the orders engine (W1-ORD): browse, cart, checkout, status, stock."""

from typing import Any

from app.botspec.models import BotSpec
from app.botspec.validate import validate_spec
from app.runtime.callbacks import parse_callback
from app.runtime.contracts import Actor, Button, OutMessage, RuntimeEvent, RuntimeResponse
from app.runtime.texts import nav as nav_texts
from app.runtime.texts import orders as tx
from tests.unit.runtime.harness import T0, Harness, button_data, text

CAP = "shop"


def shop_spec(**over: Any) -> BotSpec:
    cap: dict[str, Any] = {
        "type": "orders",
        "key": CAP,
        "title": "فروشگاه",
        "resource": "product",
        "price_field": "price",
        "stock_field": "stock",
        "checkout_fields": [
            {"key": "address", "label": "نشانی", "type": "long_text"},
            {"key": "phone", "label": "تلفن", "type": "phone"},
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
            {"key": "reopen", "label": "بازگشایی", "from_statuses": ["cancelled"], "to_status": "new"},
        ],
        "cancellable_statuses": ["new"],
        "notify_owner_on": ["placed", "cancelled"],
        **over,
    }
    spec = BotSpec.model_validate(
        {
            "bot": {"name": "فروشگاه نمونه", "welcome_text": "خوش آمدید!"},
            "resources": [
                {
                    "key": "product",
                    "label": "کالا",
                    "label_plural": "کالاها",
                    "title_field": "title",
                    "fields": [
                        {"key": "title", "label": "نام", "type": "text"},
                        {"key": "price", "label": "قیمت", "type": "integer"},
                        {"key": "stock", "label": "موجودی", "type": "integer", "required": False},
                    ],
                }
            ],
            "capabilities": [cap],
            "menu": [
                {"key": "shop_menu", "label": "فروشگاه", "capability": CAP},
                {"key": "my_orders", "label": "سفارش‌های من", "capability": CAP, "view": "mine"},
            ],
        }
    )
    if cap.get("enabled", True):  # a disabled-only menu is itself a spec error
        assert not [i for i in validate_spec(spec) if i.severity == "error"]
    return spec


async def setup(stock_a: int | None = 3, **over: Any) -> tuple[Harness, int, int]:
    h = Harness(shop_spec(**over))
    a = await h.seed("product", {"title": "قهوه", "price": 120000, "stock": stock_a})
    b = await h.seed("product", {"title": "کیک", "price": 50000, "stock": None})
    return h, a, b


def find(resp: RuntimeResponse, action: str, arg: str | int | None = None) -> Button:
    for row in resp.messages[-1].buttons:
        for b in row:
            _, act, a = parse_callback(b.data)
            if act == action and (arg is None or a == str(arg)):
                return b
    raise AssertionError(f"no {action}:{arg} button; have {button_data(resp)}")


def notices(resp: RuntimeResponse, actor: str) -> list[OutMessage]:
    return [m for m in resp.messages if m.to_actor_id == actor and m.notice]


async def checkout(h: Harness, actor: str = "ali") -> RuntimeResponse:
    await h.tap(actor, f"{CAP}:chk:")
    await h.send(actor, "تهران، خیابان آزادی")
    return await h.send(actor, "09121234567")


async def stock(h: Harness, item: int) -> Any:
    rec = await h.store.get_record("product", item)
    assert rec is not None
    return rec.data["stock"]


async def test_happy_path_browse_cart_checkout() -> None:
    h, a, b = await setup()
    listing = await h.tap("ali", "menu:open:shop_menu")
    assert "قهوه — ۱۲۰٬۰۰۰ تومان" in text(listing)
    item = await h.tap("ali", find(listing, "item", a).data)
    assert "موجودی: ۳" in text(item)
    await h.tap("ali", find(item, "add", a).data)
    await h.tap("ali", f"{CAP}:add:{a}")
    added = await h.tap("ali", f"{CAP}:add:{b}")
    assert "تعداد: ۱" in text(added) and added.outcomes == []
    cart = await h.tap("ali", find(added, "cart").data)
    assert "جمع کل: ۲۹۰٬۰۰۰ تومان" in text(cart)
    cart = await h.tap("ali", find(cart, "dec", b).data)
    assert "کیک" not in text(cart) and "۲۴۰٬۰۰۰ تومان" in text(cart)
    await h.tap("ali", f"{CAP}:add:{b}")
    asked = await h.tap("ali", find(await h.tap("ali", f"{CAP}:cart:"), "chk").data)
    assert "۲۹۰٬۰۰۰ تومان" in text(asked) and "نشانی" in text(asked)
    await h.send("ali", "تهران، خیابان آزادی")
    placed = await h.send("ali", "09121234567")

    (out,) = placed.outcomes
    assert (out.action, out.result) == ("order", "submitted") and out.record_id is not None
    order = await h.store.get_record(CAP, out.record_id)
    assert order is not None and order.status == "new" and order.actor_id == "ali"
    assert order.data["total"] == 290000 and order.data["payment_status"] == "unpaid"
    assert order.data["address"] == "تهران، خیابان آزادی"
    assert order.data["items"] == [
        {"item_id": a, "title": "قهوه", "qty": 2, "unit_price": 120000},
        {"item_id": b, "title": "کیک", "qty": 1, "unit_price": 50000},
    ]
    lines = await h.store.list_records(f"{CAP}.lines")
    assert [(ln.data["order_id"], ln.item_id, ln.data["qty"]) for ln in lines] == [
        (order.id, a, 2),
        (order.id, b, 1),
    ]
    assert await stock(h, a) == 1 and await stock(h, b) is None
    assert await h.store.list_records(f"{CAP}.cart") == []
    to_ali = [m for m in placed.messages if m.to_actor_id == "ali"]
    assert f"شمارهٔ سفارش: {order.id}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")) in to_ali[-1].text
    (owner,) = notices(placed, "owner")
    assert owner.notice == "ordered" and "۲۹۰٬۰۰۰ تومان" in owner.text
    assert [b.data for row in owner.buttons for b in row] == [
        f"{CAP}:own:{order.id}.send",
        f"{CAP}:own:{order.id}.drop",
    ]
    assert {e.kind for e in placed.effects} >= {"record_created", "record_updated", "record_deleted"}


async def test_out_of_stock_refused_and_marked() -> None:
    h, a, _ = await setup(stock_a=1)
    await h.tap("ali", f"{CAP}:add:{a}")
    refused = await h.tap("ali", f"{CAP}:add:{a}")
    (out,) = refused.outcomes
    assert (out.result, out.reason) == ("rejected", "out_of_stock")
    # Stock drops to zero before checkout: the checkout re-check refuses and writes nothing.
    await h.store.update_record("product", a, data={"stock": 0}, now=T0)
    assert tx.OUT_OF_STOCK_MARK in text(await h.tap("ali", "menu:open:shop_menu"))
    refused = await h.tap("ali", f"{CAP}:chk:")
    assert [(o.result, o.reason) for o in refused.outcomes] == [("rejected", "out_of_stock")]
    assert await h.store.get_session("ali") is None
    assert await h.store.list_records(CAP) == []


async def test_empty_cart_checkout_rejected() -> None:
    h, _, _ = await setup()
    resp = await h.tap("ali", f"{CAP}:chk:")
    assert text(resp) == tx.TEXTS["cart_empty"]
    assert [(o.action, o.result) for o in resp.outcomes] == [("order", "rejected")]


async def test_cancel_restocks_and_notifies_owner() -> None:
    h, a, _ = await setup()
    await h.tap("ali", f"{CAP}:add:{a}")
    await h.tap("ali", f"{CAP}:add:{a}")
    order_id = (await checkout(h)).outcomes[0].record_id
    assert await stock(h, a) == 1
    mine = await h.tap("ali", "menu:open:my_orders")
    resp = await h.tap("ali", find(mine, "cancel", order_id).data)
    assert [(o.action, o.result) for o in resp.outcomes] == [("cancel", "cancelled")]
    assert await stock(h, a) == 3
    assert [m.notice for m in notices(resp, "owner")] == ["cancelled"]
    again = await h.tap("ali", f"{CAP}:cancel:{order_id}")
    assert [(o.result, o.reason) for o in again.outcomes] == [("rejected", "not_allowed")]
    assert await stock(h, a) == 3
    # Someone else's order cannot be cancelled.
    other = await h.tap("sara", f"{CAP}:cancel:{order_id}")
    assert [(o.result, o.reason) for o in other.outcomes] == [("rejected", "not_found")]


async def test_not_cancellable_without_cancelled_status() -> None:
    statuses = [{"key": "new", "label": "جدید"}, {"key": "sent", "label": "ارسال‌شده"}]
    actions = [{"key": "send", "label": "ارسال", "from_statuses": ["new"], "to_status": "sent"}]
    h, a, _ = await setup(statuses=statuses, owner_actions=actions)
    await h.tap("ali", f"{CAP}:add:{a}")
    order_id = (await checkout(h)).outcomes[0].record_id
    assert f"{CAP}:cancel:{order_id}" not in button_data(await h.tap("ali", "menu:open:my_orders"))
    resp = await h.tap("ali", f"{CAP}:cancel:{order_id}")
    assert [(o.result, o.reason) for o in resp.outcomes] == [("rejected", "not_allowed")]


async def test_owner_action_notifies_customer_and_moves_stock() -> None:
    h, a, _ = await setup()
    await h.tap("ali", f"{CAP}:add:{a}")
    order_id = (await checkout(h)).outcomes[0].record_id
    denied = await h.tap("ali", f"{CAP}:own:{order_id}.send")
    assert [(o.result, o.reason) for o in denied.outcomes] == [("rejected", "not_allowed")]
    resp = await h.admin(f"{CAP}:own:{order_id}.send")
    assert [(o.action, o.result) for o in resp.outcomes] == [("owner_action", "ok")]
    (notice,) = notices(resp, "ali")
    assert notice.notice == "order_status_changed" and "ارسال‌شده" in notice.text
    order = await h.store.get_record(CAP, order_id)  # type: ignore[arg-type]
    assert order is not None and order.status == "sent" and order.data["payment_status"] == "unpaid"
    stale = await h.admin(f"{CAP}:own:{order_id}.send")
    assert [(o.result, o.reason) for o in stale.outcomes] == [("rejected", "not_allowed")]

    await h.tap("ali", f"{CAP}:add:{a}")
    second = (await checkout(h)).outcomes[0].record_id
    assert await stock(h, a) == 1
    await h.admin(f"{CAP}:own:{second}.drop")
    assert await stock(h, a) == 2
    await h.store.update_record("product", a, data={"stock": 0}, now=T0)
    short = await h.admin(f"{CAP}:own:{second}.reopen")
    assert [(o.result, o.reason) for o in short.outcomes] == [("rejected", "out_of_stock")]
    await h.store.update_record("product", a, data={"stock": 1}, now=T0)
    await h.admin(f"{CAP}:own:{second}.reopen")
    assert await stock(h, a) == 0


async def test_group_chat_gets_private_chat_hint() -> None:
    h, a, _ = await setup()
    event = RuntimeEvent(
        bot_id="b1",
        env="sandbox",
        actor=Actor(id="ali", display_name="علی"),
        kind="callback",
        data=f"{CAP}:add:{a}",
        now=T0,
        chat_type="group",
    )
    resp = await h.runtime.handle(event, h.spec, h.store)
    assert [(m.text, m.edit, m.buttons) for m in resp.messages] == [(tx.GROUP_PRIVATE, False, [])]
    assert resp.outcomes == [] and resp.effects == []


async def test_disabled_orders_capability_is_stale() -> None:
    h, a, _ = await setup(enabled=False)
    assert "nav:go:shop" not in button_data(await h.start("ali"))
    for data in ("menu:open:shop_menu", "nav:go:shop", "nav:go:cart", f"{CAP}:add:{a}", f"{CAP}:chk:"):
        resp = await h.tap("ali", data)
        assert len(resp.messages) == 1 and resp.messages[0].edit is False
        assert resp.messages[0].text.startswith(nav_texts.STALE)
    assert await h.store.list_records(f"{CAP}.cart") == []
