"""Event-level tests for the booking engine (WP2): navigation, every rule and reason code.

All interaction goes through ``BotRuntime.handle`` (via ``Harness``); buttons are located by
parsed callback action and arg, exactly as the scenario drivers do.
"""

import copy
import json
from datetime import timedelta
from typing import Any

from app.botspec.models import BotSpec
from app.botspec.records import to_utc_iso
from app.botspec.validate import validate_spec
from app.runtime.callbacks import parse_callback
from app.runtime.contracts import Actor, Button, Outcome, OutMessage, RuntimeEvent, RuntimeResponse
from app.runtime.ctx import Ctx
from app.runtime.engines import get_engine
from app.runtime.memory_store import MemoryStore
from app.runtime.store import Record
from app.runtime.texts import booking as tx
from app.runtime.texts import nav as nav_texts
from tests.unit.runtime.harness import EXAMPLES, T0, Harness, button_data, text

CAP = "book_workshop"
RES = "workshop"
MENU_MAIN = "menu:open:workshops"
MENU_MINE = "menu:open:my_bookings"


# --- spec and driver helpers (also imported by test_booking_scenarios.py) ---------------------


def workshop_data() -> dict[str, Any]:
    return json.loads((EXAMPLES / "workshop.botspec.json").read_text(encoding="utf-8"))


def booking_spec(
    *, capacity: int | dict[str, Any] | None = 2, seats_field: bool = False, **cap: Any
) -> BotSpec:
    """The workshop example with booking overrides. ``capacity`` int -> fixed value; dict ->
    replaces the capacity object. ``waitlist``/``cancellation`` dicts are merged."""
    data = workshop_data()
    if seats_field:
        data["resources"][0]["fields"].append(
            {"key": "seats", "label": "ظرفیت", "type": "integer", "required": True}
        )
    booking = next(c for c in data["capabilities"] if c["key"] == CAP)
    if isinstance(capacity, int):
        booking["capacity"] = {"mode": "fixed", "value": capacity, "field": None}
    elif isinstance(capacity, dict):
        booking["capacity"] = capacity
    for key, value in cap.items():
        if isinstance(value, dict) and isinstance(booking.get(key), dict):
            booking[key] = {**booking[key], **value}
        else:
            booking[key] = value
    spec = BotSpec.model_validate(data)
    errors = [i for i in validate_spec(spec) if i.severity == "error"]
    assert not errors, errors
    return spec


def with_capacity(spec: BotSpec, value: int) -> BotSpec:
    """Copy of ``spec`` with every fixed-capacity booking set to ``value`` (capacity_override)."""
    out = copy.deepcopy(spec)
    for c in out.capabilities:
        if c.type == "booking" and c.capacity.mode == "fixed":
            c.capacity.value = value
    return out


def iso_in(h: Harness, hours: float) -> str:
    return to_utc_iso(h.now + timedelta(hours=hours))


async def seed_item(h: Harness, title: str = "کارگاه عکاسی", hours: float = 48, **extra: Any) -> int:
    data = {"title": title, "description": "توضیح", "teacher": "مریم احمدی", "starts_at": iso_in(h, hours)}
    data.update(extra)
    return await h.seed(RES, data)


def find(resp: RuntimeResponse, action: str, arg: str | int | None = None, msg: int = -1) -> Button:
    """Button of message ``msg`` whose parsed callback has ``action`` (and ``arg`` if given)."""
    for row in resp.messages[msg].buttons:
        for b in row:
            _, act, a = parse_callback(b.data)
            if act == action and (arg is None or a == str(arg)):
                return b
    raise AssertionError(f"no {action}:{arg} button; have {button_data(resp, msg)}")


def has(resp: RuntimeResponse, action: str, arg: str | int | None = None, msg: int = -1) -> bool:
    try:
        find(resp, action, arg, msg)
    except AssertionError:
        return False
    return True


def own_messages(resp: RuntimeResponse, actor: str) -> list[OutMessage]:
    return [m for m in resp.messages if m.to_actor_id == actor and m.notice is None]


def notices(resp: RuntimeResponse) -> list[tuple[str, str | None]]:
    return [(m.to_actor_id, m.notice) for m in resp.messages if m.notice is not None]


def outcome(resp: RuntimeResponse) -> Outcome:
    assert len(resp.outcomes) == 1, resp.outcomes
    return resp.outcomes[0]


def rejected(resp: RuntimeResponse, action: str, reason: str) -> bool:
    o = outcome(resp)
    return (o.action, o.result, o.reason) == (action, "rejected", reason)


async def open_item(h: Harness, actor: str, item_id: int) -> RuntimeResponse:
    r = await h.tap(actor, MENU_MAIN)
    return await h.tap(actor, find(r, "item", item_id).data)


