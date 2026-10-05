"""Capability gating (enabled/audience), group context and the orders stub in the runtime."""

from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.runtime.contracts import Actor, RuntimeEvent, RuntimeResponse, audience_allows
from app.runtime.memory_store import MemoryStore
from app.runtime.texts import common
from app.runtime.texts import orders as orders_texts
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from tests.unit.botspec.test_capability_flags import business_data
from tests.unit.runtime.harness import T0, Harness, buttons, load_example

ALI = Actor(id="ali", display_name="علی")
STAFF = Actor(id="sam", display_name="سام", role="staff")
MANAGER = Actor(id="mina", display_name="مینا", role="manager")
OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)


def with_cap(spec: BotSpec, key: str, **flags: Any) -> BotSpec:
    data = spec.model_dump(mode="json")
    next(c for c in data["capabilities"] if c["key"] == key).update(flags)
    return BotSpec.model_validate(data)


def menu_data(resp: RuntimeResponse) -> list[str]:
    return [b.data for b in buttons(resp)]


def is_stale(resp: RuntimeResponse) -> bool:
    return len(resp.messages) == 1 and resp.messages[0].text == common.STALE


# ---------------------------------------------------------------- roles


def test_audience_allows_table() -> None:
    assert OWNER.effective_role == "manager" and ALI.effective_role == "customer"
    assert Actor(id="o", display_name="o", is_owner=True, role="staff").effective_role == "manager"
    table = {
        "everyone": (True, True, True, True),
        "staff": (False, True, True, True),
        "managers": (False, False, True, True),
    }
    for audience, expected in table.items():
        got = tuple(audience_allows(audience, a) for a in (ALI, STAFF, MANAGER, OWNER))  # type: ignore[arg-type]
        assert got == expected, audience


# ---------------------------------------------------------------- enabled


async def test_disabled_capability_hidden_and_stale() -> None:
    spec = with_cap(load_example("workshop.botspec.json"), "info", enabled=False)
    h = Harness(spec)
    resp = await h.start("ali")
    assert "menu:open:about" not in menu_data(resp)
    assert "menu:open:workshops" in menu_data(resp)
    assert is_stale(await h.tap("ali", "menu:open:about"))
    assert is_stale(await h.tap("ali", "info:show:about"))
    assert "menu:open:about" not in menu_data(h.last)  # type: ignore[arg-type]
    # Even the owner cannot use a disabled capability from Telegram.
    assert is_stale(await h.tap("owner", "info:show:about"))


async def test_disabled_capability_drops_session_on_text() -> None:
    repair = load_example("repair.botspec.json")
    h = Harness(repair)
    await h.tap("ali", "menu:open:new_request")
    await h.tap("ali", "repair:new:")
    assert await h.store.get_session("ali") is not None
    h.spec = with_cap(repair, "repair", enabled=False)
    resp = await h.send("ali", "متن")
    assert is_stale(resp)
    assert await h.store.get_session("ali") is None


async def test_admin_bypasses_disabled_capability() -> None:
    workshop = load_example("workshop.botspec.json")
    h = Harness(workshop)
    item = await h.seed(
        "workshop",
        {"title": "عکاسی", "description": "x", "teacher": "y", "starts_at": "2026-10-10T10:00:00+00:00"},
    )
    await h.tap("ali", f"book_workshop:book:{item}")
    booking_id = h.last.outcomes[0].record_id  # type: ignore[union-attr]
    assert booking_id is not None
    h.spec = with_cap(workshop, "book_workshop", enabled=False)
    assert is_stale(await h.tap("ali", f"book_workshop:cancel:{booking_id}"))
    resp = await h.admin(f"book_workshop:cancel:{booking_id}")
    assert [(o.action, o.result) for o in resp.outcomes] == [("cancel", "cancelled")]


# ---------------------------------------------------------------- audience


