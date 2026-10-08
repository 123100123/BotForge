"""Deterministic Telegram navigation (runtime/nav.py, U4): compiled role homes, stable routes,
forgiving stale handling, sessions, payload limits, the extension points later units use."""

import copy
from dataclasses import replace
from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.validate import validate_spec
from app.runtime import nav
from app.runtime.callbacks import (
    ACTIONS_BY_TYPE,
    MAX_CALLBACK_BYTES,
    NAV,
    CallbackError,
    make_callback,
    parse_callback,
)
from app.runtime.contracts import Actor, RuntimeEvent, RuntimeResponse
from app.runtime.ctx import Ctx
from app.runtime.memory_store import MemoryStore
from app.runtime.texts import nav as tx
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from tests.unit.botspec.test_capability_flags import business_data
from tests.unit.runtime.harness import T0, Harness, button_data, load_example, text
from tests.unit.runtime.test_orders import CAP as SHOP
from tests.unit.runtime.test_orders import setup as shop_setup

ALI = Actor(id="ali", display_name="علی")
SARA = Actor(id="sara", display_name="سارا")
STAFF = Actor(id="sam", display_name="سام", role="staff")
OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)


def labels(resp: RuntimeResponse) -> list[str]:
    return [b.label for row in resp.messages[-1].buttons for b in row]


def spec_of(data: dict[str, Any]) -> BotSpec:
    spec = BotSpec.model_validate(data)
    assert not [i for i in validate_spec(spec) if i.severity == "error"]
    return spec


def keys(entries: list[nav.Entry]) -> list[str]:
    return [e.key for e in entries]


# --- the contract ----------------------------------------------------------------------------------


def test_nav_is_one_additive_action() -> None:
    assert ACTIONS_BY_TYPE[NAV] == {"go"}
    assert make_callback(NAV, "go", "shop.i~2.15") == "nav:go:shop.i~2.15"
    assert parse_callback("nav:go:evt.mine") == ("nav", "go", "evt.mine")
    for bad in ("فروشگاه", "Shop", "a b", "x:y", ""):
        with pytest.raises(CallbackError):
            make_callback(NAV, "go", bad)


def test_route_payloads_and_parsing() -> None:
    assert nav.route_payload("shop.i", 2, 15) == "shop.i~2.15"
    assert nav.route_payload("evt.mine") == "evt.mine"
    route, ordinal, args = nav.parse_route("shop.i~2.15") or (None, 0, ())
    assert route is not None and (route.id, ordinal, args) == ("shop.i", 2, ("15",))
    route, ordinal, args = nav.parse_route("mgr.evt.new") or (None, 0, ())
    assert route is not None and (route.id, args) == ("mgr.evt.new", ())  # the longest id wins
    route, ordinal, args = nav.parse_route("mgr.evt.42") or (None, 0, ())
    assert route is not None and (route.id, args) == ("mgr.evt", ("42",))
    for bad in ("", "nope", "home~2", "shop~0", "shop~x", "shop.i.1.2", "info..x", "bkg~1234"):
        assert nav.parse_route(bad) is None, bad
    with pytest.raises(CallbackError):
        nav.route_payload("shop.i", 999, "9" * 60)


def test_every_generated_nav_payload_fits_telegram() -> None:
    """Homes of a spec with the longest keys and several capabilities of every type, for every
    role, plus the deepest routes with record ids at the int64 limit."""
    data = business_data()
    long_info = {
        "type": "info",
        "key": "i" * 24,
        "title": "دربارهٔ ما",
        "pages": [{"key": "p" * 24, "title": "t", "body": "b"}],
    }
    data["capabilities"] += [copy.deepcopy(long_info) | {"key": f"{'i' * 22}_{n}"} for n in range(9)]
    spec = spec_of(data)
    generated = [e.data for role in ("customer", "staff", "manager") for e in nav.compile_home(spec, role)]  # type: ignore[arg-type]
    generated += [e.data for e in nav.virtual_menu(spec)]
    generated += [nav.nav_data(nav.route_payload(r, 999, str(2**63 - 1))) for r in ("shop.i", "mgr.evt")]
    generated += [nav.nav_data(nav.route_payload("info", 99, "p" * 24))]
    generated += [nav.nav_data(f"mgr.rep.{'r' * 24}")]
    assert generated and all(len(d.encode()) <= MAX_CALLBACK_BYTES for d in generated)
    assert all(d.isascii() for d in generated)


# --- homes -----------------------------------------------------------------------------------------


