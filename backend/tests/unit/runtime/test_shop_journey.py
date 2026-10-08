"""U5: one commerce journey (shop -> product -> quantity -> cart -> checkout -> my orders), a
catalog-only shop without buy buttons, and the heading / Back / Home contract on the customer
screens of the other engines."""

from app.botspec.models import BotSpec
from app.runtime.callbacks import MAX_CALLBACK_BYTES, parse_callback
from app.runtime.contracts import Button, RuntimeResponse
from app.runtime.texts import orders as tx
from tests.unit.runtime.conftest import build_catalog_spec
from tests.unit.runtime.harness import Harness, buttons, text
from tests.unit.runtime.test_booking import booking_spec, seed_item
from tests.unit.runtime.test_events_preset import events_spec, seed_event
from tests.unit.runtime.test_orders import CAP, checkout, setup, shop_spec
from tests.unit.runtime.test_request import repair_spec

SHOP = "🛍 فروشگاه"


def labels(resp: RuntimeResponse) -> list[str]:
    return [b.label for b in buttons(resp)]


def find_action(resp: RuntimeResponse, action: str, arg: str | int | None = None) -> Button:
    for b in buttons(resp):
        _, act, a = b.data.split(":", 2)
        if act == action and (arg is None or a == str(arg)):
            return b
    raise AssertionError(f"no {action}:{arg} button; have {[b.data for b in buttons(resp)]}")


def no_oversize(*responses: RuntimeResponse) -> None:
    for resp in responses:
        for m in resp.messages:
            for row in m.buttons:
                for b in row:
                    assert len(b.data.encode()) <= MAX_CALLBACK_BYTES, b.data
                    parse_callback(b.data)  # still a valid callback


# --- the shop ----------------------------------------------------------------------------------


async def test_shop_list_is_headed_priced_and_ends_with_home() -> None:
    h, a, b = await setup(stock_a=3)
    r = await h.tap("ali", "nav:go:shop")
    assert text(r) == f"{SHOP}\nمحصول موردنظر را انتخاب کنید."
    assert labels(r)[:2] == ["قهوه · ۱۲۰٬۰۰۰ تومان", "کیک · ۵۰٬۰۰۰ تومان"]
    assert [x.data for x in buttons(r)[:2]] == [f"{CAP}:item:{a}", f"{CAP}:item:{b}"]
    assert labels(r)[2:] == ["📦 سفارش‌های من", "🏠 خانه"]  # no cart button while the cart is empty
    await h.tap("ali", f"{CAP}:add:{b}")
    r = await h.tap("ali", "nav:go:shop")
    assert labels(r)[2:] == ["🛒 سبد خرید (۱)", "📦 سفارش‌های من", "🏠 خانه"]
    no_oversize(r)


async def test_shop_marks_sold_out_products_and_keeps_long_labels_short() -> None:
    h, a, _ = await setup(stock_a=0)
    long_id = await h.seed("product", {"title": "نام خیلی بلند " * 8, "price": 1234567, "stock": None})
    r = await h.tap("ali", "nav:go:shop")
    by_data = {x.data: x.label for x in buttons(r)}
    assert by_data[f"{CAP}:item:{a}"] == "قهوه · ۱۲۰٬۰۰۰ تومان (ناموجود)"
    long_label = by_data[f"{CAP}:item:{long_id}"]
    assert len(long_label) <= 60 and long_label.endswith("۱٬۲۳۴٬۵۶۷ تومان")