async def book(h: Harness, actor: str, item_id: int) -> RuntimeResponse:
    """menu -> item -> book, like the scenario driver (no form)."""
    r = await open_item(h, actor, item_id)
    return await h.tap(actor, find(r, "book", item_id).data)


async def cancel_via_mine(h: Harness, actor: str, booking_id: int) -> RuntimeResponse:
    r = await h.tap(actor, MENU_MINE)
    return await h.tap(actor, find(r, "cancel", booking_id).data)


async def bookings(h: Harness, **kw: Any) -> list[Record]:
    return await h.store.list_records(CAP, **kw)


async def status_of(h: Harness, booking_id: int) -> str | None:
    rec = await h.store.get_record(CAP, booking_id)
    assert rec is not None
    return rec.status


async def counts(h: Harness, item_id: int) -> tuple[int, int]:
    c = await h.store.count_records(CAP, status_in=["confirmed"], item_id=item_id)
    w = await h.store.count_records(CAP, status_in=["waitlisted"], item_id=item_id)
    return c, w


async def book_ok(h: Harness, actor: str, item_id: int, expect: str = "confirmed") -> int:
    r = await book(h, actor, item_id)
    o = outcome(r)
    assert (o.action, o.result) == ("book", expect), o
    assert o.record_id is not None
    return o.record_id


# --- list and detail --------------------------------------------------------------------------


async def test_list_shows_upcoming_items_sorted_and_hides_started() -> None:
    h = Harness(booking_spec())
    later = await seed_item(h, "دیرتر", hours=72)
    started = await seed_item(h, "شروع‌شده", hours=-1)
    sooner = await seed_item(h, "زودتر", hours=24)
    r = await h.tap("ali", MENU_MAIN)
    assert text(r) == (
        "ثبت‌نام در کارگاه\nیکی از موارد زیر را انتخاب کنید:\n"
        "• زودتر (دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۱۱:۳۰)\n"
        "• دیرتر (چهارشنبه ۱۵ مهر ۱۴۰۵، ساعت ۱۱:۳۰)"
    )
    assert button_data(r) == [
        f"{CAP}:item:{sooner}",
        f"{CAP}:item:{later}",
        f"{CAP}:mine:",
        "nav:go:home",
    ]
    assert not has(r, "item", started)
    # list callback with a page arg renders the same list
    r2 = await h.tap("ali", f"{CAP}:list:0")
    assert button_data(r2) == button_data(r)


async def test_list_empty_and_pagination() -> None:
    h = Harness(booking_spec())
    r = await h.tap("ali", MENU_MAIN)
    assert text(r) == "ثبت‌نام در کارگاه\nدر حال حاضر موردی برای ثبت‌نام وجود ندارد."
    ids = [await seed_item(h, f"کارگاه {i}", hours=24 + i) for i in range(10)]
    r = await h.tap("ali", MENU_MAIN)
    assert [parse_callback(d)[2] for d in button_data(r) if ":item:" in d] == [str(i) for i in ids[:8]]
    r = await h.tap("ali", find(r, "list", 1).data)
    assert "صفحهٔ ۲ از ۲" in text(r)
    assert [parse_callback(d)[2] for d in button_data(r) if ":item:" in d] == [str(i) for i in ids[8:]]


async def test_item_detail_buttons_remaining_waitlist_and_own_status() -> None:
    h = Harness(booking_spec(capacity=1))
    w = await seed_item(h, price=1500000)
    r = await open_item(h, "ali", w)
    t = text(r)
    assert t.startswith("کارگاه عکاسی\n\nتوضیحات: توضیح\nمدرس: مریم احمدی\nزمان شروع: ")
    assert "هزینه (تومان): ۱٬۵۰۰٬۰۰۰" in t
    assert "ظرفیت باقی‌مانده: ۱" in t and "تعداد در لیست انتظار: ۰" in t
    assert button_data(r) == [f"{CAP}:book:{w}", f"{CAP}:list:0", "nav:go:home"]

    b_ali = await book_ok(h, "ali", w)
    r = await open_item(h, "ali", w)
    assert "ظرفیت باقی‌مانده: ۰" in text(r) and "وضعیت شما: قطعی" in text(r)
    assert button_data(r)[:2] == [f"{CAP}:book:{w}", f"{CAP}:cancel:{b_ali}"]

    b_sara = await book_ok(h, "sara", w, "waitlisted")
    r = await open_item(h, "sara", w)
    assert "تعداد در لیست انتظار: ۱" in text(r) and "وضعیت شما: در لیست انتظار (نفر ۱)" in text(r)
    assert has(r, "book", w) and has(r, "cancel", b_sara) and not has(r, "cancel", b_ali)