def test_customer_home_has_a_fixed_canonical_order_and_central_labels() -> None:
    spec = spec_of(business_data())
    home = nav.compile_user_home(spec, "customer")
    assert keys(home) == ["shop", "ord", "evt", "evt.mine", "info"]
    assert [e.label for e in home] == [
        "🛍 فروشگاه",
        "📦 سفارش‌های من",
        "📅 رویدادها",
        "🗓 ثبت‌نام‌های من",
        "ℹ️ دربارهٔ ما",
    ]


def test_one_shop_when_catalog_and_orders_sell_the_same_resource() -> None:
    data = business_data()
    catalog = {
        "type": "catalog",
        "key": "products",
        "title": "محصولات",
        "resource": "product",
        "detail_fields": ["price"],
    }
    data["capabilities"].append(catalog)
    spec = spec_of(data)
    home = nav.compile_user_home(spec, "customer")
    assert [e.label for e in home].count("🛍 فروشگاه") == 1
    assert "products" not in [e.capability for e in home]
    # the orders capability off: the catalog is the shop again (browse only, by its plural label)
    off = copy.deepcopy(data)
    next(c for c in off["capabilities"] if c["key"] == "shop")["enabled"] = False
    home = nav.compile_user_home(spec_of(off), "customer")
    first = home[0]
    assert (first.key, first.label, first.capability) == ("shop~2", "🗂 کالاها", "products")


def test_manager_home_lists_manage_sections_reports_and_customer_view() -> None:
    repair = load_example("repair.botspec.json")
    entries = nav.compile_home(repair, "manager")
    assert keys(entries) == ["mgr.req", "mgr.rep", "cust"]
    assert entries[-1].label == tx.CUSTOMER_VIEW
    spec = spec_of(business_data())
    assert keys(nav.compile_home(spec, "manager")) == ["mgr.evt", "mgr.rep", "cust"]  # mgr.ord: U6


def test_disabling_a_capability_changes_only_the_homes_it_appears_in() -> None:
    repair = load_example("repair.botspec.json")
    data = repair.model_dump(mode="json")
    next(c for c in data["capabilities"] if c["key"] == "info")["enabled"] = False
    no_info = BotSpec.model_validate(data)
    assert keys(nav.compile_home(no_info, "customer")) == ["sup"]
    assert keys(nav.compile_home(no_info, "manager")) == keys(nav.compile_home(repair, "manager"))
    next(c for c in data["capabilities"] if c["key"] == "info")["enabled"] = True
    next(c for c in data["capabilities"] if c["key"] == "repair")["enabled"] = False
    no_requests = BotSpec.model_validate(data)
    assert keys(nav.compile_home(no_requests, "customer")) == ["info"]
    assert keys(nav.compile_home(no_requests, "staff")) == ["info"]  # no staff queue either
    assert keys(nav.compile_home(no_requests, "manager")) == ["cust"]  # info has no metrics


def test_restricted_capabilities_appear_for_the_roles_that_may_use_them() -> None:
    data = load_example("workshop.botspec.json").model_dump(mode="json")
    next(c for c in data["capabilities"] if c["key"] == "info")["audience"] = "managers"
    spec = BotSpec.model_validate(data)
    assert "info" not in keys(nav.compile_user_home(spec, "customer"))
    assert "info" not in keys(nav.compile_user_home(spec, "staff"))
    assert "info" in keys(nav.compile_user_home(spec, "manager"))  # the manager's customer view


def test_several_capabilities_of_one_type_get_ordinals_that_ignore_enabled() -> None:
    data = load_example("workshop.botspec.json").model_dump(mode="json")
    second = {
        "type": "info",
        "key": "rules",
        "title": "قوانین",
        "pages": [{"key": "a", "title": "a", "body": "b"}],
    }
    data["capabilities"].append(second)
    spec = BotSpec.model_validate(data)
    assert [
        (e.key, e.label) for e in nav.compile_user_home(spec, "customer") if e.capability in ("info", "rules")
    ] == [
        ("info", "ℹ️ دربارهٔ ما"),
        ("info~2", "ℹ️ قوانین"),
    ]
    next(c for c in data["capabilities"] if c["key"] == "info")["enabled"] = False
    spec = BotSpec.model_validate(data)
    assert "info~2" in keys(nav.compile_user_home(spec, "customer"))  # not renumbered


def test_virtual_menu_offers_every_entry_point_without_spec_menu() -> None:
    repair = load_example("repair.botspec.json")
    unmenued = repair.model_copy(update={"menu": []})
    assert [(e.key, e.capability, e.view, e.on_home) for e in nav.virtual_menu(unmenued)] == [
        ("sup", "repair", "main", True),
        ("info", "info", "main", True),
        ("sup.mine", "repair", "mine", False),
    ]