async def test_product_quantity_add_cart_checkout_creates_one_order_with_that_quantity() -> None:
    h, a, _ = await setup(stock_a=5)
    shop = await h.tap("ali", "nav:go:shop")
    item = await h.tap("ali", find_action(shop, "item", a).data)
    assert text(item).splitlines()[0] == f"{SHOP} › قهوه"
    assert "قیمت: ۱۲۰٬۰۰۰ تومان" in text(item) and "موجودی: ۵" in text(item)
    assert labels(item)[:3] == ["➖", "۱", "➕"]
    assert labels(item)[-3:] == ["🛒 سبد خرید", "‹ فروشگاه", "🏠 خانه"]

    plus = buttons(item)[2]
    item = await h.tap("ali", plus.data)  # ➕ -> 2, the same message edited
    assert item.messages[-1].edit is True and labels(item)[:3] == ["➖", "۲", "➕"]
    item = await h.tap("ali", buttons(item)[0].data)  # ➖ -> 1
    assert labels(item)[1] == "۱"
    item = await h.tap("ali", buttons(item)[2].data)
    assert labels(item)[1] == "۲"

    added = await h.tap("ali", find_action(item, "add").data)
    assert text(added) == "۲ عدد قهوه به سبد اضافه شد."
    assert labels(added) == ["🛒 سبد خرید (۲)", "ادامهٔ خرید", "🏠 خانه"]

    cart = await h.tap("ali", buttons(added)[0].data)
    assert text(cart).splitlines()[0] == f"{SHOP} › 🛒 سبد خرید"
    assert "• قهوه × ۲ — ۲۴۰٬۰۰۰ تومان" in text(cart) and "جمع کل: ۲۴۰٬۰۰۰ تومان" in text(cart)
    assert labels(cart) == ["➖ قهوه", "ثبت سفارش", "ادامهٔ خرید", "🏠 خانه"]

    placed = await checkout(h)
    (out,) = placed.outcomes
    order = await h.store.get_record(CAP, out.record_id)  # type: ignore[arg-type]
    assert order is not None and [(e["item_id"], e["qty"]) for e in order.data["items"]] == [(a, 2)]
    assert len(await h.store.list_records(CAP)) == 1
    mine_msg = [m for m in placed.messages if m.to_actor_id == "ali"][-1]
    assert mine_msg.text.startswith(f"سفارش شما با کد {'۰۱۲۳۴۵۶۷۸۹'[order.id]} ثبت شد.")
    assert [b.label for row in mine_msg.buttons for b in row] == ["📦 سفارش‌های من", "🏠 خانه"]

    mine = await h.tap("ali", mine_msg.buttons[0][0].data)
    assert text(mine).splitlines()[0] == "📦 سفارش‌های من"
    assert "جدید" in text(mine) and "۲۴۰٬۰۰۰ تومان" in text(mine)
    assert labels(mine)[-2:] == [SHOP, "🏠 خانه"]
    no_oversize(shop, item, added, cart, placed, mine)


async def test_quantity_never_goes_beyond_the_stock_and_add_respects_it() -> None:
    h, a, _ = await setup(stock_a=2)
    item = await h.tap("ali", f"{CAP}:item:{a}")
    item = await h.tap("ali", buttons(item)[2].data)
    item = await h.tap("ali", buttons(item)[2].data)  # ➕ at the top stays at 2
    assert labels(item)[1] == "۲"
    forged = await h.tap("ali", f"{CAP}:add:{a}.9")  # a quantity the stock cannot cover
    assert [(o.result, o.reason) for o in forged.outcomes] == [("rejected", "out_of_stock")]
    assert await h.store.list_records(f"{CAP}.cart") == []
    await h.tap("ali", f"{CAP}:add:{a}.2")
    again = await h.tap("ali", f"{CAP}:add:{a}")
    assert [(o.result, o.reason) for o in again.outcomes] == [("rejected", "out_of_stock")]
    cart = (await h.store.list_records(f"{CAP}.cart"))[0]
    assert cart.data["items"] == [{"item_id": a, "qty": 2}]


async def test_adding_more_of_a_product_already_in_the_cart_says_so() -> None:
    h, a, _ = await setup(stock_a=None)
    await h.tap("ali", f"{CAP}:add:{a}.2")
    r = await h.tap("ali", f"{CAP}:add:{a}.3")
    assert text(r) == "۳ عدد قهوه به سبد اضافه شد.\nدر سبد شما: ۵ عدد"
    assert labels(r)[0] == "🛒 سبد خرید (۵)"


async def test_sold_out_product_states() -> None:
    h, a, _ = await setup(stock_a=0)
    item = await h.tap("ali", f"{CAP}:item:{a}")
    assert tx.SOLD_OUT in text(item) and "➖" not in labels(item)
    r = await h.tap("ali", find_action(item, "add").data)
    assert text(r) == "این محصول تمام شده است."
    assert labels(r) == [SHOP, "🏠 خانه"]
    assert [(o.result, o.reason) for o in r.outcomes] == [("rejected", "out_of_stock")]
    gone = await h.tap("ali", f"{CAP}:item:9999")
    assert text(gone) == tx.ITEM_UNAVAILABLE and labels(gone) == [SHOP, "🏠 خانه"]


async def test_empty_cart_offers_the_shop() -> None:
    h, _, _ = await setup()
    r = await h.tap("ali", "nav:go:cart")
    assert text(r) == f"{SHOP} › 🛒 سبد خرید\nسبد خرید شما خالی است."
    assert labels(r) == [SHOP, "🏠 خانه"]


async def test_back_buttons_point_to_the_parent_route() -> None:
    h, a, _ = await setup()
    item = await h.tap("ali", f"{CAP}:item:{a}")
    assert buttons(item)[-2].data == "nav:go:shop" and buttons(item)[-1].data == "nav:go:home"
    shop = await h.tap("ali", buttons(item)[-2].data)
    assert text(shop).startswith(SHOP) and f"{CAP}:item:{a}" in [b.data for b in buttons(shop)]


