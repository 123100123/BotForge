from typing import Any, ClassVar

import pytest

from app.botspec.models import BotSpec
from app.runtime import engines
from app.runtime.contracts import Actor
from app.runtime.ctx import Ctx
from app.runtime.engines import EngineUnavailable, get_engine, override_engine
from app.runtime.engines.base import EngineBase
from app.runtime.texts import common
from app.runtime.texts import nav as nav_texts
from tests.unit.runtime.harness import T0, Harness, button_data, text

# The customer home is compiled from the capabilities (runtime/nav.py), not from spec.menu.
WORKSHOP_MENU = ["nav:go:bkg", "nav:go:bkg.mine", "nav:go:info"]
WORKSHOP_LABELS = ["📅 کارگاه‌ها", "🗓 رزروهای من", "ℹ️ دربارهٔ ما"]


class RecordingEngine(EngineBase):
    """Fake engine that records every call."""

    type: ClassVar[str] = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def open(self, ctx: Ctx, cap: Any, view: str) -> None:
        self.calls.append(("open", cap.key, view))
        ctx.reply("opened")

    async def on_callback(self, ctx: Ctx, cap: Any, action: str, arg: str) -> None:
        self.calls.append(("callback", cap.key, action, arg))
        ctx.reply("cb")

    async def on_text(self, ctx: Ctx, cap: Any, text: str) -> None:
        self.calls.append(("text", cap.key, text))
        ctx.reply("got text")

    async def owner_action(self, ctx: Ctx, cap: Any, record_id: int, action: str) -> None:
        self.calls.append(("owner", cap.key, record_id, action))
        ctx.outcome(cap, "cancel" if action == "cancel" else "owner_action", "ok", record_id=record_id)