@pytest.mark.parametrize("name", ["workshop", "repair"])
async def test_golden_examples_validate_and_derive_with_or_without_a_menu(name: str) -> None:
    spec = load_example(f"{name}.botspec.json")
    for variant in (spec, spec.model_copy(update={"menu": []})):
        assert [i for i in validate_spec(variant) if i.severity == "error"] == []
        scenarios = derive_scenarios(variant)
        assert scenarios
        report = await run_scenarios(variant, scenarios)
        assert report.failed == 0, [r.scenario_id for r in report.results if not r.passed]


# --- runtime ---------------------------------------------------------------------------------------


async def test_nav_go_home_and_legacy_buttons_render_the_role_home() -> None:
    h = Harness(load_example("workshop.botspec.json"))
    for data in ("nav:go:home", "menu:home:", "menu:open:bkg"):  # a route id through the legacy prefix
        r = await h.tap(ALI, data)
        if data == "menu:open:bkg":
            assert "کارگاه" in text(r) and "book_workshop:mine:" in button_data(r)  # the booking list
            continue
        assert button_data(r) == ["nav:go:bkg", "nav:go:bkg.mine", "nav:go:info"]
        assert r.messages[0].edit is True
    r = await h.tap(OWNER, "nav:go:home")
    assert text(r).startswith("🧭 مدیریت ") and button_data(r)[-1] == "nav:go:cust"


async def test_owner_and_customer_homes_and_sessions_are_independent() -> None:
    repair = load_example("repair.botspec.json")
    h = Harness(repair)
    owner_home = await h.start(OWNER)
    assert text(owner_home).startswith("🧭 مدیریت ") and tx.CUSTOMER_VIEW in labels(owner_home)
    customer_home = await h.start(ALI)
    assert text(customer_home) == repair.bot.welcome_text and "nav:go:cust" not in button_data(customer_home)

    await h.tap(ALI, "repair:new:")  # ali starts a request form
    await h.tap(OWNER, "nav:go:cust")
    await h.tap(OWNER, "repair:new:")  # so does the owner, from the customer view
    ali_form, owner_form = await h.store.get_session("ali"), await h.store.get_session("owner")
    assert ali_form is not None and owner_form is not None
    await h.tap(OWNER, "nav:go:mgr")  # the owner navigates away: only their form is abandoned
    assert await h.store.get_session("owner") is None
    assert await h.store.get_session("ali") == ali_form

    cust = await h.tap(OWNER, "nav:go:cust")
    assert text(cust).startswith(tx.CUSTOMER_VIEW_NOTE)
    assert button_data(cust)[-1] == "nav:go:mgr"  # back to the manager home


async def test_two_users_keep_independent_carts_and_forms() -> None:
    h, a, b = await shop_setup()
    await h.tap(ALI, f"{SHOP}:add:{a}")
    await h.tap(SARA, f"{SHOP}:add:{b}")
    await h.tap(SARA, f"{SHOP}:add:{b}")
    await h.tap(ALI, f"{SHOP}:chk:")  # ali is now in the checkout form
    await h.tap(SARA, "nav:go:cart")
    sara_cart = await h.store.list_records(f"{SHOP}.cart", actor_id="sara")
    ali_cart = await h.store.list_records(f"{SHOP}.cart", actor_id="ali")
    assert [x["item_id"] for x in ali_cart[0].data["items"]] == [a]
    assert sara_cart[0].data["items"] == [{"item_id": b, "qty": 2}]
    assert (await h.store.get_session("ali") or {}).get("capability") == SHOP
    assert await h.store.get_session("sara") is None


async def test_a_group_press_keeps_the_private_form() -> None:
    """Fixed (was a known gap): a group button (the RSVP card) no longer clears the presser's
    private-chat session, so a form in progress there survives."""
    spec = BotSpec.model_validate(business_data())
    h = Harness(spec)
    form = {"capability": "shop", "step": "form", "vars": {"field": "address", "answers": {}, "data": {}}}
    await h.store.set_session("ali", form)
    event = RuntimeEvent(
        bot_id="b1",
        env="sandbox",
        actor=ALI,
        kind="callback",
        data="events:book:1",
        now=T0,
        chat_type="group",
    )
    resp = await h.runtime.handle(event, spec, h.store)
    assert resp.outcomes and resp.outcomes[0].action == "book"  # the RSVP itself still runs
    assert await h.store.get_session("ali") == form
    stale_group = event.model_copy(update={"data": "ghost:book:1"})  # stale in a group: a no-op
    assert (await h.runtime.handle(stale_group, spec, h.store)).messages == []
    assert await h.store.get_session("ali") == form


