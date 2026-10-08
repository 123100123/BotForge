"""Event management from Telegram for managers (runtime/manager_events.py, U7): the guided creation
form, the manager list and detail, attendees, announcements and group publishing. Fake store, fixed
clock (harness T0 = Sunday 12 Mehr 1405, 11:30 in Tehran)."""

import copy
from collections.abc import Sequence
from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.validate import validate_spec
from app.runtime import forms, manager_events, nav
from app.runtime.callbacks import MAX_CALLBACK_BYTES
from app.runtime.contracts import Actor, Button, RuntimeResponse
from app.runtime.memory_store import MemoryStore
from app.runtime.texts import manager_events as tx
from app.runtime.texts import nav as nav_tx
from tests.unit.runtime.harness import Harness, button_data, buttons, text

OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)
ALI = Actor(id="ali", display_name="علی")
SARA = Actor(id="sara", display_name="سارا")
STAFF = Actor(id="sam", display_name="سام", role="staff")
MANAGER = Actor(id="mina", display_name="مینا", role="manager")

CAP = "events"
TITLE = "کارگاه پایتون"
HOME = "nav:go:mgr"


def events_data(**cap_over: Any) -> dict[str, Any]:
    """The registry's events preset (capabilities/registry.py) plus an info page."""
    cap: dict[str, Any] = {
        "type": "booking",
        "key": CAP,
        "title": "رویدادها",
        "resource": "event",
        "capacity": {"mode": "per_item", "field": "capacity"},
        "start_field": "starts_at",
        "detail_fields": ["description", "category", "starts_at", "location"],
        "waitlist": {"enabled": True, "auto_promote": True},
        "notify_user_on": ["promoted"],
        "preset": "events",
        "reminder_hours_before": 24,
        "category_field": "category",
    }
    cap.update(cap_over)
    return {
        "bot": {"name": "کافه نمونه", "welcome_text": "خوش آمدید!", "timezone": "Asia/Tehran"},
        "resources": [
            {
                "key": "event",
                "label": "رویداد",
                "label_plural": "رویدادها",
                "title_field": "title",
                "fields": [
                    {"key": "title", "label": "عنوان", "type": "text"},
                    {"key": "description", "label": "توضیحات", "type": "long_text", "required": False},
                    {
                        "key": "category",
                        "label": "دسته‌بندی",
                        "type": "choice",
                        "required": False,
                        "choices": ["آموزشی", "سازمانی", "اجتماعی"],
                    },
                    {"key": "starts_at", "label": "زمان شروع", "type": "datetime"},
                    {"key": "location", "label": "مکان", "type": "text", "required": False},
                    {"key": "capacity", "label": "ظرفیت", "type": "integer"},
                ],
            }
        ],
        "capabilities": [
            cap,
            {
                "type": "info",
                "key": "info",
                "title": "دربارهٔ ما",
                "pages": [{"key": "a", "title": "ما", "body": "متن"}],
            },
        ],
        "menu": [],
    }


def spec_of(data: dict[str, Any]) -> BotSpec:
    spec = BotSpec.model_validate(data)
    assert not [i for i in validate_spec(spec) if i.severity == "error"]
    return spec


class OutboxStore(MemoryStore):
    """MemoryStore with the optional runtime services PgStore offers in live."""

    def __init__(self, groups: list[tuple[int, str]] | None = None) -> None:
        super().__init__()
        self.groups = groups or []
        self.queued: list[tuple[list[int], str, list[list[Button]] | None]] = []

    async def group_chats(self) -> list[tuple[int, str]]:
        return list(self.groups)

    async def enqueue_outbox(
        self, chat_ids: Sequence[int], text: str, buttons: list[list[Button]] | None = None
    ) -> bool:
        self.queued.append((list(chat_ids), text, buttons))
        return True


def harness(store: MemoryStore | None = None, **cap_over: Any) -> Harness:
    return Harness(spec_of(events_data(**cap_over)), store)


SEEN: list[str] = []  # every callback data the tests saw (payload limit test)


def record(r: RuntimeResponse) -> RuntimeResponse:
    for m in r.messages:
        SEEN.extend(b.data for row in m.buttons for b in row)
    return r


async def tap(h: Harness, data: str, actor: Actor = OWNER) -> RuntimeResponse:
    return record(await h.tap(actor, data))


async def send(h: Harness, message: str, actor: Actor = OWNER) -> RuntimeResponse:
    return record(await h.send(actor, message))