@pytest.fixture
def no_booking_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the booking engine module not existing (stays valid after WP2 lands)."""
    monkeypatch.setitem(engines.ENGINE_MODULES, "booking", "app.runtime.engines._not_written_yet")
    monkeypatch.setattr(engines, "_loaded", {k: v for k, v in engines._loaded.items() if k != "booking"})


async def test_start_shows_welcome_and_menu(workshop_h: Harness, workshop: BotSpec) -> None:
    await workshop_h.store.set_session("ali", {"capability": "book_workshop", "step": "form", "vars": {}})
    r = await workshop_h.start("ali")
    assert len(r.messages) == 1
    m = r.messages[0]
    assert m.to_actor_id == "ali" and m.text == workshop.bot.welcome_text and m.edit is False
    assert button_data(r) == WORKSHOP_MENU
    assert [b[0].label for b in m.buttons] == WORKSHOP_LABELS
    assert await workshop_h.store.get_session("ali") is None
    assert "ali" in workshop_h.store.users
    assert r.outcomes == [] and r.effects == []


async def test_text_without_session_shows_menu(workshop_h: Harness, workshop: BotSpec) -> None:
    r = await workshop_h.send("sara", "سلام")
    assert text(r) == workshop.bot.welcome_text
    assert button_data(r) == WORKSHOP_MENU
    assert "sara" in workshop_h.store.users


async def test_menu_home(workshop_h: Harness, workshop: BotSpec) -> None:
    for data in ("menu:home:", "nav:go:home"):  # legacy and nav: both the role home
        r = await workshop_h.tap("ali", data)
        assert text(r).startswith(f"🏠 {workshop.bot.name}\n")
        assert button_data(r) == WORKSHOP_MENU
        assert r.messages[0].edit is True


async def test_workshop_booking_menu_without_engine_is_controlled(
    workshop_h: Harness, no_booking_engine: None
) -> None:
    with pytest.raises(EngineUnavailable):
        get_engine("booking")
    for data in ("menu:open:workshops", "menu:open:my_bookings", "nav:go:bkg", "book_workshop:list:0"):
        r = await workshop_h.tap("ali", data)
        assert text(r) == common.NOT_AVAILABLE
        assert button_data(r) == WORKSHOP_MENU
    r = await workshop_h.admin("book_workshop:cancel:1")
    assert text(r) == common.NOT_AVAILABLE


@pytest.mark.parametrize(
    "data",
    [
        None,
        "",
        "garbage",
        "a:b",
        "nope:show:x",  # unknown capability
        "info:list:0",  # action not valid for info
        "info:book:1",
        "info:show:nope",  # unknown page
        "Info:show:about",
        "x" * 70,
    ],
)
async def test_stale_callbacks_never_raise(workshop_h: Harness, data: str | None) -> None:
    """Stale capability data: a NEW message (never an edit of the pressed one) with the notice and
    one button to the current menu."""
    r = await workshop_h.tap("ali", data)  # type: ignore[arg-type]
    assert len(r.messages) == 1 and r.messages[0].edit is False
    assert text(r) == nav_texts.STALE
    assert button_data(r) == ["nav:go:home"]
    assert r.outcomes == []


@pytest.mark.parametrize(
    "data",
    [
        "menu:open:nope",
        "menu:show:about",
        "nav:go:nope",
        "nav:go:bkg~9",
        "nav:go:mgr",
        "nav:open:x",
        "nav:go:",
    ],
)
async def test_stale_navigation_sends_the_home_as_a_new_message(workshop_h: Harness, data: str) -> None:
    """Unknown, out-of-range or forbidden navigation is forgiving: the role home as a NEW message
    under the stale notice; the pressed message is left alone."""
    r = await workshop_h.tap("ali", data)
    assert len(r.messages) == 1 and r.messages[0].edit is False
    assert text(r).startswith(nav_texts.STALE + "\n")
    assert button_data(r) == WORKSHOP_MENU
    assert r.outcomes == []


async def test_session_text_goes_to_owning_engine(workshop: BotSpec) -> None:
    h = Harness(workshop)
    fake = RecordingEngine()
    await h.store.set_session("ali", {"capability": "info", "step": "x", "vars": {}})
    with override_engine("info", fake):
        r = await h.send("ali", "پاسخ من")
    assert fake.calls == [("text", "info", "پاسخ من")]
    assert text(r) == "got text"


async def test_session_for_removed_capability_is_discarded(workshop_h: Harness, workshop: BotSpec) -> None:
    await workshop_h.store.set_session("ali", {"capability": "gone", "step": "form", "vars": {}})
    r = await workshop_h.send("ali", "متن")
    assert text(r) == workshop.bot.welcome_text
    assert await workshop_h.store.get_session("ali") is None


async def test_garbage_session_is_discarded(workshop_h: Harness) -> None:
    await workshop_h.store.set_session("ali", {"vars": {}})
    await workshop_h.send("ali", "متن")
    assert await workshop_h.store.get_session("ali") is None


async def test_info_engine_text_with_its_session_drops_it(workshop_h: Harness) -> None:
    await workshop_h.store.set_session("ali", {"capability": "info", "step": "x", "vars": {}})
    r = await workshop_h.send("ali", "متن")
    assert text(r).startswith("🏠 ") and button_data(r) == WORKSHOP_MENU
    assert await workshop_h.store.get_session("ali") is None


async def test_non_form_callback_clears_session_form_callback_keeps_it(repair: BotSpec) -> None:
    h = Harness(repair)
    fake = RecordingEngine()
    state = {"capability": "repair", "step": "form", "vars": {}}
    with override_engine("request", fake):
        await h.store.set_session("ali", state)
        await h.tap("ali", "repair:skip:")
        assert await h.store.get_session("ali") == state
        await h.tap("ali", "repair:ans:1")
        assert await h.store.get_session("ali") == state
        await h.tap("ali", "repair:mine:")
        assert await h.store.get_session("ali") is None
        await h.store.set_session("ali", state)
        await h.tap("ali", "menu:home:")
        assert await h.store.get_session("ali") is None
    assert fake.calls == [
        ("callback", "repair", "skip", ""),
        ("callback", "repair", "ans", "1"),
        ("callback", "repair", "mine", ""),
    ]


async def test_menu_open_routes_to_engine_with_view(repair: BotSpec) -> None:
    h = Harness(repair)
    fake = RecordingEngine()
    with override_engine("request", fake):
        await h.tap("ali", "menu:open:new_request")
        await h.tap("ali", "menu:open:my_requests")
    assert fake.calls == [("open", "repair", "main"), ("open", "repair", "mine")]


async def test_admin_non_owner_rejected(workshop_h: Harness, repair: BotSpec) -> None:
    r = await workshop_h.admin("book_workshop:cancel:42", actor="ali")
    assert [o.model_dump() for o in r.outcomes] == [
        {"capability": "book_workshop", "action": "cancel", "result": "rejected",
         "reason": "not_allowed", "record_id": None}
    ]  # fmt: skip
    assert text(r) == common.NOT_ALLOWED
    h = Harness(repair)
    fake = RecordingEngine()
    with override_engine("request", fake):
        r = await h.admin("repair:own:17.approve", actor="ali")
        r2 = await h.tap("ali", "repair:own:17.approve")  # Telegram inline button, non-owner
    assert fake.calls == []
    for resp in (r, r2):
        assert len(resp.outcomes) == 1
        o = resp.outcomes[0]
        assert (o.capability, o.action, o.result, o.reason) == (
            "repair",
            "owner_action",
            "rejected",
            "not_allowed",
        )


async def test_owner_actions_share_one_path(repair: BotSpec, workshop: BotSpec) -> None:
    h = Harness(repair)
    fake = RecordingEngine()
    with override_engine("request", fake):
        r1 = await h.admin("repair:own:17.approve")
        r2 = await h.tap("owner", "repair:own:18.mark_done")
    assert fake.calls == [("owner", "repair", 17, "approve"), ("owner", "repair", 18, "mark_done")]
    assert r1.outcomes[0].result == "ok" and r2.outcomes[0].record_id == 18

    hw = Harness(workshop)
    fake_b = RecordingEngine()
    with override_engine("booking", fake_b):
        r = await hw.admin("book_workshop:cancel:42")
        await hw.tap("owner", "book_workshop:cancel:43")  # a user cancel (owner as a user)
    assert fake_b.calls == [
        ("owner", "book_workshop", 42, "cancel"),
        ("callback", "book_workshop", "cancel", "43"),
    ]
    assert r.outcomes[0].action == "cancel"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ("repair:own:abc.approve", "invalid_input"),
        ("repair:own:17", "invalid_input"),
        ("repair:own:17.", "invalid_input"),
        ("repair:mine:", "invalid_input"),  # not an owner action
        ("repair:cancel:3", "invalid_input"),  # cancel is booking-only
        ("nope:own:1.approve", "not_found"),
    ],
)
async def test_admin_bad_data_rejected(repair: BotSpec, data: str, reason: str) -> None:
    h = Harness(repair)
    fake = RecordingEngine()
    with override_engine("request", fake):
        r = await h.admin(data)
    assert fake.calls == []
    assert [o.reason for o in r.outcomes] == [reason]
    assert r.outcomes[0].result == "rejected"


async def test_admin_malformed_data_is_stale(repair: BotSpec) -> None:
    r = await Harness(repair).admin("not callback data")
    assert text(r) == nav_texts.STALE and r.outcomes == []


async def test_every_event_upserts_actor(workshop_h: Harness) -> None:
    await workshop_h.tap(Actor(id="u7", display_name="کاربر هفت"), "menu:home:")
    await workshop_h.admin("x", actor="u8")
    assert workshop_h.store.users["u7"].display_name == "کاربر هفت"
    assert "u8" in workshop_h.store.users


async def test_runtime_is_deterministic(workshop: BotSpec) -> None:
    async def run() -> list[dict[str, Any]]:
        h = Harness(workshop)
        out = []
        for data in ("menu:open:about", "info:show:address", "menu:home:", "bad"):
            out.append((await h.tap("ali", data)).model_dump())
        return out

    assert await run() == await run()


# --- Ctx builder ---------------------------------------------------------------------------


async def _ctx(spec: BotSpec, kind: str = "callback", actor: str = "ali", owner: str | None = "owner") -> Ctx:
    from app.runtime.contracts import RuntimeEvent
    from app.runtime.memory_store import MemoryStore

    ev = RuntimeEvent(
        bot_id="b",
        env="sandbox",
        actor=Harness.actor(actor),
        kind=kind,
        data="x:y:z",
        now=T0,  # type: ignore[arg-type]
    )
    return await Ctx.create(ev, spec, MemoryStore(owner_actor_id=owner))


async def test_ctx_reply_edit_defaults(workshop: BotSpec) -> None:
    ctx = await _ctx(workshop, "callback")
    ctx.reply("a")
    ctx.reply("b")
    ctx.reply("c", edit=False)
    assert [m.edit for m in ctx.messages] == [True, False, False]
    ctx2 = await _ctx(workshop, "text")
    ctx2.reply("a")
    assert ctx2.messages[0].edit is False


async def test_ctx_notify_and_owner(workshop: BotSpec) -> None:
    ctx = await _ctx(workshop)
    ctx.notify(None, "promoted", "x")
    assert ctx.messages == [] and ctx.effects == []
    ctx.notify("sara", "promoted", "تبریک")
    ctx.notify_owner("booked", "ثبت‌نام جدید")
    assert [(m.to_actor_id, m.notice, m.edit) for m in ctx.messages] == [
        ("sara", "promoted", False),
        ("owner", "booked", False),
    ]
    assert [(e.kind, e.to_actor_id) for e in ctx.effects] == [
        ("notification", "sara"),
        ("notification", "owner"),
    ]

    own = await _ctx(workshop, actor="owner")
    own.notify_owner("cancelled", "x")
    assert own.messages == []
    unlinked = await _ctx(workshop, owner=None)
    unlinked.notify_owner("cancelled", "x")
    assert unlinked.messages == []


async def test_ctx_record_helpers_emit_effects(workshop: BotSpec) -> None:
    ctx = await _ctx(workshop)
    rec = await ctx.create_record("book_workshop", {"a": 1}, status="confirmed", item_id=5)
    assert rec.actor_id == "ali" and rec.created_at == T0
    other = await ctx.create_record("workshop", {}, actor_id=None)
    assert other.actor_id is None
    await ctx.update_record("book_workshop", rec.id, status="cancelled")
    await ctx.delete_record("workshop", other.id)
    assert [(e.kind, e.record_id, e.status) for e in ctx.effects] == [
        ("record_created", rec.id, "confirmed"),
        ("record_created", other.id, None),
        ("record_updated", rec.id, "cancelled"),
        ("record_deleted", other.id, None),
    ]


async def test_ctx_reject_and_outcome(workshop: BotSpec) -> None:
    ctx = await _ctx(workshop)
    cap = workshop.capability("book_workshop")
    assert cap is not None
    ctx.reject(cap, "book", "capacity_full", "ظرفیت تکمیل است", record_id=3)
    resp = ctx.response()
    assert resp.messages[0].text == "ظرفیت تکمیل است"
    assert resp.outcomes[0].model_dump() == {
        "capability": "book_workshop", "action": "book", "result": "rejected",
        "reason": "capacity_full", "record_id": 3,
    }  # fmt: skip
