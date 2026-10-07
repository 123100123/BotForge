"""Events preset of the booking engine (W1-EVT): wording, category filter, subscriptions, RSVP,
group context, the group card, and that the plain booking preset is untouched."""

from datetime import timedelta
from typing import Any

from app.botspec.models import BotSpec
from app.botspec.records import to_utc_iso
from app.botspec.validate import validate_spec
from app.runtime.callbacks import parse_callback
from app.runtime.contracts import RuntimeEvent, RuntimeResponse
from app.runtime.engines.booking import render_group_card
from app.runtime.store import Record
from app.runtime.texts import booking as tx
from app.testing import events_derive  # noqa: F401  (registers the events templates)
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from tests.unit.runtime.harness import T0, Harness, buttons, find_button, load_example, text
from tests.unit.runtime.test_booking import (
    CAP as WORKSHOP_CAP,
)
from tests.unit.runtime.test_booking import (
    booking_spec,
    seed_item,
)

CAP = "events"
SUBS = "events.subs"
CATS = ["موسیقی", "فناوری", "ورزش"]
MENU_MAIN = "menu:open:events_menu"
MENU_MINE = "menu:open:my_events"


def events_spec(*, preset: str = "events", **cap: Any) -> BotSpec:
    data: dict[str, Any] = {
        "bot": {"name": "رویدادها", "welcome_text": "سلام"},
        "resources": [
            {
                "key": "event",
                "label": "رویداد",
                "label_plural": "رویدادها",
                "title_field": "title",
                "fields": [
                    {"key": "title", "label": "عنوان", "type": "text"},
                    {"key": "category", "label": "دسته", "type": "choice", "choices": CATS},
                    {"key": "starts_at", "label": "زمان شروع", "type": "datetime"},
                    {"key": "location", "label": "مکان", "type": "text", "required": False},
                    {"key": "capacity", "label": "ظرفیت", "type": "integer"},
                ],
            }
        ],
        "capabilities": [
            {
                "type": "booking",
                "key": CAP,
                "title": "رویدادها",
                "resource": "event",
                "capacity": {"mode": "per_item", "value": None, "field": "capacity"},
                "start_field": "starts_at",
                "detail_fields": ["location"],
                "preset": preset,
                "category_field": "category",
                "waitlist": {"enabled": True, "auto_promote": True},
                **cap,
            }
        ],
        "menu": [
            {"key": "events_menu", "label": "رویدادها", "capability": CAP, "view": "main"},
            {"key": "my_events", "label": "ثبت‌نام‌های من", "capability": CAP, "view": "mine"},
        ],
    }
    spec = BotSpec.model_validate(data)
    errors = [i for i in validate_spec(spec) if i.severity == "error"]
    assert not errors, errors
    return spec


async def seed_event(
    h: Harness, title: str, category: str, hours: float, capacity: int = 10, location: str = "تهران"
) -> int:
    return await h.seed(
        "event",
        {
            "title": title,
            "category": category,
            "starts_at": to_utc_iso(h.now + timedelta(hours=hours)),
            "location": location,
            "capacity": capacity,
        },
    )


def labels(resp: RuntimeResponse, msg: int = -1) -> list[str]:
    return [b.label for b in buttons(resp, msg)]


def datas(resp: RuntimeResponse, msg: int = -1) -> list[str]:
    return [b.data for b in buttons(resp, msg)]


async def group_tap(h: Harness, actor: str, data: str) -> RuntimeResponse:
    ev = RuntimeEvent(
        bot_id="b1",
        env="sandbox",
        actor=h.actor(actor),
        kind="callback",
        data=data,
        now=h.now,
        chat_type="group",
    )
    return await h.runtime.handle(ev, h.spec, h.store)


# --- list wording and category filter --------------------------------------------------------


async def test_list_shows_upcoming_sorted_with_category_and_attendance() -> None:
    h = Harness(events_spec())
    late = await seed_event(h, "کنسرت بزرگ", CATS[0], 72, capacity=50)
    soon = await seed_event(h, "همایش وب", CATS[1], 24, capacity=10)
    await seed_event(h, "رویداد گذشته", CATS[2], -5)
    await h.store.create_record(CAP, {}, status="confirmed", actor_id="u1", item_id=soon, now=h.now)

    resp = await h.tap("ali", MENU_MAIN)
    body = text(resp)
    assert "رویدادهای پیش‌رو" in body
    assert "رویداد گذشته" not in body
    assert body.index("همایش وب") < body.index("کنسرت بزرگ")  # sorted by start
    assert CATS[1] in body and CATS[0] in body
    assert "۱ / ۱۰" in body and "۰ / ۵۰" in body  # going/capacity
    assert "۱۴۰۵" in body  # Jalali date
    assert f"{CAP}:item:{soon}" in datas(resp) and f"{CAP}:item:{late}" in datas(resp)
    assert f"{CAP}:list:sub" in datas(resp)
    assert tx.EVENTS_SUBS_BUTTON in labels(resp)
    assert any(d == CAP + ":mine:" for d in datas(resp))