async def session(h: Harness, actor: Actor = OWNER) -> dict[str, Any] | None:
    return await h.store.get_session(actor.id)


async def stage(h: Harness) -> str | None:
    s = await session(h)
    return s["vars"]["stage"] if s else None


def events(h: Harness) -> list[Any]:
    return [r for r in h.store.all_records() if r.collection == "event"]  # type: ignore[attr-defined]


async def fill_form(h: Harness) -> RuntimeResponse:
    """New event through every step with buttons: title, skip description, 20 Mehr, 18:30,
    first category, a place, capacity 20 -> the preview."""
    await tap(h, "nav:go:mgr.evt.new")
    await send(h, TITLE)
    await tap(h, f"{CAP}:skip:")
    await tap(h, f"{CAP}:ans:d20261012")
    await tap(h, f"{CAP}:ans:t1830")
    await tap(h, f"{CAP}:ans:o0")
    await send(h, "تهران، خیابان آزادی")
    return await send(h, "۲۰")


STAGES = [
    "text:title",
    "text:description",
    "date:starts_at",
    "time:starts_at",
    "choice:category",
    "text:location",
    "number:capacity",
    "preview",
]


# --- creation --------------------------------------------------------------------------------------


async def test_full_creation_flow_creates_one_event_in_utc() -> None:
    h = harness()
    r = await tap(h, "nav:go:mgr.evt")
    assert text(r).startswith("🧭 مدیریت › 📅 رویدادها")
    assert button_data(r)[0] == "nav:go:mgr.evt.new" and buttons(r)[0].label == "➕ رویداد جدید"

    r = await tap(h, "nav:go:mgr.evt.new")
    assert r.messages[0].edit and "مرحلهٔ ۱ از ۷: عنوان" in text(r)
    assert button_data(r) == ["nav:go:mgr.evt", f"{CAP}:stop:", HOME]  # Back leaves the form

    r = await send(h, TITLE)
    assert "مرحلهٔ ۲ از ۷: توضیحات" in text(r)
    assert button_data(r) == [f"{CAP}:skip:", f"{CAP}:ans:b", f"{CAP}:stop:", HOME]

    r = await tap(h, f"{CAP}:skip:")  # date: the next 14 days in Jalali
    days = [b for b in buttons(r) if b.data.startswith(f"{CAP}:ans:d2")]
    assert len(days) == 14
    assert (days[0].label, days[0].data) == ("یکشنبه ۱۲ مهر", f"{CAP}:ans:d20261004")
    assert days[-1].data == f"{CAP}:ans:d20261017"
    assert [len(row) for row in r.messages[-1].buttons[:7]] == [2] * 7
    assert f"{CAP}:ans:dx" in button_data(r)

    r = await tap(h, f"{CAP}:ans:d20261012")  # time: 08:00..22:00 every 30 minutes, rows of four
    slots = [b for b in buttons(r) if b.data.startswith(f"{CAP}:ans:t")]
    assert len(slots) == 29
    assert (slots[0].label, slots[0].data) == ("۰۸:۰۰", f"{CAP}:ans:t0800")
    assert slots[-1].data == f"{CAP}:ans:t2200"
    assert [len(row) for row in r.messages[-1].buttons[:8]] == [4] * 7 + [1]

    r = await tap(h, f"{CAP}:ans:t1830")  # category buttons from the field's choices
    assert [b.label for b in buttons(r)][:3] == ["آموزشی", "سازمانی", "اجتماعی"]
    r = await tap(h, f"{CAP}:ans:o0")
    assert "مرحلهٔ ۶ از ۷: مکان" in text(r)
    r = await send(h, "تهران، خیابان آزادی")
    assert "۲۰" in [b.label for b in buttons(r)]  # capacity shortcuts
    assert f"{CAP}:skip:" not in button_data(r)  # per_item capacity is required: no "unlimited"
    r = await send(h, "۲۰")

    assert await stage(h) == "preview"
    preview = text(r)
    assert "زمان شروع: دوشنبه ۲۰ مهر ۱۴۰۵، ساعت ۱۸:۳۰" in preview
    assert f"عنوان: {TITLE}" in preview and "ظرفیت: ۲۰" in preview and "توضیحات: —" in preview
    assert button_data(r) == [f"{CAP}:ans:pub", f"{CAP}:ans:edit", f"{CAP}:ans:b", f"{CAP}:stop:", HOME]

    r = await tap(h, f"{CAP}:ans:pub")
    [event] = events(h)
    assert event.data == {
        "title": TITLE,
        "description": None,
        "category": "آموزشی",
        "starts_at": "2026-10-12T15:00:00+00:00",  # 18:30 in Tehran (+03:30)
        "location": "تهران، خیابان آزادی",
        "capacity": 20,
    }
    assert event.actor_id is None  # like a record created from the web data admin
    assert "رویداد ثبت شد و برای مشتریان نمایش داده می‌شود." in text(r)
    assert button_data(r) == [f"nav:go:mgr.evt.{event.id}", "nav:go:mgr.evt", HOME]  # no groups: no publish
    assert [e.kind for e in r.effects] == ["record_created"]
    assert await session(h) is None

    r = await tap(h, f"{CAP}:ans:pub")  # pressed again: no session, no second event
    assert len(events(h)) == 1 and [m.edit for m in r.messages] == [False]