async def test_item_detail_without_waitlist_has_no_waitlist_line() -> None:
    h = Harness(booking_spec(waitlist={"enabled": False}))
    w = await seed_item(h)
    r = await open_item(h, "ali", w)
    assert "لیست انتظار" not in text(r)


async def test_item_stale_and_started_item_detail_still_offers_book() -> None:
    h = Harness(booking_spec())
    r = await h.tap("ali", f"{CAP}:item:999")
    assert text(r) == nav_texts.STALE
    started = await seed_item(h, hours=-2)
    r = await h.tap("ali", f"{CAP}:item:{started}")
    assert has(r, "book", started) and tx.CLOSED_LINE in text(r)
    r = await h.tap("ali", find(r, "book", started).data)
    assert rejected(r, "book", "booking_closed")


# --- booking ----------------------------------------------------------------------------------


async def test_book_confirmed_creates_record_and_notifies_owner() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    r = await book(h, "ali", w)
    o = outcome(r)
    assert o.model_dump() == {
        "capability": CAP, "action": "book", "result": "confirmed", "reason": None, "record_id": o.record_id,
    }  # fmt: skip
    rec = await h.store.get_record(CAP, o.record_id or 0)
    assert rec is not None
    assert (rec.item_id, rec.actor_id, rec.status, rec.data) == (w, "ali", "confirmed", {})
    mine = own_messages(r, "ali")
    assert mine[0].text == "ثبت‌نام شما در «کارگاه عکاسی» قطعی شد." and mine[0].edit is True
    assert has(r, "mine", msg=r.messages.index(mine[0]))
    assert notices(r) == [("owner", "booked")]
    owner_msg = next(m for m in r.messages if m.to_actor_id == "owner")
    assert owner_msg.text == "ثبت‌نام جدید: ali در «کارگاه عکاسی» ثبت‌نام کرد."
    assert [(e.kind, e.status) for e in r.effects] == [
        ("record_created", "confirmed"),
        ("notification", None),
    ]


async def test_capacity_then_waitlist_positions_and_owner_notices() -> None:
    h = Harness(booking_spec(notify_owner_on=["booked", "waitlisted"]))
    w = await seed_item(h)
    await book_ok(h, "ali", w)
    await book_ok(h, "sara", w)
    r = await book(h, "reza", w)
    assert (outcome(r).result, outcome(r).reason) == ("waitlisted", None)
    assert own_messages(r, "reza")[0].text == (
        "ظرفیت «کارگاه عکاسی» تکمیل است؛ شما در لیست انتظار قرار گرفتید (نفر ۱)."
    )
    assert notices(r) == [("owner", "waitlisted")]
    r = await book(h, "nima", w)
    assert outcome(r).result == "waitlisted" and "(نفر ۲)" in own_messages(r, "nima")[0].text
    assert await counts(h, w) == (2, 2)


async def test_waitlisted_booking_does_not_send_booked_notice() -> None:
    h = Harness(booking_spec(capacity=1))  # notify_owner_on = booked, cancelled
    w = await seed_item(h)
    await book_ok(h, "ali", w)
    r = await book(h, "sara", w)
    assert outcome(r).result == "waitlisted" and notices(r) == []


async def test_capacity_full_without_waitlist_rejected_but_book_button_kept() -> None:
    h = Harness(booking_spec(capacity=1, waitlist={"enabled": False}))
    w = await seed_item(h)
    await book_ok(h, "ali", w)
    r = await open_item(h, "sara", w)
    assert "ظرفیت باقی‌مانده: ۰" in text(r) and has(r, "book", w)
    r = await h.tap("sara", find(r, "book", w).data)
    assert rejected(r, "book", "capacity_full")
    assert text(r) == "متأسفانه ظرفیت «کارگاه عکاسی» تکمیل است."
    assert has(r, "item", w) and notices(r) == []
    assert await counts(h, w) == (1, 0)


async def test_duplicate_rejected_for_confirmed_and_waitlisted() -> None:
    h = Harness(booking_spec(capacity=1))
    w = await seed_item(h)
    await book_ok(h, "ali", w)
    r = await book(h, "ali", w)
    assert rejected(r, "book", "duplicate") and text(r) == "شما قبلاً در «کارگاه عکاسی» ثبت‌نام کرده‌اید."
    assert has(r, "mine")
    await book_ok(h, "sara", w, "waitlisted")
    assert rejected(await book(h, "sara", w), "book", "duplicate")
    assert len(await bookings(h)) == 2


async def test_duplicate_allowed_when_not_one_active_per_item() -> None:
    h = Harness(booking_spec(capacity=1, one_active_per_user_per_item=False))
    w = await seed_item(h)
    await book_ok(h, "ali", w)
    await book_ok(h, "ali", w, "waitlisted")


async def test_rebook_after_cancel_is_not_duplicate() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    await cancel_via_mine(h, "ali", b)
    await book_ok(h, "ali", w)