async def test_category_filter_buttons_and_filtering() -> None:
    h = Harness(events_spec())
    await seed_event(h, "کنسرت بزرگ", CATS[0], 72)
    await seed_event(h, "همایش وب", CATS[1], 24)
    await seed_event(h, "هکاتون", CATS[1], 48)

    resp = await h.tap("ali", MENU_MAIN)
    ds = datas(resp)
    assert f"{CAP}:list:0" in ds  # all
    assert all(f"{CAP}:list:c{i}.0" in ds for i in range(len(CATS)))
    assert tx.EVENTS_ALL_CATEGORIES in " ".join(labels(resp))

    filtered = await h.tap("ali", f"{CAP}:list:c1.0")
    body = text(filtered)
    assert "همایش وب" in body and "هکاتون" in body
    assert "کنسرت بزرگ" not in body
    assert "✓ " + CATS[1] in " ".join(labels(filtered))  # selected filter is marked

    empty = await h.tap("ali", f"{CAP}:list:c2.0")  # no sport events
    assert "همایش وب" not in text(empty)
    assert f"{CAP}:list:0" in datas(empty)  # the filter row is still there to switch back

    stale = await h.tap("ali", f"{CAP}:list:c9.0")  # unknown category index -> all
    assert "کنسرت بزرگ" in text(stale)


async def test_filtered_pagination_keeps_the_category() -> None:
    h = Harness(events_spec())
    for n in range(10):
        await seed_event(h, f"همایش {n}", CATS[1], 24 + n)
    resp = await h.tap("ali", f"{CAP}:list:c1.0")
    assert f"{CAP}:list:c1.1" in datas(resp)
    page2 = await h.tap("ali", f"{CAP}:list:c1.1")
    assert f"{CAP}:list:c1.0" in datas(page2)


async def test_empty_list_wording() -> None:
    h = Harness(events_spec())
    resp = await h.tap("ali", MENU_MAIN)
    assert "رویداد پیش‌رویی" in text(resp)


# --- subscriptions ---------------------------------------------------------------------------


async def subs_of(h: Harness, actor: str) -> list[Record]:
    return await h.store.list_records(SUBS, actor_id=actor)


async def test_subscription_toggle_creates_and_deletes_records() -> None:
    h = Harness(events_spec())
    view = await h.tap("ali", f"{CAP}:list:sub")
    assert [lb.split(" ", 1)[0] for lb in labels(view)[:3]] == [tx.EVENTS_SUB_OFF] * 3
    assert [d for d in datas(view) if ":list:sub." in d] == [f"{CAP}:list:sub.{i}" for i in range(3)]

    view = await h.tap("ali", f"{CAP}:list:sub.1")
    recs = await subs_of(h, "ali")
    assert [r.data for r in recs] == [{"category": CATS[1]}]
    assert labels(view)[1] == f"{tx.EVENTS_SUB_ON} {CATS[1]}"
    assert labels(view)[0] == f"{tx.EVENTS_SUB_OFF} {CATS[0]}"

    await h.tap("ali", f"{CAP}:list:sub.0")
    assert sorted(r.data["category"] for r in await subs_of(h, "ali")) == sorted([CATS[0], CATS[1]])
    assert await subs_of(h, "sara") == []  # per user

    view = await h.tap("ali", f"{CAP}:list:sub.1")  # toggle off
    assert [r.data["category"] for r in await subs_of(h, "ali")] == [CATS[0]]
    assert labels(view)[1] == f"{tx.EVENTS_SUB_OFF} {CATS[1]}"
    # subscription records live apart from the bookings
    assert await h.store.count_records(CAP) == 0


async def test_subscription_toggle_with_bad_index_changes_nothing() -> None:
    h = Harness(events_spec())
    resp = await h.tap("ali", f"{CAP}:list:sub.7")
    assert await subs_of(h, "ali") == []
    assert f"{CAP}:list:sub.0" in datas(resp)