async def test_typed_jalali_date_and_time_and_invalid_input_reasks() -> None:
    h = harness()
    await tap(h, "nav:go:mgr.evt.new")
    await send(h, TITLE)
    await send(h, "یک دورهمی دوستانه")  # description typed
    r = await tap(h, f"{CAP}:ans:dx")
    assert tx.ASK_DATE_TYPED in text(r) and button_data(r) == [f"{CAP}:ans:dd", f"{CAP}:stop:", HOME]
    r = await send(h, "۱۴۰۵/۱۳/۰۱")
    assert "تاریخ معتبری نیست" in text(r) and await stage(h) == "date:starts_at"
    r = await send(h, "1405/7/1")  # 1 Mehr is before today (12 Mehr)
    assert tx.PAST_DATE in text(r) and await stage(h) == "date:starts_at"
    r = await send(h, "۱۴۰۵/۷/۲۰")
    assert await stage(h) == "time:starts_at"
    r = await send(h, "25:00")
    assert "ساعت معتبری نیست" in text(r) and await stage(h) == "time:starts_at"
    r = await send(h, "۱۸:۳۰")
    assert await stage(h) == "choice:category"
    r = await send(h, "چیز دیگر")  # not a choice: re-asked with the buttons
    assert tx.USE_BUTTONS in text(r) and await stage(h) == "choice:category"
    await send(h, "اجتماعی")
    await tap(h, f"{CAP}:skip:")  # no place
    r = await send(h, "صفر")
    assert "عدد صحیح" in text(r) and await stage(h) == "number:capacity"
    r = await send(h, "0")
    assert tx.INVALID_CAPACITY in text(r)
    await send(h, "1405-07-21")  # still the capacity step: a date is not a number
    assert await stage(h) == "number:capacity"
    await tap(h, f"{CAP}:ans:n50")
    await tap(h, f"{CAP}:ans:pub")
    [event] = events(h)
    assert event.data["starts_at"] == "2026-10-12T15:00:00+00:00"
    assert (event.data["category"], event.data["capacity"], event.data["location"]) == ("اجتماعی", 50, None)
    assert event.data["description"] == "یک دورهمی دوستانه"


async def test_today_hides_past_times_and_rejects_a_past_typed_time() -> None:
    h = harness()
    await tap(h, "nav:go:mgr.evt.new")
    await send(h, TITLE)
    await tap(h, f"{CAP}:skip:")
    r = await tap(h, f"{CAP}:ans:d20261004")  # today, 11:30 in Tehran
    slots = [b.data for b in buttons(r) if b.data.startswith(f"{CAP}:ans:t")]
    assert slots[0] == f"{CAP}:ans:t1200" and len(slots) == 21
    r = await send(h, "۱۱:۰۰")
    assert tx.PAST_TIME in text(r) and await stage(h) == "time:starts_at"
    r = await tap(h, f"{CAP}:ans:t0900")  # an old button for a past slot
    assert tx.PAST_TIME in text(r)
    await send(h, "12:00")
    assert await stage(h) == "choice:category"


async def test_back_returns_to_the_previous_step_at_every_step() -> None:
    h = harness()
    await fill_form(h)
    for i in range(len(STAGES) - 1, 0, -1):
        assert await stage(h) == STAGES[i]
        r = await tap(h, f"{CAP}:ans:b")
        assert await stage(h) == STAGES[i - 1]
        assert r.messages[0].edit
        assert f"{CAP}:ans:k" in button_data(r)  # the step still has its value
    assert "nav:go:mgr.evt" in button_data(h.last)  # type: ignore[arg-type]  # first step: Back leaves
    r = await tap(h, "nav:go:mgr.evt")
    assert await session(h) is None and text(r).startswith("🧭 مدیریت › 📅 رویدادها")