async def test_user_limit_counts_active_bookings_across_items() -> None:
    h = Harness(booking_spec(max_active_per_user=2))
    items = [await seed_item(h, f"کارگاه {i}", hours=24 + i) for i in range(4)]
    first = await book_ok(h, "ali", items[0])
    await book_ok(h, "ali", items[1])
    r = await book(h, "ali", items[2])
    assert rejected(r, "book", "user_limit")
    assert text(r) == "شما به سقف ۲ ثبت‌نام فعال رسیده‌اید و ثبت‌نام جدید ممکن نیست."
    await book_ok(h, "sara", items[2])  # per user
    await cancel_via_mine(h, "ali", first)
    await book_ok(h, "ali", items[2])  # cancelled bookings do not count


async def test_user_limit_counts_waitlisted_and_duplicate_checked_first() -> None:
    h = Harness(booking_spec(capacity=1, max_active_per_user=1))
    a = await seed_item(h, "الف", hours=24)
    b = await seed_item(h, "ب", hours=30)
    await book_ok(h, "sara", a)
    await book_ok(h, "ali", a, "waitlisted")
    assert rejected(await book(h, "ali", a), "book", "duplicate")
    assert rejected(await book(h, "ali", b), "book", "user_limit")


async def test_book_unknown_or_malformed_item_is_not_found() -> None:
    h = Harness(booking_spec())
    for data in (f"{CAP}:book:999", f"{CAP}:book:abc", f"{CAP}:book:"):
        r = await h.tap("ali", data)
        assert rejected(r, "book", "not_found") and text(r) == tx.ITEM_NOT_FOUND
    assert await bookings(h) == []


async def test_booking_cutoff_boundary() -> None:
    h = Harness(booking_spec(closes_hours_before_start=24))
    w = await seed_item(h, hours=48)
    h.advance(24)  # exactly at the cutoff: still open
    await book_ok(h, "ali", w)
    h.advance(1 / 3600)
    r = await book(h, "sara", w)  # item still listed (not started), booking refused
    assert (
        rejected(r, "book", "booking_closed")
        and text(r) == "مهلت ثبت‌نام در «کارگاه عکاسی» به پایان رسیده است."
    )


async def test_started_item_closed_without_cutoff() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h, hours=2)
    h.advance(2)  # exactly at start: still bookable and listed
    await book_ok(h, "ali", w)
    h.advance(1 / 60)
    r = await h.tap("sara", MENU_MAIN)
    assert not has(r, "item", w)
    r = await h.tap("sara", f"{CAP}:book:{w}")
    assert rejected(r, "book", "booking_closed")


async def test_closed_checked_before_duplicate() -> None:
    h = Harness(booking_spec(closes_hours_before_start=1))
    w = await seed_item(h, hours=5)
    await book_ok(h, "ali", w)
    h.advance(4.5)
    assert rejected(await h.tap("ali", f"{CAP}:book:{w}"), "book", "booking_closed")


async def test_per_item_capacity() -> None:
    spec = booking_spec(capacity={"mode": "per_item", "value": None, "field": "seats"}, seats_field=True)
    h = Harness(spec)
    one = await seed_item(h, "یک‌نفره", seats=1)
    three = await seed_item(h, "سه‌نفره", hours=50, seats=3)
    await book_ok(h, "ali", one)
    await book_ok(h, "sara", one, "waitlisted")
    for actor in ("ali", "sara", "reza"):
        await book_ok(h, actor, three)
    await book_ok(h, "nima", three, "waitlisted")
    r = await open_item(h, "omid", three)
    assert "ظرفیت باقی‌مانده: ۰" in text(r)


async def test_per_item_capacity_missing_or_non_positive_is_zero() -> None:
    spec = booking_spec(
        capacity={"mode": "per_item", "value": None, "field": "seats"},
        seats_field=True,
        waitlist={"enabled": False},
    )
    h = Harness(spec)
    missing = await seed_item(h, "بدون ظرفیت")
    zero = await seed_item(h, "صفر", seats=0)
    negative = await seed_item(h, "منفی", seats=-3)
    text_seats = await seed_item(h, "متنی", seats="۲")
    for w in (missing, zero, negative):
        assert rejected(await book(h, "ali", w), "book", "capacity_full")
    await book_ok(h, "ali", text_seats)  # digit strings are tolerated