async def test_no_subscription_ui_without_category_field() -> None:
    h = Harness(events_spec(category_field=None))
    await seed_event(h, "همایش وب", CATS[1], 24)
    resp = await h.tap("ali", MENU_MAIN)
    assert "همایش وب" in text(resp)
    assert not any(":list:sub" in d or ":list:c" in d for d in datas(resp))
    sub = await h.tap("ali", f"{CAP}:list:sub")  # falls back to the list
    assert "همایش وب" in text(sub)
    assert await subs_of(h, "ali") == []


# --- RSVP ------------------------------------------------------------------------------------


async def test_rsvp_flow_wording_and_mine() -> None:
    h = Harness(events_spec(cancellation={"enabled": True, "deadline_hours": None}))
    item = await seed_event(h, "همایش وب", CATS[1], 24, capacity=1, location="دانشگاه تهران")

    detail = await h.tap("ali", f"{CAP}:item:{item}")
    assert "دانشگاه تهران" in text(detail)  # location
    assert CATS[1] in text(detail)  # category shown without being in detail_fields
    assert "۱۴۰۵" in text(detail)  # start shown
    book_btn = find_button(detail, "شرکت می‌کنم")
    assert book_btn.data == f"{CAP}:book:{item}"

    done = await h.tap("ali", book_btn.data)
    assert "شرکت شما در «همایش وب» ثبت شد" in text(done, 0)
    assert "ثبت‌نام‌های من" in labels(done)

    waitlisted = await h.tap("sara", book_btn.data)
    assert "فهرست انتظار" in text(waitlisted)

    again = await h.tap("ali", f"{CAP}:item:{item}")
    assert "شرکت می‌کنید" in text(again)
    cancel_btn = find_button(again, "لغو شرکت")

    mine = await h.tap("ali", f"{CAP}:mine:")
    assert "ثبت‌نام‌های شما در رویدادها" in text(mine) and "همایش وب" in text(mine)
    mine_menu = await h.tap("ali", MENU_MINE)
    assert "همایش وب" in text(mine_menu)

    cancelled = await h.tap("ali", cancel_btn.data)
    assert "شرکت شما در «همایش وب» لغو شد" in text(cancelled, 0)
    promoted = [m for m in cancelled.messages if m.to_actor_id == "sara"]
    assert promoted and "قطعی شد" in promoted[0].text  # waitlist promotion, events wording
    assert "هیچ رویدادی" in text(await h.tap("ali", f"{CAP}:mine:"))


async def test_started_event_is_history_with_events_wording() -> None:
    h = Harness(events_spec(cancellation={"enabled": True, "deadline_hours": None}))
    past = await seed_event(h, "همایش وب", CATS[1], 1)
    upcoming = await seed_event(h, "کنسرت", CATS[0], 30)
    await h.tap("ali", f"{CAP}:book:{past}")
    await h.tap("ali", f"{CAP}:book:{upcoming}")
    h.advance(2)
    mine = await h.tap("ali", f"{CAP}:mine:")
    lines = text(mine).splitlines()
    assert any(line.startswith("• همایش وب") and line.endswith("— برگزار شده") for line in lines)
    assert any(line.startswith("• کنسرت") and line.endswith("— شرکت می‌کنید") for line in lines)
    cancel = next(b.data for b in buttons(mine) if b.label == "لغو شرکت: همایش وب")
    refused = await h.tap("ali", cancel)
    assert text(refused) == "رویداد «همایش وب» شروع شده است و دیگر نمی‌توان شرکت در آن را لغو کرد."
    outcome = refused.outcomes[-1]
    assert outcome.action == "cancel" and outcome.result == "rejected"
    assert outcome.reason == "cancel_deadline_passed"


async def test_text_override_precedence_in_events_preset() -> None:
    plain = {"key": "confirmed", "value": "ثبت شد: {title}"}
    events = {"key": "events_confirmed", "value": "رویداد {title} ثبت شد"}
    for overrides, expected in (([plain], "ثبت شد: همایش"), ([plain, events], "رویداد همایش ثبت شد")):
        h = Harness(events_spec(texts=overrides))
        item = await seed_event(h, "همایش", CATS[1], 24)
        assert text(await h.tap("ali", f"{CAP}:book:{item}")) == expected


# --- group context ---------------------------------------------------------------------------