@pytest.mark.parametrize("steps_done", range(len(STAGES)))
async def test_cancel_at_every_step_ends_the_flow(steps_done: int) -> None:
    h = harness()
    actions = [
        ("send", TITLE),
        ("tap", f"{CAP}:skip:"),
        ("tap", f"{CAP}:ans:d20261012"),
        ("tap", f"{CAP}:ans:t1830"),
        ("tap", f"{CAP}:ans:o1"),
        ("tap", f"{CAP}:skip:"),
        ("send", "12"),
    ]
    r = await tap(h, "nav:go:mgr.evt.new")
    for kind, value in actions[:steps_done]:
        r = await (send(h, value) if kind == "send" else tap(h, value))
    assert await stage(h) == STAGES[steps_done]
    assert f"{CAP}:stop:" in button_data(r)
    r = await tap(h, f"{CAP}:stop:")
    assert await session(h) is None and not events(h)
    assert text(r) == "ساخت رویداد لغو شد."
    assert button_data(r) == ["nav:go:mgr.evt", "nav:go:mgr"]
    r = await send(h, "متن بعدی")  # no form captures text any more
    assert not events(h) and "🧭 مدیریت" in text(r)


async def test_preview_edit_keeps_values() -> None:
    h = harness()
    await fill_form(h)
    r = await tap(h, f"{CAP}:ans:edit")
    assert await stage(h) == "text:title"
    assert f"مقدار فعلی: {TITLE}" in text(r) and f"{CAP}:ans:k" in button_data(r)
    r = await send(h, "کارگاه جنگو")  # change the title, keep everything else
    while await stage(h) != "preview":
        assert f"{CAP}:ans:k" in button_data(r)
        r = await tap(h, f"{CAP}:ans:k")
    assert (
        "عنوان: کارگاه جنگو" in text(r) and "ساعت ۱۸:۳۰" in text(r) and "مکان: تهران، خیابان آزادی" in text(r)
    )
    await tap(h, f"{CAP}:ans:pub")
    [event] = events(h)
    assert event.data["title"] == "کارگاه جنگو" and event.data["capacity"] == 20


async def test_old_step_buttons_reask_the_current_step_in_a_new_message() -> None:
    h = harness()
    await tap(h, "nav:go:mgr.evt.new")
    await send(h, TITLE)
    await tap(h, f"{CAP}:skip:")
    await tap(h, f"{CAP}:ans:d20261012")
    r = await tap(h, f"{CAP}:ans:d20261013")  # the date message's button, now at the time step
    assert await stage(h) == "time:starts_at"
    assert [m.edit for m in r.messages] == [False] and tx.STEP_STALE in text(r)
    r = await tap(h, f"{CAP}:ans:o9")
    assert await stage(h) == "time:starts_at" and tx.STEP_STALE in text(r)


async def test_created_event_appears_in_the_customer_events_list() -> None:
    h = harness()
    await fill_form(h)
    await tap(h, f"{CAP}:ans:pub")
    [event] = events(h)
    r = await tap(h, "nav:go:evt", ALI)
    assert TITLE in text(r)
    assert f"{CAP}:item:{event.id}" in button_data(r)
    r = await tap(h, f"{CAP}:book:{event.id}", ALI)
    assert [o.result for o in r.outcomes] == ["confirmed"]


async def test_non_managers_get_the_stale_home() -> None:
    h = harness()
    for actor in (ALI, STAFF):
        for data in ("nav:go:mgr.evt.new", "nav:go:mgr.evt", "nav:go:mgr.evt.att.1", "nav:go:mgr.evt.ann.1"):
            r = await tap(h, data, actor)
            assert [m.edit for m in r.messages] == [False], data
            assert text(r).startswith(nav_tx.STALE + "\n\n"), data
            assert await session(h, actor) is None
    # a stored manager (not the owner) may manage events
    r = await tap(h, "nav:go:mgr.evt.new", MANAGER)
    assert "مرحلهٔ ۱ از ۷" in text(r)