async def test_capacity_lowered_below_confirmed_count() -> None:
    h = Harness(booking_spec(capacity=3))
    w = await seed_item(h)
    ids = [await book_ok(h, a, w) for a in ("ali", "sara", "reza")]
    wait = await book_ok(h, "nima", w, "waitlisted")
    h.spec = with_capacity(h.spec, 1)  # owner lowers capacity: existing bookings stay
    assert await counts(h, w) == (3, 1)
    await book_ok(h, "omid", w, "waitlisted")  # no new confirmations
    r = await cancel_via_mine(h, "ali", ids[0])
    assert outcome(r).result == "cancelled" and await counts(h, w) == (2, 2)
    await cancel_via_mine(h, "sara", ids[1])
    assert await counts(h, w) == (1, 2)  # 1 confirmed == capacity 1: still nobody promoted
    r = await cancel_via_mine(h, "reza", ids[2])
    assert await counts(h, w) == (1, 1) and await status_of(h, wait) == "confirmed"
    assert notices(r) == [("owner", "cancelled"), ("nima", "promoted")]


# --- form flow --------------------------------------------------------------------------------

FORM_FIELDS = [
    {"key": "phone", "label": "شماره تماس", "type": "phone"},
    {"key": "level", "label": "سطح", "type": "choice", "choices": ["مبتدی", "پیشرفته"]},
]


async def test_form_flow_collects_values_then_books() -> None:
    h = Harness(booking_spec(form_fields=FORM_FIELDS))
    w = await seed_item(h)
    r = await book(h, "ali", w)
    assert r.outcomes == [] and await bookings(h) == []
    assert text(r).startswith("ثبت‌نام در «کارگاه عکاسی»\nلطفاً «شماره تماس» را وارد کنید:")
    assert has(r, "stop")
    session = await h.store.get_session("ali")
    assert session is not None and session["vars"]["data"] == {"item_id": w}
    r = await h.send("ali", "۰۹۱۲۱۲۳۴۵۶۷")
    assert "«سطح»" in text(r)
    r = await h.tap("ali", find(r, "ans", 1).data)
    o = outcome(r)
    assert (o.action, o.result) == ("book", "confirmed")
    rec = await h.store.get_record(CAP, o.record_id or 0)
    assert rec is not None and rec.data == {"phone": "09121234567", "level": "پیشرفته"}
    assert rec.item_id == w and rec.actor_id == "ali"
    assert await h.store.get_session("ali") is None
    assert notices(r) == [("owner", "booked")]


async def test_form_invalid_answer_reasked_and_stop_books_nothing() -> None:
    h = Harness(booking_spec(form_fields=FORM_FIELDS))
    w = await seed_item(h)
    await book(h, "ali", w)
    r = await h.send("ali", "abc")
    assert text(r).startswith("پاسخ «شماره تماس» پذیرفته نشد:")
    r = await h.tap("ali", find(r, "stop").data)
    assert text(r) == "فرم لغو شد." and await bookings(h) == [] and r.outcomes == []


async def test_form_rejection_before_form_starts() -> None:
    h = Harness(booking_spec(capacity=1, waitlist={"enabled": False}, form_fields=FORM_FIELDS))
    w = await seed_item(h)
    await h.store.create_record(CAP, {}, status="confirmed", actor_id="sara", item_id=w, now=h.now)
    r = await book(h, "ali", w)
    assert rejected(r, "book", "capacity_full") and await h.store.get_session("ali") is None


async def test_form_rechecks_when_last_seat_taken_meanwhile() -> None:
    h = Harness(booking_spec(capacity=1, waitlist={"enabled": False}, form_fields=FORM_FIELDS))
    w = await seed_item(h)
    await book(h, "ali", w)  # ali starts the form while a seat is free
    await h.send("ali", "09121234567")
    await book(h, "sara", w)  # sara completes first and takes the last seat
    r = await h.send("sara", "09127654321")
    r = await h.tap("sara", find(r, "ans", 0).data)
    assert outcome(r).result == "confirmed"
    r = await h.tap("ali", f"{CAP}:ans:0")
    assert rejected(r, "book", "capacity_full")
    assert await counts(h, w) == (1, 0)


async def test_form_recheck_waitlists_when_seat_taken_meanwhile() -> None:
    h = Harness(booking_spec(capacity=1, form_fields=FORM_FIELDS))
    w = await seed_item(h)
    await book(h, "ali", w)
    await book(h, "sara", w)
    for actor in ("sara", "ali"):
        await h.send(actor, "09121234567")
    assert outcome(await h.tap("sara", f"{CAP}:ans:0")).result == "confirmed"
    assert outcome(await h.tap("ali", f"{CAP}:ans:1")).result == "waitlisted"


async def test_form_recheck_closed_and_deleted_item() -> None:
    h = Harness(booking_spec(closes_hours_before_start=24, form_fields=FORM_FIELDS))
    w = await seed_item(h, hours=25)
    gone = await seed_item(h, "حذف‌شده", hours=40)
    await book(h, "ali", w)
    await h.send("ali", "09121234567")
    h.advance(2)
    assert rejected(await h.tap("ali", f"{CAP}:ans:0"), "book", "booking_closed")
    await book(h, "sara", gone)
    await h.send("sara", "09121234567")
    await h.store.delete_record(RES, gone)
    assert rejected(await h.tap("sara", f"{CAP}:ans:0"), "book", "not_found")
    assert await bookings(h) == []