async def test_stale_navigation_is_a_new_message_with_the_home() -> None:
    h = Harness(load_example("workshop.botspec.json"))
    for data in ("menu:open:gone_key", "nav:go:unknown", "nav:go:mgr.rep", "nav:go:staff.q"):
        r = await h.tap(ALI, data)
        assert [m.edit for m in r.messages] == [False], data
        assert text(r).startswith(tx.STALE + "\n\n")
        assert button_data(r) == ["nav:go:bkg", "nav:go:bkg.mine", "nav:go:info"]
    r = await h.tap(ALI, "book_workshop:item:999")  # a stale record: notice + one button
    assert [(m.text, m.edit) for m in r.messages] == [(tx.STALE, False)]
    assert button_data(r) == ["nav:go:home"]


async def test_placeholder_routes_answer_with_a_notice_and_the_manager_home() -> None:
    h = Harness(BotSpec.model_validate(business_data()))
    for data in ("nav:go:mgr.ord", "nav:go:mgr.team"):
        r = await h.tap(OWNER, data)
        assert text(r).startswith(tx.COMING_SOON), data
        assert "nav:go:cust" in button_data(r)
    r = await h.tap(OWNER, "nav:go:mgr.evt")  # U7: the manager's events list (runtime/manager_events.py)
    assert button_data(r)[0] == "nav:go:mgr.evt.new"


# --- extension points ------------------------------------------------------------------------------


async def test_register_route_replaces_a_placeholder() -> None:
    original = nav.ROUTES["mgr.team"]
    seen: list[str] = []

    async def team(ctx: Ctx, target: nav.Target) -> None:
        seen.append(target.payload)
        ctx.reply(ctx.heading("mgr.team"), [[ctx.back_button("mgr.team"), ctx.home_button()]])

    try:
        nav.register_route(replace(original, resolve=team, ready=True))
        spec = BotSpec.model_validate(business_data())
        assert "mgr.team" in keys(nav.compile_home(spec, "manager"))
        r = await Harness(spec).tap(OWNER, "nav:go:mgr.team")
        assert seen == ["mgr.team"]
        assert text(r) == tx.TEAM and button_data(r) == ["nav:go:mgr", "nav:go:home"]
    finally:
        nav.register_route(original)


async def test_attention_providers_feed_the_manager_home() -> None:
    async def pending(ctx: Ctx) -> list[nav.AttentionItem]:
        return [nav.AttentionItem("۳ سفارش جدید", nav.nav_button("سفارش‌های جدید", "mgr.ord"))]

    nav.register_attention(pending)
    try:
        r = await Harness(BotSpec.model_validate(business_data())).start(OWNER)
        assert f"{tx.ATTENTION_HEADING}\n• ۳ سفارش جدید" in text(r)
        assert button_data(r)[0] == "nav:go:mgr.ord"
    finally:
        nav.ATTENTION.remove(pending)


async def test_heading_and_back_follow_the_route_tree() -> None:
    spec = BotSpec.model_validate(business_data())
    ev = RuntimeEvent(bot_id="b", env="sandbox", actor=ALI, kind="callback", data="x:y:z", now=T0)
    ctx = await Ctx.create(ev, spec, MemoryStore())
    assert ctx.heading("shop", "نوشیدنی‌ها") == "🛍 فروشگاه › نوشیدنی‌ها"
    assert ctx.heading("shop.i", "قهوه") == "🛍 فروشگاه › قهوه"
    assert ctx.heading("cart") == "🛍 فروشگاه › 🛒 سبد خرید"
    assert ctx.heading("evt.mine") == "🗓 ثبت‌نام‌های من"
    assert ctx.heading("mgr.evt.new") == "📅 مدیریت رویدادها › ➕ رویداد جدید"
    assert nav.back_route(ctx, "shop.i.15") == "shop"
    assert nav.back_route(ctx, "cart") == "shop"
    assert nav.back_route(ctx, "evt") == "home"
    assert ctx.back_button("sup.mine").data == "nav:go:sup"
    owner_ctx = await Ctx.create(ev.model_copy(update={"actor": OWNER}), spec, MemoryStore())
    assert nav.back_route(owner_ctx, "evt") == "cust"  # a manager's user screens go back to the customer view
    assert nav.back_route(owner_ctx, "mgr.evt") == "mgr"
    assert ctx.menu_button_for("events", "mine") is not None
    assert ctx.menu_button_for("events", "mine").data == "nav:go:evt.mine"  # type: ignore[union-attr]