async def test_a_demoted_manager_mid_form_is_stopped() -> None:
    h = harness()
    await tap(h, "nav:go:mgr.evt.new", MANAGER)
    demoted = MANAGER.model_copy(update={"role": "customer"})
    r = await send(h, TITLE, demoted)
    assert await session(h, demoted) is None and not events(h)
    assert r.messages[-1].text == nav_tx.STALE


async def test_disabled_events_capability_has_no_manager_entry() -> None:
    h = harness(enabled=False)
    r = await h.start(OWNER)
    assert not [d for d in button_data(r) if d.startswith("nav:go:mgr.evt")]
    r = await tap(h, "nav:go:mgr.evt.new")
    assert text(r).startswith(nav_tx.STALE) and await session(h) is None
    on = harness()
    r = await on.start(OWNER)
    assert "nav:go:mgr.evt" in button_data(r)


# --- list, detail, attendees ---------------------------------------------------------------------


async def seed_event(h: Harness, title: str, starts_at: str, capacity: int = 1, **extra: Any) -> int:
    data = {"title": title, "starts_at": starts_at, "capacity": capacity, **extra}
    return await h.seed("event", data)


async def test_list_upcoming_sorted_with_counts_and_a_past_toggle() -> None:
    h = harness()
    later = await seed_event(h, "دوم", "2026-10-20T15:00:00+00:00", capacity=20)
    sooner = await seed_event(h, "اول", "2026-10-06T15:00:00+00:00", capacity=0)
    past = await seed_event(h, "قدیمی", "2026-09-01T15:00:00+00:00")
    await tap(h, f"{CAP}:book:{later}", ALI)
    r = await tap(h, "nav:go:mgr.evt")
    labels = [b.label for b in buttons(r)]
    assert labels[1:3] == ["اول · ۱۴ مهر · ۰ نفر", "دوم · ۲۸ مهر · ۱/۲۰"]
    assert button_data(r)[1:3] == [f"nav:go:mgr.evt.{sooner}", f"nav:go:mgr.evt.{later}"]
    assert button_data(r)[-2:] == ["nav:go:mgr.evt.past", "nav:go:mgr"]
    r = await tap(h, "nav:go:mgr.evt.past")
    assert button_data(r)[1] == f"nav:go:mgr.evt.{past}" and "nav:go:mgr.evt" in button_data(r)
    r = await tap(h, f"nav:go:mgr.evt.{past}")
    assert tx.DETAIL_PAST.replace("{label}", "رویداد") in text(r)
    assert button_data(r)[-2:] == ["nav:go:mgr.evt.past", HOME]


async def test_manager_detail_has_counts_and_no_rsvp_buttons() -> None:
    h = harness()
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 1, location="سالن ۱", category="آموزشی")
    await tap(h, f"{CAP}:book:{eid}", ALI)
    await tap(h, f"{CAP}:book:{eid}", SARA)  # waitlisted
    r = await tap(h, f"nav:go:mgr.evt.{eid}")
    body = text(r)
    assert body.startswith(f"🧭 مدیریت › 📅 رویدادها › {TITLE}")
    for line in (
        "🗓 دوشنبه ۲۰ مهر ۱۴۰۵، ساعت ۱۸:۳۰",
        "📍 سالن ۱",
        "🏷 آموزشی",
        "👥 ظرفیت: ۱",
        "قطعی: ۱ · ⏳ در انتظار: ۱",
    ):
        assert line in body
    assert button_data(r) == [
        f"nav:go:mgr.evt.att.{eid}",
        f"nav:go:mgr.evt.ann.{eid}",
        "nav:go:mgr.evt",
        HOME,
    ]
    assert not [d for d in button_data(r) if d.startswith(f"{CAP}:")]  # no book/cancel for managers
    r = await tap(h, "nav:go:mgr.evt.999")
    assert [m.edit for m in r.messages] == [False] and "دیگر وجود ندارد" in text(r)