async def test_group_book_answers_with_one_short_text() -> None:
    h = Harness(events_spec())
    item = await seed_event(h, "همایش وب", CATS[1], 24, capacity=1)

    resp = await group_tap(h, "ali", f"{CAP}:book:{item}")
    assert len(resp.messages) == 1
    msg = resp.messages[0]
    assert msg.buttons == [] and msg.edit is False
    assert "شرکت شما" in msg.text
    assert await h.store.count_records(CAP, status_in=["confirmed"], actor_id="ali", item_id=item) == 1
    assert [o.result for o in resp.outcomes] == ["confirmed"]

    dup = await group_tap(h, "ali", f"{CAP}:book:{item}")
    assert len(dup.messages) == 1 and dup.messages[0].buttons == [] and dup.messages[0].edit is False
    assert [o.reason for o in dup.outcomes] == ["duplicate"]

    wait = await group_tap(h, "sara", f"{CAP}:book:{item}")
    assert len(wait.messages) == 1 and "فهرست انتظار" in wait.messages[0].text

    missing = await group_tap(h, "sara", f"{CAP}:book:99999")
    assert len(missing.messages) == 1 and missing.messages[0].buttons == []


async def test_group_book_with_form_fields_redirects_to_private_chat() -> None:
    form = [{"key": "phone", "label": "تلفن", "type": "phone"}]
    h = Harness(events_spec(form_fields=form))
    item = await seed_event(h, "همایش وب", CATS[1], 24)
    resp = await group_tap(h, "ali", f"{CAP}:book:{item}")
    assert [m.text for m in resp.messages] == [tx.EVENTS_GROUP_PRIVATE]
    assert resp.messages[0].buttons == [] and resp.messages[0].edit is False
    assert await h.store.count_records(CAP) == 0
    assert await h.store.get_session("ali") is None  # no form started in the group


async def test_group_other_actions_get_the_same_text() -> None:
    h = Harness(events_spec())
    item = await seed_event(h, "همایش وب", CATS[1], 24)
    for data in (f"{CAP}:list:0", f"{CAP}:item:{item}", f"{CAP}:mine:", f"{CAP}:list:sub", f"{CAP}:cancel:1"):
        resp = await group_tap(h, "ali", data)
        assert [m.text for m in resp.messages] == [tx.EVENTS_GROUP_PRIVATE], data
        assert resp.messages[0].buttons == []
    assert await h.store.count_records(CAP) == 0 and await subs_of(h, "ali") == []


async def test_booking_preset_in_group_is_unchanged() -> None:
    h = Harness(booking_spec(capacity=2))
    item = await seed_item(h)
    resp = await group_tap(h, "ali", f"{WORKSHOP_CAP}:book:{item}")
    assert resp.messages[0].buttons  # the usual reply with navigation buttons
    assert tx.EVENTS_GROUP_PRIVATE not in [m.text for m in resp.messages]


# --- group card ------------------------------------------------------------------------------


def card_item(**data: Any) -> Record:
    base = {
        "title": "همایش وب",
        "category": CATS[1],
        "starts_at": "2026-10-10T14:30:00Z",
        "location": "دانشگاه تهران",
    }
    return Record(
        id=7,
        collection="event",
        data={**base, **data},
        status=None,
        actor_id=None,
        item_id=None,
        created_at=T0,
        updated_at=T0,
    )


def test_render_group_card_with_capacity() -> None:
    spec = events_spec()
    cap = spec.capabilities[0]
    h = Harness(spec)
    body, rows = render_group_card(cap, card_item(), 3, 10, now=h.now)  # type: ignore[arg-type]
    lines = body.split("\n")
    assert lines[0] == "📅 همایش وب"
    assert "۱۴۰۵" in lines[1] and "۱۸:۰۰" in lines[1]  # Tehran time (UTC+3:30)
    assert lines[2] == "📍 دانشگاه تهران"
    assert lines[3].endswith("۳ / ۱۰")
    assert len(rows) == 1 and len(rows[0]) == 1
    assert rows[0][0].label == "شرکت می‌کنم"
    assert parse_callback(rows[0][0].data) == (CAP, "book", "7")


def test_render_group_card_without_capacity_or_location() -> None:
    cap = events_spec().capabilities[0]
    item = card_item(location="")
    body, rows = render_group_card(cap, item, 5, None, now=Harness(events_spec()).now)  # type: ignore[arg-type]
    assert "📍" not in body
    assert body.split("\n")[-1] == "۵ نفر شرکت می‌کنند"
    assert [b.data for row in rows for b in row] == [f"{CAP}:book:7"]