@pytest.mark.parametrize(
    ("audience", "allowed"),
    [
        ("staff", {"sam", "mina", "owner"}),
        ("managers", {"mina", "owner"}),
    ],
)
async def test_restricted_capability(audience: str, allowed: set[str]) -> None:
    spec = with_cap(load_example("workshop.botspec.json"), "info", audience=audience)
    h = Harness(spec)
    for actor in (ALI, STAFF, MANAGER, OWNER):
        visible = "menu:open:about" in menu_data(await h.start(actor))
        opened = await h.tap(actor, "menu:open:about")
        shown = await h.tap(actor, "info:show:about")
        if actor.id in allowed:
            assert visible, actor.id
            assert not is_stale(opened) and not is_stale(shown), actor.id
            assert "دربارهٔ آموزشگاه" in shown.messages[0].text
        else:
            assert not visible, actor.id
            assert is_stale(opened) and is_stale(shown), actor.id


# ---------------------------------------------------------------- group context


async def group_event(
    h: Harness, kind: str, data: str | None = None, text: str | None = None
) -> RuntimeResponse:
    ev = RuntimeEvent(
        bot_id="b1", env="sandbox", actor=ALI, kind=kind, data=data, text=text, now=T0, chat_type="group"
    )  # type: ignore[arg-type]
    return await h.runtime.handle(ev, h.spec, h.store)


async def test_group_context_noops() -> None:
    h = Harness(load_example("workshop.botspec.json"))
    assert (await group_event(h, "start")).messages == []
    assert (await group_event(h, "text", text="سلام")).messages == []
    assert (await group_event(h, "callback", data="menu:home:")).messages == []
    assert (await group_event(h, "callback", data="menu:open:about")).messages == []
    assert (await group_event(h, "callback", data="garbage")).messages == []
    assert "ali" not in h.store.users
    routed = await group_event(h, "callback", data="info:show:about")
    assert "دربارهٔ آموزشگاه" in routed.messages[0].text


# ---------------------------------------------------------------- orders stub + events preset


async def test_orders_stub_and_events_preset_run() -> None:
    spec = BotSpec.model_validate(business_data())
    h = Harness(spec, MemoryStore())
    start = await h.start("ali")
    assert "menu:open:shop_menu" in menu_data(start)
    # The real orders engine (W1-ORD) answers every entry point; nothing exists yet, so it writes nothing.
    shop = await h.tap("ali", "menu:open:shop_menu")
    assert shop.messages[0].text == orders_texts.TEXTS["empty"].replace("{title}", "فروشگاه")
    assert (await h.tap("ali", "menu:open:my_orders")).messages[0].text == orders_texts.TEXTS["mine_empty"]
    for resp in (
        await h.tap("ali", "shop:add:1"),
        await h.tap("ali", "shop:chk:"),
        await h.admin("shop:own:1.send"),
    ):
        assert [o.result for o in resp.outcomes] == ["rejected"]
        assert resp.effects == []
    events = await h.tap("ali", "menu:open:events_menu")
    assert events.messages and not is_stale(events)
    assert is_stale(await h.tap("ali", "info:add:1"))  # orders-only action on another type


# ---------------------------------------------------------------- derived scenarios


async def test_derive_skips_disabled_and_drives_restricted_as_owner() -> None:
    workshop = load_example("workshop.botspec.json")
    disabled = derive_scenarios(with_cap(workshop, "book_workshop", enabled=False))
    assert disabled and all(sc.capability_keys == ["info"] for sc in disabled)
    restricted = with_cap(workshop, "book_workshop", audience="staff")
    scenarios = derive_scenarios(restricted)
    booking = [sc for sc in scenarios if sc.capability_keys == ["book_workshop"]]
    assert booking, "single-persona templates survive"
    assert len(booking) < len(derive_scenarios(workshop)) - 1, "multi-persona templates are dropped"
    for sc in booking:
        actors = {st.actor for st in sc.steps if st.actor} | {
            st.target_actor for st in sc.steps if st.target_actor
        }
        assert actors == {"owner"}, sc.id
    report = await run_scenarios(restricted, scenarios)
    assert report.failed == 0, [r for r in report.results if not r.passed]
    repair = with_cap(load_example("repair.botspec.json"), "repair", audience="managers")
    repair_scenarios = derive_scenarios(repair)
    assert any(sc.capability_keys == ["repair"] for sc in repair_scenarios)
    report = await run_scenarios(repair, repair_scenarios)
    assert report.failed == 0, [r for r in report.results if not r.passed]