async def test_attendee_list_shows_confirmed_and_waitlisted_and_cancels_one() -> None:
    h = harness()
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 1)
    await tap(h, f"{CAP}:book:{eid}", ALI)
    await tap(h, f"{CAP}:book:{eid}", SARA)
    r = await tap(h, f"nav:go:mgr.evt.att.{eid}")
    assert "۱. علی — قطعی" in text(r) and "۲. سارا — در انتظار (نوبت ۱)" in text(r)
    ali_booking = next(b for b in h.store.all_records() if b.collection == CAP and b.actor_id == "ali")  # type: ignore[attr-defined]
    assert button_data(r) == [
        f"nav:go:mgr.evt.cx.{ali_booking.id}",
        f"nav:go:mgr.evt.cx.{ali_booking.id + 1}",
        f"nav:go:mgr.evt.{eid}",
        HOME,
    ]
    r = await tap(h, f"nav:go:mgr.evt.cx.{ali_booking.id}")  # confirm first
    assert "«علی»" in text(r) and button_data(r)[0] == f"nav:go:mgr.evt.cxy.{ali_booking.id}"
    r = await tap(h, f"nav:go:mgr.evt.cxy.{ali_booking.id}")
    assert [o.result for o in r.outcomes] == ["cancelled"]
    own = [m for m in r.messages if m.to_actor_id == "owner"]
    assert len(own) == 1 and own[0].edit
    assert "ثبت‌نام «علی» لغو شد" in own[0].text and "۱. سارا — قطعی" in own[0].text  # promoted
    assert {m.to_actor_id: m.notice for m in r.messages if m.notice} == {
        "ali": "cancelled",
        "sara": "promoted",
    }
    r = await tap(h, f"nav:go:mgr.evt.cxy.{ali_booking.id}")  # again: nothing to cancel
    assert tx.BOOKING_GONE in text(r) and not r.outcomes


async def test_attendee_names_come_from_the_store() -> None:
    h = harness()
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 5)
    await h.seed(CAP, {}, status="confirmed", actor_id="ghost", item_id=eid)  # never talked to the bot
    await tap(h, f"{CAP}:book:{eid}", ALI)
    r = await tap(h, f"nav:go:mgr.evt.att.{eid}")
    assert "۱. کاربر ghost — قطعی" in text(r) and "۲. علی — قطعی" in text(r)


# --- announcements -------------------------------------------------------------------------------


async def test_announcement_goes_to_confirmed_registrants_only() -> None:
    h = harness()
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 1)
    await tap(h, f"{CAP}:book:{eid}", ALI)
    await tap(h, f"{CAP}:book:{eid}", SARA)  # waitlisted: not a recipient
    r = await tap(h, f"nav:go:mgr.evt.ann.{eid}")
    assert "برای ۱ نفر" in text(r)
    r = await send(h, "  مکان عوض شد: سالن ۲  ")
    assert "مکان عوض شد: سالن ۲" in text(r)
    assert button_data(r)[:2] == [f"{CAP}:ans:send", f"{CAP}:ans:re"]
    r = await tap(h, f"{CAP}:ans:send")
    notices = [m for m in r.messages if m.notice]
    assert [(m.to_actor_id, m.notice) for m in notices] == [("ali", "announcement")]
    assert notices[0].text == f"📣 {TITLE}\n\nمکان عوض شد: سالن ۲"
    assert [b.data for row in notices[0].buttons for b in row] == [f"{CAP}:item:{eid}"]
    assert "در صف ارسال" in next(m for m in r.messages if m.to_actor_id == "owner").text
    assert await session(h) is None
    r = await tap(h, f"{CAP}:ans:send")  # again: stale, nothing sent
    assert not [m for m in r.messages if m.notice]


async def test_announcement_uses_the_outbox_when_the_store_has_one() -> None:
    store = OutboxStore()
    h = harness(store)
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 5)
    for actor_id in ("1001", "1002"):
        await tap(h, f"{CAP}:book:{eid}", Actor(id=actor_id, display_name=actor_id))
    await tap(h, f"nav:go:mgr.evt.ann.{eid}")
    await send(h, "یادآوری")
    r = await tap(h, f"{CAP}:ans:send")
    assert not [m for m in r.messages if m.notice]
    assert store.queued == [([1001, 1002], f"📣 {TITLE}\n\nیادآوری", store.queued[0][2])]


async def test_announcement_rewrite_cancel_and_nobody() -> None:
    h = harness()
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 5)
    r = await tap(h, f"nav:go:mgr.evt.ann.{eid}")
    assert tx.ANNOUNCE_NOBODY in text(r) and await session(h) is None
    await tap(h, f"{CAP}:book:{eid}", ALI)
    await tap(h, f"nav:go:mgr.evt.ann.{eid}")
    r = await send(h, "x" * 3501)
    assert "حداکثر" in text(r)
    await send(h, "اول")
    r = await tap(h, f"{CAP}:ans:re")
    assert "متن اعلان را بنویسید" in text(r)
    r = await tap(h, f"{CAP}:stop:")
    assert (
        text(r) == tx.ANNOUNCE_CANCELLED
        and await session(h) is None
        and not [m for m in r.messages if m.notice]
    )