def test_render_group_card_closed_event_and_resource_title() -> None:
    spec = events_spec(closes_hours_before_start=2)
    cap = spec.capabilities[0]
    resource = spec.resources[0]
    start = card_item()
    from app.runtime import formatting

    start_dt = formatting.parse_datetime(start.data["starts_at"])
    assert start_dt is not None
    body, rows = render_group_card(cap, start, 1, 2, now=start_dt - timedelta(hours=1), resource=resource)  # type: ignore[arg-type]
    assert tx.EVENTS_CARD_CLOSED in body and len(rows) == 1
    open_body, _ = render_group_card(cap, start, 1, 2, now=start_dt - timedelta(hours=5))  # type: ignore[arg-type]
    assert tx.EVENTS_CARD_CLOSED not in open_body


# --- the plain booking preset is unchanged -----------------------------------------------------


async def test_booking_preset_keeps_its_wording() -> None:
    h = Harness(booking_spec(capacity=1))
    item = await seed_item(h)
    listing_resp = await h.tap("ali", "menu:open:workshops")
    assert "یکی از موارد زیر را انتخاب کنید" in text(listing_resp)
    assert not any(":list:sub" in d or ":list:c" in d for d in datas(listing_resp))
    detail = await h.tap("ali", f"{WORKSHOP_CAP}:item:{item}")
    assert find_button(detail, tx.BOOK_BUTTON).data == f"{WORKSHOP_CAP}:book:{item}"
    done = await h.tap("ali", f"{WORKSHOP_CAP}:book:{item}")
    assert "ثبت‌نام شما در «کارگاه عکاسی» قطعی شد" in text(done, 0)
    mine = await h.tap("ali", f"{WORKSHOP_CAP}:mine:")
    assert "ثبت‌نام‌های فعال شما" in text(mine)


def test_events_texts_do_not_leak_into_booking_defaults() -> None:
    assert tx.TEXTS["confirmed"] == "ثبت‌نام شما در «{title}» قطعی شد."
    assert tx.BOOK_BUTTON == "ثبت‌نام" and tx.words("booking").book_button == "ثبت‌نام"
    assert tx.words("events").book_button == "شرکت می‌کنم"


# --- derived scenarios -------------------------------------------------------------------------


async def test_derived_events_scenarios_exist_and_pass() -> None:
    spec = events_spec(cancellation={"enabled": True, "deadline_hours": None})
    scenarios = derive_scenarios(spec)
    ids = {s.id for s in scenarios}
    for template in ("events_list", "events_category_filter", "events_rsvp_mine", "events_cancel_rsvp"):
        assert f"derived:{CAP}:{template}" in ids
    assert f"derived:{CAP}:basic" in ids  # plain booking templates still apply
    report = await run_scenarios(spec, scenarios)
    failed = [
        (r.scenario_id, [s.message for s in r.steps if not s.passed]) for r in report.results if not r.passed
    ]
    assert not failed, failed


async def test_derived_events_scenarios_pass_for_fixed_capacity_and_no_category() -> None:
    spec = events_spec(
        category_field=None,
        capacity={"mode": "fixed", "value": 5, "field": None},
        cancellation={"enabled": False, "deadline_hours": None},
    )
    scenarios = derive_scenarios(spec)
    ids = {s.id for s in scenarios}
    assert f"derived:{CAP}:events_list" in ids
    assert f"derived:{CAP}:events_category_filter" not in ids
    assert f"derived:{CAP}:events_cancel_rsvp" not in ids
    report = await run_scenarios(spec, scenarios)
    assert report.failed == 0, [r.scenario_id for r in report.results if not r.passed]


async def test_booking_preset_gets_no_events_scenarios() -> None:
    spec = events_spec(preset="booking")
    ids = {s.id for s in derive_scenarios(spec)}
    assert not any("events_" in i.split(":")[-1] for i in ids)
    assert f"derived:{CAP}:basic" in ids


async def test_golden_workshop_scenario_still_passes() -> None:
    from tests.unit.runtime.test_booking_scenarios import SCENARIOS

    report = await run_scenarios(load_example("workshop.botspec.json"), list(SCENARIOS))
    assert report.failed == 0, [r.scenario_id for r in report.results if not r.passed]
