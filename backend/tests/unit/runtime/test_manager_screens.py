"""Telegram manager screens (U6): the manager home's summary and attention lines, the order queue
(``mgr.ord``), the request queue's manager frame (``mgr.req``) and the team screen (``mgr.team``)."""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from app.botspec.models import BotSpec
from app.botspec.validate import validate_spec
from app.runtime import manager_orders, nav
from app.runtime.callbacks import MAX_CALLBACK_BYTES
from app.runtime.contracts import Actor, RuntimeResponse
from app.runtime.memory_store import MemoryStore
from app.runtime.texts import manager as tx
from app.runtime.texts import nav as nav_texts
from app.schemas.business import TeamMemberOut, TeamOut
from tests.unit.botspec.test_capability_flags import business_data
from tests.unit.runtime.harness import T0, Harness, button_data, buttons, find_button, text

OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)
MANAGER = Actor(id="mina", display_name="مینا", role="manager")
STAFF = Actor(id="sam", display_name="سام", role="staff")
ALI = Actor(id="ali", display_name="علی")
REZA = Actor(id="reza", display_name="رضا")

SUPPORT = {
    "type": "request",
    "key": "support",
    "title": "پشتیبانی",
    "form_fields": [{"key": "msg", "label": "پیام", "type": "text"}],
    "statuses": [{"key": "new", "label": "باز"}, {"key": "closed", "label": "بسته"}],
    "initial_status": "new",
    "owner_actions": [{"key": "close", "label": "بستن", "from_statuses": ["new"], "to_status": "closed"}],
}


def spec_data() -> dict[str, Any]:
    data = business_data()  # orders "shop" (new -> sent -> done), events "events" (capacity 20), info
    data["capabilities"].append(copy.deepcopy(SUPPORT))
    return data


def make_spec(data: dict[str, Any] | None = None) -> BotSpec:
    spec = BotSpec.model_validate(data or spec_data())
    assert not [i for i in validate_spec(spec) if i.severity == "error"]
    return spec


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