# --- groups --------------------------------------------------------------------------------------


async def test_group_publish_is_offered_only_when_the_bot_is_in_a_group() -> None:
    store = OutboxStore(groups=[(-1001234567890, "گروه کافه")])
    h = harness(store)
    await fill_form(h)
    r = await tap(h, f"{CAP}:ans:pub")
    [event] = events(h)
    assert button_data(r)[0] == f"nav:go:mgr.evt.pub.{event.id}"
    r = await tap(h, f"nav:go:mgr.evt.{event.id}")
    assert f"nav:go:mgr.evt.pub.{event.id}" in button_data(r)
    r = await tap(h, f"nav:go:mgr.evt.pub.{event.id}")
    assert button_data(r)[0] == f"nav:go:mgr.evt.pub.{event.id}.n1001234567890"
    r = await tap(h, f"nav:go:mgr.evt.pub.{event.id}.n1001234567890")
    [(chats, card, card_buttons)] = store.queued
    assert chats == [-1001234567890] and card.startswith(f"📅 {TITLE}")
    assert [b.data for row in card_buttons or [] for b in row] == [f"{CAP}:book:{event.id}"]
    assert "گروه کافه" in text(r)
    r = await tap(h, f"nav:go:mgr.evt.pub.{event.id}.n42")  # not one of the bot's groups
    assert tx.GROUP_GONE in text(r) and len(store.queued) == 1

    plain = harness()  # no groups (sandbox, tests): never offered, and the route says so
    eid = await seed_event(plain, TITLE, "2026-10-12T15:00:00+00:00")
    r = await tap(plain, f"nav:go:mgr.evt.{eid}")
    assert not [d for d in button_data(r) if ".pub." in d]
    r = await tap(plain, f"nav:go:mgr.evt.pub.{eid}")
    assert tx.NO_GROUPS in text(r)


# --- contracts -----------------------------------------------------------------------------------


async def test_every_payload_fits_telegram() -> None:
    long_key = "e" * 24
    data = events_data(key=long_key)
    h = Harness(spec_of(data))
    await tap(h, "nav:go:mgr.evt.new")
    await send(h, TITLE)
    await tap(h, f"{long_key}:skip:")
    await tap(h, f"{long_key}:ans:dx")
    await tap(h, f"{long_key}:ans:dd")
    await tap(h, f"{long_key}:ans:d20261012")
    await tap(h, f"{long_key}:ans:t1830")
    await tap(h, f"{long_key}:ans:o2")
    await tap(h, f"{long_key}:skip:")
    await send(h, "7")
    await tap(h, f"{long_key}:ans:pub")
    assert len(events(h)) == 1
    big = 2**63 - 1
    for route in (
        nav.route_payload("mgr.evt", 999, big),
        nav.route_payload("mgr.evt.att", 999, big, 999),
        nav.route_payload("mgr.evt.cxy", 999, big),
        nav.route_payload("mgr.evt.pub", 999, big, f"n{big}"),
        nav.route_payload("mgr.evt.past", 999, 999),
    ):
        SEEN.append(nav.nav_data(route))
    assert SEEN and all(len(d.encode()) <= MAX_CALLBACK_BYTES and d.isascii() for d in SEEN)


async def test_routes_are_registered_and_parse() -> None:
    for payload, (route_id, args) in {
        "mgr.evt": ("mgr.evt", ()),
        "mgr.evt.15": ("mgr.evt", ("15",)),
        "mgr.evt.new": ("mgr.evt.new", ()),
        "mgr.evt.past.2": ("mgr.evt.past", ("2",)),
        "mgr.evt.att.15.1": ("mgr.evt.att", ("15", "1")),
        "mgr.evt.pub~2.15.n100": ("mgr.evt.pub", ("15", "n100")),
    }.items():
        parsed = nav.parse_route(payload)
        assert parsed is not None and (parsed[0].id, parsed[2]) == (route_id, args), payload
        assert parsed[0].role == "manager" and parsed[0].ready
    assert manager_events.STEP_NEW in forms.STEP_HOSTS and manager_events.STEP_ANN in forms.STEP_HOSTS