# --- my bookings ------------------------------------------------------------------------------


async def test_mine_view_lists_active_bookings_with_cancel_buttons() -> None:
    h = Harness(booking_spec(capacity=1))
    a = await seed_item(h, "الف", hours=24)  # 2026-10-05 08:00 UTC = 11:30 Tehran
    b = await seed_item(h, "ب", hours=30)
    c = await seed_item(h, "ج", hours=36)
    r = await h.tap("ali", MENU_MINE)
    assert text(r) == "شما در حال حاضر ثبت‌نام فعالی ندارید." and has(r, "list", 0)
    await book_ok(h, "sara", b)
    ba = await book_ok(h, "ali", a)
    bb = await book_ok(h, "ali", b, "waitlisted")
    bc = await book_ok(h, "ali", c)
    await cancel_via_mine(h, "ali", bc)
    r = await h.tap("ali", MENU_MINE)
    assert text(r) == (
        "ثبت‌نام‌های فعال شما:\n"
        "• الف (دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۱۱:۳۰) — قطعی\n"
        "• ب (دوشنبه ۱۳ مهر ۱۴۰۵، ساعت ۱۷:۳۰) — در لیست انتظار (نفر ۱)"
    )
    assert button_data(r) == [f"{CAP}:cancel:{ba}", f"{CAP}:cancel:{bb}", f"{CAP}:list:0", "nav:go:home"]
    r2 = await h.tap("ali", f"{CAP}:mine:")
    assert text(r2) == text(r)


# --- cancellation -----------------------------------------------------------------------------


async def test_user_cancel_notifies_owner_and_frees_seat() -> None:
    h = Harness(booking_spec(capacity=1, waitlist={"enabled": False}))
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    r = await cancel_via_mine(h, "ali", b)
    o = outcome(r)
    assert (o.action, o.result, o.record_id) == ("cancel", "cancelled", b)
    assert own_messages(r, "ali")[0].text == "ثبت‌نام شما در «کارگاه عکاسی» لغو شد."
    assert notices(r) == [("owner", "cancelled")]
    owner_msg = next(m for m in r.messages if m.to_actor_id == "owner")
    assert owner_msg.text == "ali ثبت‌نام خود در «کارگاه عکاسی» را لغو کرد."
    assert await status_of(h, b) == "cancelled"
    await book_ok(h, "sara", w)


async def test_cancel_from_item_detail() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    r = await open_item(h, "ali", w)
    r = await h.tap("ali", find(r, "cancel", b).data)
    assert outcome(r).result == "cancelled"


async def test_cancel_stale_foreign_or_unknown_is_not_found() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    stale = await h.tap("ali", f"{CAP}:cancel:{b}")
    assert outcome(stale).result == "cancelled"
    again = await h.tap("ali", f"{CAP}:cancel:{b}")  # double tap / stale button
    assert rejected(again, "cancel", "not_found") and text(again) == tx.BOOKING_NOT_FOUND
    b2 = await book_ok(h, "ali", w)
    assert rejected(await h.tap("sara", f"{CAP}:cancel:{b2}"), "cancel", "not_found")
    assert rejected(await h.tap("ali", f"{CAP}:cancel:{w}"), "cancel", "not_found")  # an item id
    assert rejected(await h.tap("ali", f"{CAP}:cancel:999"), "cancel", "not_found")
    assert rejected(await h.tap("ali", f"{CAP}:cancel:x"), "cancel", "not_found")
    assert await status_of(h, b2) == "confirmed"


async def test_cancellation_disabled_keeps_cancel_button() -> None:
    h = Harness(booking_spec(cancellation={"enabled": False}))
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    r = await open_item(h, "ali", w)
    assert has(r, "cancel", b)
    r = await cancel_via_mine(h, "ali", b)
    assert rejected(r, "cancel", "cancellation_disabled")
    assert text(r) == "امکان لغو ثبت‌نام «کارگاه عکاسی» وجود ندارد." and notices(r) == []
    assert await status_of(h, b) == "confirmed"


async def test_cancel_deadline_boundary() -> None:
    h = Harness(booking_spec(cancellation={"deadline_hours": 24}))
    w = await seed_item(h, hours=48)
    ali = await book_ok(h, "ali", w)
    sara = await book_ok(h, "sara", w)
    h.advance(24)  # exactly start - 24h: still allowed
    assert outcome(await cancel_via_mine(h, "ali", ali)).result == "cancelled"
    h.advance(1 / 3600)
    r = await cancel_via_mine(h, "sara", sara)  # the cancel button is still offered
    assert rejected(r, "cancel", "cancel_deadline_passed")
    assert text(r) == "لغو ثبت‌نام «کارگاه عکاسی» فقط تا ۲۴ ساعت پیش از شروع ممکن است و این مهلت گذشته است."
    assert await status_of(h, sara) == "confirmed"