async def order(h: Harness, actor: str, status: str = "new", total: int = 240000) -> int:
    items = [{"item_id": 1, "title": "قهوه", "qty": 2, "unit_price": total // 2}]
    data = {"address": "تهران، خیابان آزادی", "phone": "09121234567", "items": items, "total": total}
    return await h.seed("shop", {**data, "payment_status": "unpaid"}, status=status, actor_id=actor)


async def seeded(store: MemoryStore | None = None) -> tuple[Harness, dict[str, int]]:
    """3 new orders and 1 delivered, 2 open requests, an event in 5 h (2 going) and one in 30 h."""
    h = Harness(make_spec(), store=store)
    for actor in (ALI, REZA):
        await h.start(actor)  # the users become known (display names)
    ids = {
        "o1": await order(h, "ali"),
        "o2": await order(h, "reza", total=100000),
        "o3": await order(h, "ali"),
        "done": await order(h, "reza", status="done"),
    }
    for _ in range(2):
        await h.seed("support", {"msg": "سلام"}, status="new", actor_id="ali")
    soon = await h.seed("event", {"title": "کارگاه قهوه", "starts_at": iso(T0 + timedelta(hours=5))})
    await h.seed("event", {"title": "همایش", "starts_at": iso(T0 + timedelta(hours=30))})
    for actor in ("ali", "reza"):
        await h.seed("events", {}, status="confirmed", actor_id=actor, item_id=soon)
    ids["soon"] = soon
    return h, ids


def is_stale_home(resp: RuntimeResponse) -> bool:
    msgs = resp.messages
    return len(msgs) == 1 and msgs[0].edit is False and msgs[0].text.startswith(nav_texts.STALE)


def all_data(resp: RuntimeResponse) -> list[str]:
    return [b.data for m in resp.messages for row in m.buttons for b in row]


# --- manager home ----------------------------------------------------------------------------------


async def test_owner_start_lands_on_the_manager_home_with_summary_and_attention() -> None:
    h, _ = await seeded()
    r = await h.start(OWNER)
    body = text(r)
    lines = body.splitlines()
    assert lines[0] == "🧭 مدیریت کافه نمونه"
    assert lines[1] == "امروز: ۴ سفارش · ۲ ثبت‌نام · ۲ درخواست"
    assert nav_texts.ATTENTION_HEADING in body
    assert "• ۳ سفارش «جدید» منتظر رسیدگی" in body
    assert "• ۲ درخواست باز در «پشتیبانی»" in body
    assert "رویداد «کارگاه قهوه»" in body and "۲/۲۰ نفر" in body
    assert "همایش" not in body  # starts in 30 h: outside the window
    assert tx.NOTHING_WAITING not in body
    assert button_data(r) == [
        "nav:go:mgr.ord.l.new",  # attention: the filtered lists
        "nav:go:mgr.req",
        "nav:go:mgr.evt",
        "nav:go:mgr.ord",  # the Manage entries
        "nav:go:mgr.evt",
        "nav:go:mgr.req",
        "nav:go:mgr.rep",
        "nav:go:mgr.team",
        "nav:go:cust",
    ]
    assert find_button(r, "سفارش‌های جدید").label == "📦 سفارش‌های جدید (۳)"
    assert len(r.messages[-1].buttons) <= 7 + 3
    for actor in (MANAGER,):
        assert button_data(await h.start(actor)) == button_data(r)


async def test_nothing_waiting_and_quiet_day() -> None:
    h = Harness(make_spec())
    r = await h.start(OWNER)
    lines = text(r).splitlines()
    assert lines[1:3] == [tx.TODAY_NOTHING, tx.NOTHING_WAITING]
    assert nav_texts.ATTENTION_HEADING not in text(r)
    assert button_data(r)[0] == "nav:go:mgr.ord"


async def test_manager_home_hides_disabled_capabilities() -> None:
    data = spec_data()
    for cap in data["capabilities"]:
        if cap["key"] in ("shop", "support"):
            cap["enabled"] = False
    h = Harness(make_spec(data))
    await order(h, "ali")
    await h.seed("support", {"msg": "x"}, status="new", actor_id="ali")
    r = await h.start(OWNER)
    data_ = button_data(r)
    assert not [d for d in data_ if d.startswith(("nav:go:mgr.ord", "nav:go:mgr.req"))]
    assert "سفارش" not in text(r) and "درخواست" not in text(r)
    assert data_ == ["nav:go:mgr.evt", "nav:go:mgr.rep", "nav:go:mgr.team", "nav:go:cust"]
    for gone in ("nav:go:mgr.ord", "nav:go:mgr.req"):  # an old button for a disabled capability
        assert is_stale_home(await h.tap(OWNER, gone))


# --- orders ----------------------------------------------------------------------------------------


async def test_attention_line_opens_the_filtered_list() -> None:
    h, ids = await seeded()
    home = await h.start(OWNER)
    r = await h.tap(OWNER, find_button(home, "سفارش‌های جدید").data)
    lines = text(r).splitlines()
    assert lines[0] == "🧭 مدیریت › 📦 سفارش‌ها"
    assert lines[1] == "نمایش: جدید · ۳ سفارش"
    assert lines[2:] == [  # newest first
        f"#{ids['o3']} · علی · ۲۴۰٬۰۰۰ تومان".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
        f"#{ids['o2']} · رضا · ۱۰۰٬۰۰۰ تومان".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
        f"#{ids['o1']} · علی · ۲۴۰٬۰۰۰ تومان".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")),
    ]
    labels = [b.label for b in buttons(r)]
    assert labels[:4] == ["همه (۴)", "• جدید (۳)", "ارسال‌شده (۰)", "تحویل‌شده (۱)"]
    assert button_data(r)[4:] == [
        f"nav:go:mgr.ord.o.{ids['o3']}.new",
        f"nav:go:mgr.ord.o.{ids['o2']}.new",
        f"nav:go:mgr.ord.o.{ids['o1']}.new",
        "nav:go:mgr",
    ]
    assert r.messages[0].edit is True


async def test_list_filters_and_pages() -> None:
    h, ids = await seeded()
    for _ in range(9):
        await order(h, "ali")
    r = await h.tap(OWNER, "nav:go:mgr.ord")
    assert "نمایش: همه · ۱۳ سفارش" in text(r)
    assert "صفحهٔ ۱ از ۲" in text(r)
    assert " · جدید" in text(r)  # every status: each line names its status
    assert len([d for d in button_data(r) if ".o." in d]) == 8
    nxt = find_button(r, "بعدی").data
    assert nxt == "nav:go:mgr.ord.l._.1"
    page2 = await h.tap(OWNER, nxt)
    assert "صفحهٔ ۲ از ۲" in text(page2)
    assert len([d for d in button_data(page2) if ".o." in d]) == 5
    assert find_button(page2, "قبلی").data == "nav:go:mgr.ord"
    done = await h.tap(OWNER, "nav:go:mgr.ord.l.done")
    assert "نمایش: تحویل‌شده · ۱ سفارش" in text(done)
    assert f"nav:go:mgr.ord.o.{ids['done']}.done" in button_data(done)
    gone_status = await h.tap(OWNER, "nav:go:mgr.ord.l.nope")  # a status the spec no longer has
    assert "نمایش: همه · ۱۳ سفارش" in text(gone_status)


async def test_order_detail_shows_items_customer_answers_and_actions() -> None:
    h, ids = await seeded()
    r = await h.tap(OWNER, f"nav:go:mgr.ord.o.{ids['o2']}.new")
    body = text(r)
    n = str(ids["o2"]).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert body.splitlines()[0] == f"🧭 مدیریت › 📦 سفارش‌ها › سفارش #{n}"
    for line in (
        "مشتری: رضا",
        "وضعیت: جدید",
        "• قهوه × ۲ — ۱۰۰٬۰۰۰ تومان",
        "جمع کل: ۱۰۰٬۰۰۰ تومان",
        "نشانی: تهران، خیابان آزادی",
        "تلفن: 09121234567",
    ):
        assert line in body, line
    assert button_data(r) == [f"nav:go:mgr.ord.a.{ids['o2']}.send", "nav:go:mgr.ord.l.new", "nav:go:mgr"]
    assert [b.label for b in buttons(r)] == ["ارسال", tx.BACK_TO_ORDERS, tx.MANAGER]
    delivered = await h.tap(OWNER, f"nav:go:mgr.ord.o.{ids['done']}")
    assert tx.ORDER_NO_ACTIONS in text(delivered)
    assert button_data(delivered) == ["nav:go:mgr.ord", "nav:go:mgr"]


async def test_confirming_from_the_manager_screen_matches_the_owner_button() -> None:
    """The same owner action through the manager screen and through the engine's ``own`` button:
    identical status change, effects, outcome and customer notice; only the owner's screen differs."""
    h, ids = await seeded()
    twin, twin_ids = await seeded()
    assert ids == twin_ids
    r = await h.tap(OWNER, f"nav:go:mgr.ord.a.{ids['o2']}.send")
    legacy = await twin.tap(OWNER, f"shop:own:{ids['o2']}.send")

    assert (await h.store.get_record("shop", ids["o2"])).status == "sent"  # type: ignore[union-attr]
    assert r.effects == legacy.effects and r.outcomes == legacy.outcomes
    assert r.outcomes[-1].result == "ok"
    notices = [m for m in r.messages if m.notice]
    assert notices == [m for m in legacy.messages if m.notice]
    assert [(m.to_actor_id, m.notice) for m in notices] == [("reza", "order_status_changed")]

    mine = [m for m in r.messages if m.to_actor_id == "owner"]
    assert len(mine) == 1 and mine[0].edit is True
    n = str(ids["o2"]).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert mine[0].text.startswith(f"✅ وضعیت سفارش {n} به «ارسال‌شده» تغییر کرد.\n\n🧭 مدیریت › ")
    assert "وضعیت: ارسال‌شده" in mine[0].text
    owner_buttons = [b.data for row in mine[0].buttons for b in row]
    assert owner_buttons == [f"nav:go:mgr.ord.a.{ids['o2']}.deliver", "nav:go:mgr.ord.l.new", "nav:go:mgr"]


async def test_stale_action_gets_the_specific_message_as_a_new_message() -> None:
    h, ids = await seeded()
    before = h.store.all_records()
    r = await h.tap(OWNER, f"nav:go:mgr.ord.a.{ids['done']}.send")  # delivered: send no longer applies
    assert [(m.text, m.edit) for m in r.messages] == [(tx.ACTION_STALE, False)]
    assert button_data(r) == [f"nav:go:mgr.ord.o.{ids['done']}", "nav:go:mgr.ord.l.done", "nav:go:mgr"]
    assert buttons(r)[0].label == tx.VIEW_ORDER
    assert r.outcomes[-1].result == "rejected" and r.outcomes[-1].reason == "not_allowed"
    assert h.store.all_records() == before

    first = await h.tap(OWNER, f"nav:go:mgr.ord.a.{ids['o1']}.send")
    assert first.outcomes[-1].result == "ok"
    again = await h.tap(OWNER, f"nav:go:mgr.ord.a.{ids['o1']}.send")  # pressed twice
    assert [(m.text, m.edit) for m in again.messages] == [(tx.ACTION_STALE, False)]
    assert not [m for m in again.messages if m.notice]

    missing = await h.tap(OWNER, "nav:go:mgr.ord.a.99999.send")
    assert [(m.text, m.edit) for m in missing.messages] == [(tx.ORDER_GONE, False)]
    assert tx.VIEW_ORDER not in [b.label for b in buttons(missing)]


async def test_customers_and_staff_never_reach_the_manager_screens() -> None:
    h, ids = await seeded()
    before = h.store.all_records()
    for actor in (ALI, STAFF):
        for data in (
            "nav:go:mgr.ord",
            "nav:go:mgr.ord.l.new",
            f"nav:go:mgr.ord.o.{ids['o1']}",
            f"nav:go:mgr.ord.a.{ids['o1']}.send",
            "nav:go:mgr.team",
            "nav:go:mgr.req",
        ):
            r = await h.tap(actor, data)
            assert is_stale_home(r), (actor.id, data)
            assert not [d for d in button_data(r) if d.startswith("nav:go:mgr")]
    assert h.store.all_records() == before


async def test_malformed_order_routes_are_stale() -> None:
    h, _ = await seeded()
    for data in (
        "nav:go:mgr.ord.x",
        "nav:go:mgr.ord.o",
        "nav:go:mgr.ord.o.abc",
        "nav:go:mgr.ord.a.1",
        "nav:go:mgr.ord.l.new.x",
        "nav:go:mgr.ord~9",
    ):
        assert is_stale_home(await h.tap(OWNER, data)), data


# --- requests --------------------------------------------------------------------------------------


async def test_request_queue_has_the_manager_heading_and_home() -> None:
    h, _ = await seeded()
    home = await h.start(OWNER)
    r = await h.tap(OWNER, find_button(home, "درخواست‌های باز").data)
    assert text(r).startswith("🧭 مدیریت › 📝 درخواست‌ها\nپشتیبانی\n")
    data = button_data(r)
    assert data[-1] == "nav:go:mgr" and "nav:go:home" not in data
    assert sum(1 for d in data if d.startswith("support:own:")) == 2  # the engine's queue buttons
    action = next(d for d in data if d.startswith("support:own:"))
    done = await h.tap(OWNER, action)  # the engine's own path, unchanged
    assert done.outcomes[-1].result == "ok"


# --- team ------------------------------------------------------------------------------------------


class TeamStore(MemoryStore):
    async def team_overview(self) -> TeamOut:
        seen = datetime(2026, 1, 1, tzinfo=UTC)
        return TeamOut(
            staff_link="https://t.me/cafe_bot?start=staff_SECRET",
            staff_link_code="SECRET",
            members=[
                TeamMemberOut(actor_id="owner", display_name="مدیر", role="manager", first_seen=seen),
                TeamMemberOut(actor_id="mina", display_name="مینا", role="manager", first_seen=seen),
                TeamMemberOut(actor_id="sam", display_name="سام", role="staff", first_seen=seen),
            ],
            counts={"customer": 40, "staff": 1, "manager": 2},
        )


async def test_team_lists_counts_members_and_the_link_for_the_owner() -> None:
    h, _ = await seeded(TeamStore())
    r = await h.tap(OWNER, "nav:go:mgr.team")
    body = text(r)
    assert body.splitlines()[0] == "🧭 مدیریت › 👥 کارکنان"
    for line in (
        "مدیر: ۲ · همکار: ۱ · مشتری: ۴۰",
        "• مدیر — مدیر (مالک)",
        "• مینا — مدیر",
        "• سام — همکار",
        "https://t.me/cafe_bot?start=staff_SECRET",
        tx.TEAM_WEB_NOTE,
    ):
        assert line in body, line
    assert button_data(r) == ["nav:go:mgr"]
    other = await h.tap(MANAGER, "nav:go:mgr.team")  # managers see the team, not the secret link
    assert "SECRET" not in text(other) and tx.TEAM_LINK_OWNER_ONLY in text(other)
    plain, _ = await seeded()  # a store without the team extension
    assert tx.TEAM_UNAVAILABLE in text(await plain.tap(OWNER, "nav:go:mgr.team"))


# --- payloads --------------------------------------------------------------------------------------


async def test_every_manager_payload_fits_telegram() -> None:
    h, ids = await seeded(TeamStore())
    seen: list[str] = []
    for data in (
        None,
        "nav:go:mgr.ord",
        "nav:go:mgr.ord.l.new",
        f"nav:go:mgr.ord.o.{ids['o1']}.new",
        f"nav:go:mgr.ord.a.{ids['o1']}.send",
        "nav:go:mgr.req",
        "nav:go:mgr.team",
        "nav:go:mgr.rep",
    ):
        r = await (h.start(OWNER) if data is None else h.tap(OWNER, data))
        seen += all_data(r)
    assert seen and all(len(d.encode()) <= MAX_CALLBACK_BYTES for d in seen)

    # worst case: the longest keys, the largest ids and a high ordinal never overflow
    long_key = "k" * 24
    data = spec_data()
    shop = next(c for c in data["capabilities"] if c["key"] == "shop")
    shop["statuses"].append({"key": long_key, "label": "طولانی"})
    shop["owner_actions"].append(
        {"key": long_key, "label": "طولانی", "from_statuses": ["new"], "to_status": long_key}
    )
    spec = make_spec(data)
    cap = spec.capability("shop")
    assert cap is not None
    huge = 2**62
    for route in (
        manager_orders.order_payload(spec, cap, huge, long_key),
        manager_orders.list_payload(spec, cap, long_key, 999),
        manager_orders.payload(spec, cap, "a", huge, long_key),
    ):
        assert route is None or len(nav.nav_data(route).encode()) <= MAX_CALLBACK_BYTES
    assert manager_orders.order_payload(spec, cap, huge, long_key) is not None  # falls back: no filter