async def test_unregistered_custom_steps_are_still_stale_and_customer_forms_unchanged() -> None:
    h = harness(form_fields=[{"key": "name", "label": "نام", "type": "text"}])
    await h.store.set_session("ali", {"capability": CAP, "step": "unknown", "vars": {}})
    r = await h.send(ALI, "سلام")
    assert r.messages[-1].text == nav_tx.STALE
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 5)
    r = await h.tap(ALI, f"{CAP}:book:{eid}")
    assert (await h.store.get_session("ali") or {}).get("step") == "form"
    r = await h.send(ALI, "علی رضایی")
    assert [o.result for o in r.outcomes] == ["confirmed"]


def test_spec_fixture_matches_the_registry_preset() -> None:
    from app.capabilities.registry import _events_ops

    ops = _events_ops(
        BotSpec.model_validate({**copy.deepcopy(events_data()), "resources": [], "capabilities": []})
    )
    assert ops is not None
    resource = ops[0].value
    assert [f["key"] for f in resource["fields"]] == [
        f["key"] for f in events_data()["resources"][0]["fields"]
    ]


# --- every screen: Back to its parent and Home -------------------------------------------------------


def screens(r: Any) -> list[Any]:
    return [m for m in r.messages if m.to_actor_id == OWNER.id]


async def test_every_event_screen_ends_with_the_manager_home_button() -> None:
    store = OutboxStore(groups=[(-1001234567890, "گروه کافه")])
    h = harness(store)
    eid = await seed_event(h, TITLE, "2026-10-12T15:00:00+00:00", 1)
    old = await seed_event(h, "قدیمی", "2026-09-01T15:00:00+00:00", 1)
    await tap(h, f"{CAP}:book:{eid}", ALI)
    booking = next(b for b in h.store.all_records() if b.collection == CAP and b.actor_id == "ali")  # type: ignore[attr-defined]

    taps = [
        "nav:go:mgr.evt",
        "nav:go:mgr.evt.past",
        "nav:go:mgr.evt.999",  # not found
        f"nav:go:mgr.evt.{eid}",
        f"nav:go:mgr.evt.{old}",
        f"nav:go:mgr.evt.att.{eid}",
        f"nav:go:mgr.evt.cx.{booking.id}",
        "nav:go:mgr.evt.cx.99999",  # booking gone
        f"nav:go:mgr.evt.pub.{eid}",
        f"nav:go:mgr.evt.pub.{eid}.n42",  # group gone
        f"nav:go:mgr.evt.ann.{eid}",  # asks for the text
    ]
    for data in taps:
        r = await tap(h, data)
        assert HOME in [d for m in screens(r) for row in m.buttons for d in (b.data for b in row)], data
    r = await send(h, "سلام")  # announcement preview
    assert HOME in button_data(r) and f"nav:go:mgr.evt.{eid}" in button_data(r)
    r = await tap(h, f"{CAP}:ans:send")  # sent
    assert HOME in button_data(r)
    await tap(h, f"nav:go:mgr.evt.ann.{eid}")
    r = await tap(h, f"{CAP}:stop:")  # announcement cancelled
    assert HOME in button_data(r)
    r = await tap(h, f"nav:go:mgr.evt.pub.{eid}.n1001234567890")  # group queued
    assert HOME in button_data(r)
    r = await tap(h, f"nav:go:mgr.evt.cxy.{booking.id}")  # attendee cancelled
    assert HOME in button_data(r)
    await fill_form(h)
    r = await tap(h, f"{CAP}:ans:pub")  # event created
    assert HOME in button_data(r)
    await tap(h, "nav:go:mgr.evt.new")
    r = await tap(h, f"{CAP}:stop:")  # creation cancelled
    assert HOME in button_data(r)


async def test_an_optional_step_with_a_value_offers_keep_or_clear_never_skip() -> None:
    h = harness()
    await fill_form(h)
    r = await tap(h, f"{CAP}:ans:edit")  # back to the first step with every value kept
    await tap(h, f"{CAP}:ans:k")  # title kept -> description
    assert await stage(h) == "text:description"
    labels = [b.label for b in buttons(h.last)]  # type: ignore[arg-type]
    assert tx.KEEP in labels and tx.CLEAR in labels and tx.SKIP not in labels
    assert labels.count(tx.KEEP) == 1

    fresh = harness()  # no value yet: only "skip"
    await tap(fresh, "nav:go:mgr.evt.new")
    r = await send(fresh, TITLE)
    labels = [b.label for b in buttons(r)]
    assert tx.SKIP in labels and tx.KEEP not in labels and tx.CLEAR not in labels