async def test_order_no_longer_cancellable_gets_a_specific_message() -> None:
    h, a, _ = await setup()
    await h.tap("ali", f"{CAP}:add:{a}")
    order_id = (await checkout(h)).outcomes[0].record_id
    await h.admin(f"{CAP}:own:{order_id}.send")  # shipped: no longer cancellable
    r = await h.tap("ali", f"{CAP}:cancel:{order_id}")
    assert text(r) == "این سفارش دیگر قابل لغو نیست."
    assert labels(r) == ["📦 سفارش‌های من", "🏠 خانه"]
    assert [(o.result, o.reason) for o in r.outcomes] == [("rejected", "not_allowed")]


async def test_several_shops_name_the_shop_in_the_heading() -> None:
    spec = shop_spec()
    data = spec.model_dump(mode="json")
    second = {**data["capabilities"][0], "key": "gifts", "title": "هدیه‌ها"}
    h = Harness(BotSpec.model_validate({**data, "capabilities": [*data["capabilities"], second]}))
    await h.seed("product", {"title": "قهوه", "price": 1000, "stock": 3})
    assert text(await h.tap("ali", "nav:go:shop")).splitlines()[0] == f"{SHOP} › فروشگاه"
    assert text(await h.tap("ali", "nav:go:shop~2")).splitlines()[0] == f"{SHOP} › هدیه‌ها"


# --- a catalog-only shop ------------------------------------------------------------------------


async def test_catalog_only_bot_has_no_buy_buttons() -> None:
    h = Harness(build_catalog_spec())
    rid = await h.seed("event", {"title": "قهوه", "starts_at": "2026-10-20T08:00:00+00:00", "price": 5})
    home = await h.start("ali")
    assert "nav:go:shop" in [b.data for b in buttons(home)]
    shop = await h.tap("ali", "nav:go:shop")
    assert text(shop).splitlines()[0] == "🗂 رویدادها"
    detail = await h.tap("ali", f"events:item:{rid}")
    assert text(detail).splitlines()[0] == "🗂 رویدادها › قهوه"
    for resp in (shop, detail):
        actions = {b.data.split(":")[1] for b in buttons(resp)}
        assert actions <= {"item", "list", "go"}, actions
        assert not [b for b in buttons(resp) if "تومان" in b.label or "سبد" in b.label]
    assert [b.data for b in buttons(detail)] == ["nav:go:shop", "nav:go:home"]
    no_oversize(shop, detail)


# --- headings and Back / Home on the other customer screens ------------------------------------------


async def test_booking_headings_and_back() -> None:
    h = Harness(booking_spec())
    item = await seed_item(h)
    lst = await h.tap("ali", "nav:go:bkg")
    assert text(lst).splitlines()[0] == "📅 کارگاه‌ها"
    detail = await h.tap("ali", f"book_workshop:item:{item}")
    assert text(detail).splitlines()[0] == "📅 کارگاه‌ها › کارگاه عکاسی"
    assert [b.data for b in buttons(detail)][-2:] == ["nav:go:bkg", "nav:go:home"]
    mine = await h.tap("ali", "nav:go:bkg.mine")
    assert text(mine).splitlines()[0] == "🗓 رزروهای من"
    no_oversize(lst, detail, mine)


async def test_events_headings_and_back() -> None:
    h = Harness(events_spec())
    ev = await seed_event(h, "کنسرت", "موسیقی", 24)
    lst = await h.tap("ali", "nav:go:evt")
    assert text(lst).splitlines()[0] == "📅 رویدادها"
    detail = await h.tap("ali", f"events:item:{ev}")
    assert text(detail).splitlines()[0] == "📅 رویدادها › کنسرت"
    assert "ظرفیت باقی‌مانده" in text(detail)
    assert [b.data for b in buttons(detail)][-2:] == ["nav:go:evt", "nav:go:home"]
    mine = await h.tap("ali", "nav:go:evt.mine")
    assert text(mine).splitlines()[0] == "🗓 ثبت‌نام‌های من"


async def test_request_headings_and_back() -> None:
    h = Harness(repair_spec())
    main = await h.tap("ali", "nav:go:sup")
    assert text(main).splitlines()[0] == "📝 درخواست تعمیر"
    assert labels(main) == ["درخواست جدید", "درخواست‌های من", "🏠 خانه"]
    mine = await h.tap("ali", "nav:go:sup.mine")
    assert text(mine).splitlines()[0] == "📝 درخواست تعمیر › درخواست‌های من"
    assert [b.data for b in buttons(mine)][-2:] == ["nav:go:sup", "nav:go:home"]


async def test_info_headings_and_back() -> None:
    h = Harness(build_catalog_spec(info_pages=2))
    lst = await h.tap("ali", "nav:go:info")
    assert text(lst).splitlines()[0] == "ℹ️ دربارهٔ ما"
    page = await h.tap("ali", "info:show:p2")
    assert text(page).splitlines()[0] == "ℹ️ دربارهٔ ما › صفحه 2"
    assert [b.data for b in buttons(page)] == ["nav:go:info", "nav:go:home"]