async def test_cancel_without_deadline_allowed_after_start() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h, hours=1)
    b = await book_ok(h, "ali", w)
    h.advance(3)
    assert outcome(await cancel_via_mine(h, "ali", b)).result == "cancelled"


# --- promotion --------------------------------------------------------------------------------


async def test_promotion_order_three_waitlisted() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    ali = await book_ok(h, "ali", w)
    sara = await book_ok(h, "sara", w)
    reza, nima, omid = [await book_ok(h, a, w, "waitlisted") for a in ("reza", "nima", "omid")]
    r = await cancel_via_mine(h, "ali", ali)
    assert notices(r) == [("owner", "cancelled"), ("reza", "promoted")]
    promo = next(m for m in r.messages if m.notice == "promoted")
    assert promo.text == "خبر خوب! از لیست انتظار خارج شدید و ثبت‌نام شما در «کارگاه عکاسی» قطعی شد."
    assert has(r, "mine", msg=r.messages.index(promo))
    assert [await status_of(h, i) for i in (reza, nima, omid)] == ["confirmed", "waitlisted", "waitlisted"]
    r = await cancel_via_mine(h, "sara", sara)
    assert ("nima", "promoted") in notices(r)
    assert [await status_of(h, i) for i in (nima, omid)] == ["confirmed", "waitlisted"]
    r = await open_item(h, "omid", w)
    assert "در لیست انتظار (نفر ۱)" in text(r)
    assert await counts(h, w) == (2, 1)


async def test_waitlisted_cancel_promotes_nobody() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    await book_ok(h, "ali", w)
    await book_ok(h, "sara", w)
    reza = await book_ok(h, "reza", w, "waitlisted")
    nima = await book_ok(h, "nima", w, "waitlisted")
    r = await cancel_via_mine(h, "reza", reza)
    assert outcome(r).result == "cancelled" and ("nima", "promoted") not in notices(r)
    assert await status_of(h, nima) == "waitlisted" and await counts(h, w) == (2, 1)


async def test_auto_promote_off_promotes_nobody() -> None:
    h = Harness(booking_spec(waitlist={"enabled": True, "auto_promote": False}))
    w = await seed_item(h)
    ali = await book_ok(h, "ali", w)
    await book_ok(h, "sara", w)
    reza = await book_ok(h, "reza", w, "waitlisted")
    r = await cancel_via_mine(h, "ali", ali)
    assert notices(r) == [("owner", "cancelled")]
    assert await status_of(h, reza) == "waitlisted" and await counts(h, w) == (1, 1)


async def test_promotion_without_user_notice() -> None:
    h = Harness(booking_spec(capacity=1, notify_user_on=[], notify_owner_on=[]))
    w = await seed_item(h)
    ali = await book_ok(h, "ali", w)
    sara = await book_ok(h, "sara", w, "waitlisted")
    r = await cancel_via_mine(h, "ali", ali)
    assert notices(r) == [] and await status_of(h, sara) == "confirmed"


async def test_promoting_the_canceller_own_waitlisted_booking_replies_instead_of_notice() -> None:
    h = Harness(booking_spec(capacity=1, one_active_per_user_per_item=False))
    w = await seed_item(h)
    first = await book_ok(h, "ali", w)
    second = await book_ok(h, "ali", w, "waitlisted")
    r = await cancel_via_mine(h, "ali", first)
    assert await status_of(h, second) == "confirmed"
    assert all(m.notice != "promoted" for m in r.messages)
    assert [m.edit for m in own_messages(r, "ali")] == [True, False]


async def test_no_owner_linked_skips_owner_notices() -> None:
    h = Harness(booking_spec(), store=MemoryStore(owner_actor_id=None))
    w = await seed_item(h)
    r = await book(h, "ali", w)
    assert outcome(r).result == "confirmed" and notices(r) == []


# --- owner cancel -----------------------------------------------------------------------------


async def test_owner_cancel_via_admin_ignores_deadline_and_promotes() -> None:
    h = Harness(booking_spec(cancellation={"enabled": False, "deadline_hours": 24}))
    w = await seed_item(h, hours=10)  # already inside the deadline
    ali = await book_ok(h, "ali", w)
    await book_ok(h, "sara", w)
    reza = await book_ok(h, "reza", w, "waitlisted")
    assert rejected(await cancel_via_mine(h, "ali", ali), "cancel", "cancellation_disabled")
    r = await h.admin(f"{CAP}:cancel:{ali}")
    o = outcome(r)
    assert (o.capability, o.action, o.result, o.record_id) == (CAP, "cancel", "cancelled", ali)
    assert notices(r) == [("ali", "cancelled"), ("reza", "promoted")]
    assert (
        next(m for m in r.messages if m.to_actor_id == "ali").text == "ثبت‌نام شما در «کارگاه عکاسی» لغو شد."
    )
    assert own_messages(r, "owner")[0].text == "ثبت‌نام کاربر ali در «کارگاه عکاسی» لغو شد."
    assert await status_of(h, ali) == "cancelled" and await status_of(h, reza) == "confirmed"


async def test_owner_cancel_inactive_or_unknown_is_not_found() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    assert outcome(await h.admin(f"{CAP}:cancel:{b}")).result == "cancelled"
    r = await h.admin(f"{CAP}:cancel:{b}")
    assert rejected(r, "cancel", "not_found") and notices(r) == []
    assert rejected(await h.admin(f"{CAP}:cancel:999"), "cancel", "not_found")
    assert rejected(await h.admin(f"{CAP}:cancel:{w}"), "cancel", "not_found")  # an item, not a booking


async def test_non_owner_admin_rejected() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    r = await h.admin(f"{CAP}:cancel:{b}", actor="sara")
    assert rejected(r, "cancel", "not_allowed")
    assert await status_of(h, b) == "confirmed"


async def test_owner_action_other_than_cancel_not_allowed() -> None:
    spec = booking_spec()
    h = Harness(spec)
    w = await seed_item(h)
    b = await book_ok(h, "ali", w)
    cap = spec.capability(CAP)
    ev = RuntimeEvent(
        bot_id="b1", env="sandbox", actor=Harness.actor("owner"), kind="admin", data="x", now=T0
    )
    ctx = await Ctx.create(ev, spec, h.store)
    await get_engine("booking").owner_action(ctx, cap, b, "approve")
    o = ctx.response().outcomes[0]
    assert (o.action, o.result, o.reason) == ("owner_action", "rejected", "not_allowed")
    assert await status_of(h, b) == "confirmed"


async def test_owner_as_customer_gets_no_owner_notice() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    r = await book(h, "owner", w)
    assert outcome(r).result == "confirmed" and notices(r) == []


# --- texts ------------------------------------------------------------------------------------


async def test_text_overrides_from_cap_texts() -> None:
    h = Harness(
        booking_spec(
            capacity=1,
            texts=[
                {"key": "confirmed", "value": "تبریک! جای شما در {title} محفوظ است."},
                {"key": "waitlisted", "value": "نوبت شما: {position}"},
                {"key": "item_detail", "value": "{title} | {remaining}"},
                {"key": "owner_booked", "value": "{user} → {title}"},
            ],
        )
    )
    w = await seed_item(h)
    r = await book(h, "ali", w)
    assert own_messages(r, "ali")[0].text == "تبریک! جای شما در کارگاه عکاسی محفوظ است."
    assert next(m for m in r.messages if m.to_actor_id == "owner").text == "ali → کارگاه عکاسی"
    r = await book(h, "sara", w)
    assert own_messages(r, "sara")[0].text == "نوبت شما: ۱"
    r = await open_item(h, "reza", w)
    assert text(r).startswith("کارگاه عکاسی | ۰")


async def test_display_name_used_in_owner_notice() -> None:
    h = Harness(booking_spec())
    w = await seed_item(h)
    ali = Actor(id="ali", display_name="علی رضایی")
    r = await h.tap(ali, MENU_MAIN)
    r = await h.tap(ali, find(r, "item", w).data)
    r = await h.tap(ali, find(r, "book", w).data)
    assert next(m for m in r.messages if m.to_actor_id == "owner").text == (
        "ثبت‌نام جدید: علی رضایی در «کارگاه عکاسی» ثبت‌نام کرد."
    )


async def test_capacity_raised_then_cancel_fills_every_free_seat_in_order() -> None:
    h = Harness(booking_spec(capacity=1))
    w = await seed_item(h)
    ali = await book_ok(h, "ali", w)
    sara, reza, nima = [await book_ok(h, a, w, "waitlisted") for a in ("sara", "reza", "nima")]
    h.spec = with_capacity(h.spec, 3)  # raising capacity alone promotes nobody (no event)
    assert await counts(h, w) == (1, 3)
    r = await cancel_via_mine(h, "ali", ali)
    # confirmed 0 < 3: waitlisted bookings are confirmed oldest first until the capacity is met
    assert [n[0] for n in notices(r) if n[1] == "promoted"] == ["sara", "reza", "nima"]
    assert [await status_of(h, i) for i in (sara, reza, nima)] == ["confirmed"] * 3
    assert await counts(h, w) == (3, 0)
