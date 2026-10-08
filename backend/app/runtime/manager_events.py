"""Event management in Telegram for managers (U7): list, guided creation, detail, attendees,
announcements to registrants and group publishing. Deterministic, no LLM.

Only booking capabilities with ``preset="events"`` (nav's ``mgr.evt`` candidates) and only managers
(every route below has ``role="manager"``; nav answers anyone else with the stale home). Importing
this module registers the routes (``nav.register_route``) and the form step hosts
(``forms.register_step``); ``runtime/runtime.py`` imports it.

Routes (``~<n>`` = the events capability's ordinal, kept on every link; ids are record ids):

  mgr.evt                 upcoming events: [➕ رویداد جدید], one button per event
                          «title · ۱۹ مهر · ۱۸/۲۰», paging, [🕘 گذشته], [🧭 مدیریت]
  mgr.evt.up.<page>       the same list, another page
  mgr.evt.past[.<page>]   past events, newest first, [📅 پیش رو]
  mgr.evt.<id>            the manager's event detail (no RSVP buttons): date and time, place,
                          category, capacity, confirmed/waitlisted counts, [👥 شرکت‌کنندگان],
                          [📣 اعلان به ثبت‌نام‌شدگان], [📣 انتشار در گروه] (only when the bot is
                          in a group), [🧭 بازگشت به رویدادها]
  mgr.evt.att.<id>[.<p>]  attendees (confirmed, then waitlisted with their position), names from
                          the store, one [✖ لغو ثبت‌نام …] per attendee
  mgr.evt.cx.<booking>    confirm cancelling one attendee; mgr.evt.cxy.<booking> does it through
                          the booking engine's owner action ``cancel`` (the web's admin cancel:
                          the customer is notified and the waitlist promoted)
  mgr.evt.ann.<id>        announcement to the confirmed registrants (prompt, preview, send)
  mgr.evt.pub.<id>[.<g>]  publish the event card (``services/group_cards.render_for_item``, the
                          web publish's card) into group ``<g>`` (``n<abs id>`` for a negative
                          chat id, ``p<id>`` otherwise) through the notification outbox
  mgr.evt.new             the guided creation form below

Creation form (session step ``mgr_evt_new``; the session's capability is the events capability, so
the runtime routes its text and form actions through the booking engine to ``forms``, which hands
them to this module: ``forms.register_step``). One step per resource field, in this order: title,
``description``, the start datetime as two steps (date, time), category, ``location``, any other
field, capacity (``capacity.mode == "per_item"``). Every step has [‹ بازگشت] (the previous step; the
first step goes back to the list) and [✖ لغو] (cancels the whole flow); optional fields add
[رد کردن] ([بدون محدودیت] for an optional capacity); a step that already has a value adds
[✔ بدون تغییر]. Steps:
  date      the next 14 days in the bot's timezone as Jalali buttons («یکشنبه ۱۹ مهر»), plus
            [✍️ تاریخ دیگر را بنویسید]; typed «۱۴۰۵/۷/۲۰», «1405-07-20» or «۷/۲۰» (``jalali``)
  time      08:00-22:00 every 30 minutes, rows of four (past slots hidden for today); typed «۱۸:۳۰»
  choice    one button per choice (typed text matching a choice is accepted)
  preview   every value formatted; [✅ انتشار] [✏️ ویرایش] (back to the first step, values kept)
            [‹ بازگشت] [✖ لغو]
Publishing validates the whole record with ``validate_record_detailed`` (what the web data API
uses), the date and time combined in the bot's timezone and stored as UTC ISO; a value that fails
sends the manager back to its step with the error. The session is cleared before the record is
created, so a second [✅ انتشار] press finds no session and gets the stale notice (no duplicate).

Form callback args (``<cap>:ans:<arg>``, ``<cap>:skip:``, ``<cap>:stop:``): ``b`` back, ``k`` keep,
``d<YYYYMMDD>`` a date, ``dx`` type a date, ``dd`` the date buttons again, ``t<HHMM>`` a time,
``o<i>`` choice/boolean option ``i``, ``n<int>`` a capacity shortcut, ``pub`` publish, ``edit``. A
button that does not belong to the current step (an older message) re-asks the current step in a
NEW message. Session vars: ``{"stage": <step id> | "preview", "values": {...}, "ord": <n>}``; a
datetime field's parts live under ``<key>#date`` (ISO date) and ``<key>#time`` (``HH:MM``).

Announcement (session step ``mgr_evt_ann``, vars ``{"event", "ord", "text"}``): typed text ->
preview -> [📣 ارسال برای n نفر]. Recipients are the confirmed registrants at send time. A store
with ``enqueue_outbox`` (``PgStore`` in live) queues one outbox message per recipient in the event's
transaction; any other store (simulator, tests) sends them as ``announcement`` notices.

Optional store services (not in the frozen ``Store`` protocol; detected with ``getattr``):
``display_names(actor_ids)``, ``group_chats()`` and ``enqueue_outbox(chat_ids, text, buttons)``.
Without them names fall back to the booking's ``name`` value or the actor id, and group publishing
is not offered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any

from app.botspec.models import AnyCapability, BookingCapability, BotSpec, FieldDef, FieldType, Resource
from app.botspec.records import RecordValueError, coerce_value, to_utc_iso, validate_record_detailed
from app.botspec.text_keys import fill_text
from app.roles import can_run_owner_actions
from app.runtime import formatting, forms, jalali, listing, nav
from app.runtime.callbacks import ACT_ANS, ACT_CANCEL, ACT_ITEM, ACT_SKIP, ACT_STOP, CallbackError
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx, parse_int
from app.runtime.engines import EngineUnavailable, get_engine
from app.runtime.engines.booking import CONFIRMED, WAITLISTED, BookingEngine
from app.runtime.store import Record
from app.runtime.texts import common
from app.runtime.texts import manager_events as tx
from app.runtime.texts import nav as nav_tx

Rows = list[list[Button]]

STEP_NEW = "mgr_evt_new"
STEP_ANN = "mgr_evt_ann"
PREVIEW = "preview"

R_LIST = "mgr.evt"
R_UP = "mgr.evt.up"
R_PAST = "mgr.evt.past"
R_NEW = "mgr.evt.new"
R_ATT = "mgr.evt.att"
R_CX = "mgr.evt.cx"
R_CXY = "mgr.evt.cxy"
R_ANN = "mgr.evt.ann"
R_PUB = "mgr.evt.pub"

DATE_DAYS = 14
FIRST_SLOT = (8, 0)
LAST_SLOT = (22, 0)
SLOT_MINUTES = 30
SLOTS_PER_ROW = 4
DAYS_PER_ROW = 2
CHOICES_PER_ROW = 2
CAPACITY_SHORTCUTS = (10, 20, 30, 50, 100)
ATTENDEES_PAGE = 10
ANNOUNCEMENT_MAX_CHARS = 3500  # the web announcement limit (schemas.business)
NAME_MAX = 30

_DATE_ARG = re.compile(r"d(\d{8})")
_TIME_ARG = re.compile(r"t(\d{4})")
_OPTION_ARG = re.compile(r"o(\d{1,3})")
_NUMBER_ARG = re.compile(r"n(\d{1,6})")
_CHAT_ARG = re.compile(r"([np])(\d{1,19})")
_PRIVATE_CHAT = re.compile(r"[0-9]+")  # ASCII only: a person's private chat id


def _fill(template: str, **values: object) -> str:
    return fill_text(template, {k: str(v) for k, v in values.items()})


def _num(value: int) -> str:
    return formatting.format_int(value)


# --- context -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Events:
    """The events capability being managed, its resource and its nav ordinal."""

    cap: BookingCapability
    resource: Resource
    ordinal: int

    @property
    def label(self) -> str:
        return self.resource.label or self.cap.title

    @property
    def plural(self) -> str:
        return self.resource.label_plural or self.cap.title

    def route(self, route_id: str, *args: str | int) -> str:
        return nav.route_payload(route_id, self.ordinal, *args)

    def button(self, label: str, route_id: str, *args: str | int) -> Button:
        return nav.nav_button(label, self.route(route_id, *args))


def _events_of(spec: BotSpec, cap: AnyCapability | None, ordinal: int) -> Events | None:
    if not isinstance(cap, BookingCapability) or cap.preset != "events":
        return None
    resource = spec.resource(cap.resource)
    return Events(cap, resource, ordinal) if resource is not None else None


def _ordinal_of(spec: BotSpec, cap: AnyCapability) -> int:
    candidates = nav.ROUTES[R_LIST].candidates
    for n, candidate in enumerate(candidates(spec) if candidates else [], 1):
        if candidate.key == cap.key:
            return n
    return 1


def _crumb(ev: Events, *extra: str) -> str:
    return nav_tx.CRUMB_SEPARATOR.join(
        [nav_tx.MANAGER_SHORT, _fill(tx.LIST_HEADING, plural=ev.plural), *(e for e in extra if e)]
    )


def _is_manager(ctx: Ctx) -> bool:
    return ctx.actor.effective_role == "manager"


def _today(ctx: Ctx) -> date:
    return formatting.to_local(ctx.now, ctx.tz).date()


def _start(ev: Events, record: Record) -> datetime | None:
    return formatting.parse_datetime(record.data.get(ev.cap.start_field)) if ev.cap.start_field else None


def _title(ctx: Ctx, ev: Events, record: Record) -> str:
    return listing.record_title(ctx, ev.resource, record)


def _list_button(ev: Events) -> Button:
    return ev.button(_fill(tx.EVENTS_BUTTON, plural=ev.plural), R_LIST)


def _event_button(ev: Events, record_id: int, label: str | None = None) -> Button:
    return ev.button(label or _fill(tx.BACK_TO_EVENT, label=ev.label), R_LIST, record_id)


async def _get_event(ctx: Ctx, ev: Events, record_id: int | None) -> Record | None:
    if record_id is None:
        return None
    return await ctx.store.get_record(ev.resource.key, record_id)


def _not_found(ctx: Ctx, ev: Events) -> None:
    """A link to an event (or booking) that no longer exists: a NEW message, the old one stays."""
    ctx.reply(_fill(tx.NOT_FOUND, label=ev.label), [[_list_button(ev)]], edit=False)


async def _counts(ctx: Ctx, ev: Events, record_id: int) -> tuple[int, int]:
    confirmed = await ctx.store.count_records(ev.cap.key, status_in=[CONFIRMED], item_id=record_id)
    waitlisted = await ctx.store.count_records(ev.cap.key, status_in=[WAITLISTED], item_id=record_id)
    return confirmed, waitlisted


# --- optional store services ---------------------------------------------------------------------


async def _group_chats(ctx: Ctx) -> list[tuple[int, str]]:
    service = getattr(ctx.store, "group_chats", None)
    if service is None:
        return []
    return list(await service())


async def _names(ctx: Ctx, bookings: list[Record]) -> dict[str, str]:
    service = getattr(ctx.store, "display_names", None)
    ids = {b.actor_id for b in bookings if b.actor_id}
    return dict(await service(ids)) if service is not None and ids else {}


def _person(booking: Record, names: dict[str, str]) -> str:
    name = names.get(booking.actor_id or "") or booking.data.get("name")
    if not isinstance(name, str) or not name.strip():
        name = _fill(tx.UNKNOWN_PERSON, id=booking.actor_id or "—")
    return listing.truncate(name.strip(), NAME_MAX)


async def _enqueue(ctx: Ctx, chat_ids: list[int], text: str, buttons: Rows | None) -> bool:
    service = getattr(ctx.store, "enqueue_outbox", None)
    if service is None:
        return False
    return bool(await service(chat_ids, text, buttons))


# --- creation steps ------------------------------------------------------------------------------

_ORDER = {"title": 0, "description": 1, "start": 2, "category": 3, "location": 4, "other": 5, "capacity": 6}


@dataclass(frozen=True)
class Step:
    id: str  # "<kind>:<field key>"
    kind: str  # text | number | choice | bool | date | time
    role: str  # title | description | start | category | location | capacity | other
    field: FieldDef

    @property
    def key(self) -> str:
        """Where the step's answer lives in the session values."""
        if self.kind in ("date", "time"):
            return f"{self.field.key}#{self.kind}"
        return self.field.key


def _role(ev: Events, field: FieldDef) -> str:
    cap = ev.cap
    if field.key == ev.resource.title_field:
        return "title"
    if field.key == cap.start_field:
        return "start"
    if field.key == cap.category_field:
        return "category"
    if cap.capacity.mode == "per_item" and field.key == cap.capacity.field:
        return "capacity"
    if field.key in ("description", "location"):
        return field.key
    return "other"


def _steps(ev: Events) -> list[Step]:
    fields = sorted(enumerate(ev.resource.fields), key=lambda p: (_ORDER[_role(ev, p[1])], p[0]))
    steps: list[Step] = []
    for _, field in fields:
        role = _role(ev, field)
        if field.type == FieldType.datetime:
            steps.append(Step(f"date:{field.key}", "date", role, field))
            steps.append(Step(f"time:{field.key}", "time", role, field))
        elif field.type == FieldType.choice:
            steps.append(Step(f"choice:{field.key}", "choice", role, field))
        elif field.type == FieldType.boolean:
            steps.append(Step(f"bool:{field.key}", "bool", role, field))
        elif field.type in (FieldType.integer, FieldType.decimal):
            steps.append(Step(f"number:{field.key}", "number", role, field))
        else:
            steps.append(Step(f"text:{field.key}", "text", role, field))
    return steps


def _step_name(step: Step) -> str:
    if step.kind == "date":
        return tx.DATE_STEP if step.role == "start" else f"{tx.DATE_STEP} {step.field.label}"
    if step.kind == "time":
        return tx.TIME_STEP if step.role == "start" else f"{tx.TIME_STEP} {step.field.label}"
    return step.field.label


def _question(ev: Events, step: Step, *, none_left: bool = False) -> str:
    name = step.field.label
    if step.kind == "date":
        return tx.ASK_DATE_START if step.role == "start" else _fill(tx.ASK_DATE, name=name)
    if step.kind == "time":
        if none_left:
            return tx.ASK_TIME_NONE_LEFT
        return tx.ASK_TIME_START if step.role == "start" else _fill(tx.ASK_TIME, name=name)
    if step.role == "title":
        return _fill(tx.ASK_TITLE, label=ev.label)
    if step.role == "description":
        return _fill(tx.ASK_DESCRIPTION, label=ev.label)
    if step.role == "location":
        return tx.ASK_LOCATION
    if step.role == "capacity":
        return tx.ASK_CAPACITY
    if step.kind == "choice":
        return _fill(tx.ASK_CHOICE, name=name)
    if step.kind == "bool":
        return _fill(tx.ASK_BOOLEAN, name=name)
    if step.kind == "number":
        return _fill(tx.ASK_NUMBER, name=name)
    return _fill(tx.ASK_TEXT, name=name)


def _date_of(values: dict[str, Any], field_key: str) -> date | None:
    raw = values.get(f"{field_key}#date")
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def _time_of(values: dict[str, Any], field_key: str) -> tuple[int, int] | None:
    raw = values.get(f"{field_key}#time")
    return jalali.parse_time(raw) if isinstance(raw, str) else None


def _compose(ctx: Ctx, values: dict[str, Any], field_key: str) -> datetime | None:
    """The local date and time of a datetime field, combined in the bot's timezone."""
    d, t = _date_of(values, field_key), _time_of(values, field_key)
    if d is None or t is None:
        return None
    return datetime.combine(d, time(t[0], t[1]), tzinfo=formatting.get_tz(ctx.tz))


def _shown_value(ctx: Ctx, step: Step, values: dict[str, Any]) -> str:
    value = values.get(step.key)
    if value is None:
        return formatting.EMPTY_VALUE
    if step.kind == "date":
        d = _date_of(values, step.field.key)
        return jalali.full_date(d) if d is not None else formatting.EMPTY_VALUE
    if step.kind == "time":
        t = _time_of(values, step.field.key)
        return jalali.hhmm(*t) if t is not None else formatting.EMPTY_VALUE
    return ctx.fmt(step.field, value)


def _slots() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    minutes = FIRST_SLOT[0] * 60 + FIRST_SLOT[1]
    while minutes <= LAST_SLOT[0] * 60 + LAST_SLOT[1]:
        out.append(divmod(minutes, 60))
        minutes += SLOT_MINUTES
    return out


def _chunk(buttons: list[Button], size: int) -> Rows:
    return [buttons[i : i + size] for i in range(0, len(buttons), size)]


def _ans(ev: Events, label: str, arg: str) -> Button:
    return Ctx.button(label, ev.cap, ACT_ANS, arg)


def _nav_row(ev: Events, steps: list[Step], step: Step | None) -> list[Button]:
    """[‹ بازگشت] [✖ لغو]; Back on the first step leaves the form for the list."""
    if step is not None and steps and step.id == steps[0].id:
        back = ev.button(tx.BACK, R_LIST)
    else:
        back = _ans(ev, tx.BACK, "b")
    return [back, Ctx.button(tx.CANCEL, ev.cap, ACT_STOP)]


def _step_rows(ctx: Ctx, ev: Events, steps: list[Step], step: Step, values: dict[str, Any]) -> Rows:
    rows: Rows = []
    field = step.field
    if step.kind == "date":
        today = _today(ctx)
        days = [today + timedelta(days=i) for i in range(DATE_DAYS)]
        rows += _chunk([_ans(ev, jalali.weekday_day_month(d), f"d{d:%Y%m%d}") for d in days], DAYS_PER_ROW)
        rows.append([_ans(ev, tx.TYPE_DATE, "dx")])
    elif step.kind == "time":
        rows += _chunk(
            [_ans(ev, jalali.hhmm(h, m), f"t{h:02d}{m:02d}") for h, m in _open_slots(ctx, step, values)],
            SLOTS_PER_ROW,
        )
    elif step.kind == "choice":
        choices = list(field.choices or [])
        rows += _chunk(
            [_ans(ev, listing.truncate(c, 30), f"o{i}") for i, c in enumerate(choices)], CHOICES_PER_ROW
        )
    elif step.kind == "bool":
        rows.append([_ans(ev, tx.YES, "o0"), _ans(ev, tx.NO, "o1")])
    elif step.role == "capacity":
        rows.append([_ans(ev, _num(n), f"n{n}") for n in CAPACITY_SHORTCUTS])
    if not field.required and step.kind != "time":
        rows.append([Ctx.button(tx.UNLIMITED if step.role == "capacity" else tx.SKIP, ev.cap, ACT_SKIP)])
    if step.key in values:
        rows.append([_ans(ev, tx.KEEP, "k")])
    rows.append(_nav_row(ev, steps, step))
    return rows


def _open_slots(ctx: Ctx, step: Step, values: dict[str, Any]) -> list[tuple[int, int]]:
    """The time buttons: every slot, or only the ones still ahead when the date is today."""
    d = _date_of(values, step.field.key)
    if d is None or d != _today(ctx):
        return _slots()
    tz = formatting.get_tz(ctx.tz)
    return [(h, m) for h, m in _slots() if datetime.combine(d, time(h, m), tzinfo=tz) > ctx.now]


def _ask(
    ctx: Ctx,
    ev: Events,
    steps: list[Step],
    step: Step,
    values: dict[str, Any],
    *,
    prefix: str | None = None,
    edit: bool | None = None,
) -> None:
    n = next((i for i, s in enumerate(steps, 1) if s.id == step.id), 1)
    lines = [
        _crumb(ev, _fill(tx.NEW_TITLE, label=ev.label)),
        _fill(tx.STEP_LINE, n=_num(n), total=_num(len(steps)), name=_step_name(step)),
        "",
    ]
    if prefix:
        lines += [prefix, ""]
    none_left = step.kind == "time" and not _open_slots(ctx, step, values)
    question = _question(ev, step, none_left=none_left)
    if not step.field.required and step.kind != "time":
        question = f"{question} {tx.OPTIONAL}"
    lines.append(question)
    if step.key in values:
        lines.append(_fill(tx.CURRENT_VALUE, value=_shown_value(ctx, step, values)))
    ctx.reply("\n".join(lines), _step_rows(ctx, ev, steps, step, values), edit=edit)


def _ask_typed_date(ctx: Ctx, ev: Events, steps: list[Step], step: Step) -> None:
    lines = [
        _crumb(ev, _fill(tx.NEW_TITLE, label=ev.label)),
        _fill(
            tx.STEP_LINE,
            n=_num(next((i for i, s in enumerate(steps, 1) if s.id == step.id), 1)),
            total=_num(len(steps)),
            name=_step_name(step),
        ),
        "",
        tx.ASK_DATE_TYPED,
    ]
    ctx.reply("\n".join(lines), [[_ans(ev, tx.BACK, "dd"), Ctx.button(tx.CANCEL, ev.cap, ACT_STOP)]])


def _preview_lines(ctx: Ctx, ev: Events, steps: list[Step], values: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for step in steps:
        field = step.field
        if field.key in seen:
            continue
        seen.add(field.key)
        if field.type == FieldType.datetime:
            dt = _compose(ctx, values, field.key)
            shown = formatting.format_datetime(dt, ctx.tz) if dt is not None else formatting.EMPTY_VALUE
        else:
            shown = _shown_value(ctx, step, values)
        lines.append(f"{field.label}: {shown}")
    return lines


def _preview(
    ctx: Ctx,
    ev: Events,
    steps: list[Step],
    values: dict[str, Any],
    *,
    prefix: str | None = None,
    edit: bool | None = None,
) -> None:
    lines = [_crumb(ev, _fill(tx.NEW_TITLE, label=ev.label)), ""]
    if prefix:
        lines += [prefix, ""]
    lines.append(_fill(tx.PREVIEW_HEADING, label=ev.label))
    lines += _preview_lines(ctx, ev, steps, values)
    lines += ["", tx.PREVIEW_HINT]
    rows: Rows = [
        [_ans(ev, tx.PUBLISH, "pub")],
        [_ans(ev, tx.EDIT, "edit")],
        [_ans(ev, tx.BACK, "b"), Ctx.button(tx.CANCEL, ev.cap, ACT_STOP)],
    ]
    ctx.reply("\n".join(lines), rows, edit=edit)


# --- creation flow -------------------------------------------------------------------------------


async def _start_form(ctx: Ctx, ev: Events) -> None:
    steps = _steps(ev)
    session = {
        "capability": ev.cap.key,
        "step": STEP_NEW,
        "vars": {"stage": steps[0].id, "values": {}, "ord": ev.ordinal},
    }
    await ctx.set_session(session)
    _ask(ctx, ev, steps, steps[0], {})


async def _goto(
    ctx: Ctx, ev: Events, session: dict[str, Any], steps: list[Step], stage: str, *, prefix: str | None = None
) -> None:
    session["vars"]["stage"] = stage
    await ctx.set_session(session)
    values = session["vars"]["values"]
    if stage == PREVIEW:
        _preview(ctx, ev, steps, values, prefix=prefix)
        return
    step = next(s for s in steps if s.id == stage)
    _ask(ctx, ev, steps, step, values, prefix=prefix)


async def _advance(ctx: Ctx, ev: Events, session: dict[str, Any], steps: list[Step], step: Step) -> None:
    idx = next(i for i, s in enumerate(steps) if s.id == step.id)
    nxt = steps[idx + 1].id if idx + 1 < len(steps) else PREVIEW
    await _goto(ctx, ev, session, steps, nxt)


async def _answer(
    ctx: Ctx, ev: Events, session: dict[str, Any], steps: list[Step], step: Step, value: Any
) -> None:
    session["vars"]["values"][step.key] = value
    if step.kind == "date" and value is None:  # an optional datetime skipped: no time either
        session["vars"]["values"][f"{step.field.key}#time"] = None
        idx = next(i for i, s in enumerate(steps) if s.id == step.id)
        if (
            idx + 1 < len(steps)
            and steps[idx + 1].kind == "time"
            and steps[idx + 1].field.key == step.field.key
        ):
            step = steps[idx + 1]
    await _advance(ctx, ev, session, steps, step)


def _check_date(ctx: Ctx, d: date) -> str | None:
    return tx.PAST_DATE if d < _today(ctx) else None


def _check_time(ctx: Ctx, step: Step, values: dict[str, Any], t: tuple[int, int]) -> str | None:
    d = _date_of(values, step.field.key)
    if d is None:
        return None
    if datetime.combine(d, time(*t), tzinfo=formatting.get_tz(ctx.tz)) <= ctx.now:
        return tx.PAST_TIME
    return None


def _coerce(ev: Events, step: Step, raw: Any) -> tuple[Any, str | None]:
    """A typed or chosen value for a non-date/time step: ``(cleaned, None)`` or ``(None, error)``."""
    try:
        value = coerce_value(step.field, raw)
    except RecordValueError as exc:
        return None, _fill(tx.INVALID_ANSWER, error=str(exc))
    if step.role == "capacity" and isinstance(value, int | float) and value < 1:
        return None, tx.INVALID_CAPACITY
    if isinstance(value, str) and not value:
        return None, _fill(tx.INVALID_ANSWER, error=f"«{step.field.label}» خالی است.")
    return value, None


async def _new_text(ctx: Ctx, ev: Events, session: dict[str, Any], steps: list[Step], text: str) -> None:
    stage = session["vars"].get("stage")
    values = session["vars"]["values"]
    if stage == PREVIEW:
        _preview(ctx, ev, steps, values, prefix=tx.USE_BUTTONS)
        return
    step = next((s for s in steps if s.id == stage), None)
    if step is None:
        await _goto(ctx, ev, session, steps, steps[0].id)
        return
    if step.kind == "date":
        d = jalali.parse_date(text, _today(ctx))
        error = (
            _fill(tx.INVALID_DATE, text=listing.truncate(text.strip(), 30))
            if d is None
            else _check_date(ctx, d)
        )
        if error is not None or d is None:
            _ask(ctx, ev, steps, step, values, prefix=error)
            return
        await _answer(ctx, ev, session, steps, step, d.isoformat())
        return
    if step.kind == "time":
        t = jalali.parse_time(text)
        error = (
            _fill(tx.INVALID_TIME, text=listing.truncate(text.strip(), 30))
            if t is None
            else _check_time(ctx, step, values, t)
        )
        if error is not None or t is None:
            _ask(ctx, ev, steps, step, values, prefix=error)
            return
        await _answer(ctx, ev, session, steps, step, f"{t[0]:02d}:{t[1]:02d}")
        return
    value, error = _coerce(ev, step, text)
    if error is not None:
        prefix = f"{error}\n{tx.USE_BUTTONS}" if step.kind in ("choice", "bool") else error
        _ask(ctx, ev, steps, step, values, prefix=prefix)
        return
    await _answer(ctx, ev, session, steps, step, value)


async def _new_callback(
    ctx: Ctx, ev: Events, session: dict[str, Any], steps: list[Step], action: str, arg: str
) -> None:
    v = session["vars"]
    values: dict[str, Any] = v["values"]
    if action == ACT_STOP:
        await ctx.clear_session()
        ctx.reply(
            _fill(tx.CANCELLED, label=ev.label),
            [[_list_button(ev)], [nav.nav_button(tx.MANAGER_BUTTON, nav.MGR)]],
        )
        return
    stage = v.get("stage")
    if stage == PREVIEW:
        if action == ACT_ANS and arg == "pub":
            await _publish(ctx, ev, session, steps)
        elif action == ACT_ANS and arg == "edit":
            await _goto(ctx, ev, session, steps, steps[0].id)
        elif action == ACT_ANS and arg == "b":
            await _goto(ctx, ev, session, steps, steps[-1].id)
        else:
            _preview(ctx, ev, steps, values, prefix=tx.STEP_STALE, edit=False)
        return
    step = next((s for s in steps if s.id == stage), None)
    if step is None:  # the spec changed under the form: start over, values kept
        await _goto(ctx, ev, session, steps, steps[0].id)
        return
    if action == ACT_SKIP:
        if step.field.required or step.kind == "time":
            _ask(ctx, ev, steps, step, values, prefix=tx.STEP_STALE, edit=False)
            return
        await _answer(ctx, ev, session, steps, step, None)
        return
    if action != ACT_ANS:
        _ask(ctx, ev, steps, step, values, prefix=tx.STEP_STALE, edit=False)
        return
    if arg == "b":
        idx = next(i for i, s in enumerate(steps) if s.id == step.id)
        await _goto(ctx, ev, session, steps, steps[max(idx - 1, 0)].id)
        return
    if arg == "k" and step.key in values:
        kept = values[step.key]
        if step.kind == "time" and kept is not None:
            t = _time_of(values, step.field.key)
            error = _check_time(ctx, step, values, t) if t is not None else tx.PAST_TIME
            if error is not None:
                _ask(ctx, ev, steps, step, values, prefix=error)
                return
        if step.kind == "date" and kept is not None:
            d = _date_of(values, step.field.key)
            error = _check_date(ctx, d) if d is not None else tx.PAST_DATE
            if error is not None:
                _ask(ctx, ev, steps, step, values, prefix=error)
                return
        await _advance(ctx, ev, session, steps, step)
        return
    await _pick(ctx, ev, session, steps, step, arg)


async def _pick(
    ctx: Ctx, ev: Events, session: dict[str, Any], steps: list[Step], step: Step, arg: str
) -> None:
    """A step button (date, time, option, capacity shortcut); anything else is a stale press."""
    values: dict[str, Any] = session["vars"]["values"]
    if step.kind == "date":
        if arg == "dx":
            _ask_typed_date(ctx, ev, steps, step)
            return
        if arg == "dd":
            _ask(ctx, ev, steps, step, values)
            return
        m = _DATE_ARG.fullmatch(arg)
        d: date | None = None
        if m is not None:
            try:
                d = datetime.strptime(m.group(1), "%Y%m%d").date()
            except ValueError:
                d = None
        if d is not None:
            error = _check_date(ctx, d)
            if error is not None:
                _ask(ctx, ev, steps, step, values, prefix=error)
                return
            await _answer(ctx, ev, session, steps, step, d.isoformat())
            return
    elif step.kind == "time":
        m = _TIME_ARG.fullmatch(arg)
        t = jalali.parse_time(f"{m.group(1)[:2]}:{m.group(1)[2:]}") if m is not None else None
        if t is not None:
            error = _check_time(ctx, step, values, t)
            if error is not None:
                _ask(ctx, ev, steps, step, values, prefix=error)
                return
            await _answer(ctx, ev, session, steps, step, f"{t[0]:02d}:{t[1]:02d}")
            return
    elif step.kind in ("choice", "bool"):
        m = _OPTION_ARG.fullmatch(arg)
        idx = int(m.group(1)) if m is not None else -1
        options: list[Any] = list(step.field.choices or []) if step.kind == "choice" else [True, False]
        if 0 <= idx < len(options):
            value, error = _coerce(ev, step, options[idx])
            if error is None:
                await _answer(ctx, ev, session, steps, step, value)
                return
    elif step.role == "capacity":
        m = _NUMBER_ARG.fullmatch(arg)
        if m is not None:
            value, error = _coerce(ev, step, int(m.group(1)))
            if error is None:
                await _answer(ctx, ev, session, steps, step, value)
                return
    _ask(ctx, ev, steps, step, values, prefix=tx.STEP_STALE, edit=False)


def _record_data(ctx: Ctx, ev: Events, values: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field in ev.resource.fields:
        if field.type == FieldType.datetime:
            dt = _compose(ctx, values, field.key)
            data[field.key] = to_utc_iso(dt) if dt is not None else None
        else:
            data[field.key] = values.get(field.key)
    return data


def _step_for_field(steps: list[Step], field_key: str | None) -> Step:
    return next((s for s in steps if s.field.key == field_key), steps[0])


async def _publish(ctx: Ctx, ev: Events, session: dict[str, Any], steps: list[Step]) -> None:
    values: dict[str, Any] = session["vars"]["values"]
    cleaned, errors = validate_record_detailed(ev.resource.fields, _record_data(ctx, ev, values))
    if errors:
        field_key, message = errors[0]
        prefix = _fill(tx.CREATE_FAILED, label=ev.label, error=message)
        await _goto(ctx, ev, session, steps, _step_for_field(steps, field_key).id, prefix=prefix)
        return
    start = formatting.parse_datetime(cleaned.get(ev.cap.start_field)) if ev.cap.start_field else None
    if start is not None and start <= ctx.now:
        await _goto(
            ctx, ev, session, steps, _step_for_field(steps, ev.cap.start_field).id, prefix=tx.PAST_TIME
        )
        return
    await ctx.clear_session()  # before creating: a second press finds no session (no duplicate)
    record = await ctx.create_record(ev.resource.key, cleaned, actor_id=None)
    lines = [_crumb(ev, _title(ctx, ev, record)), "", _fill(tx.CREATED, label=ev.label)]
    if start is not None:
        lines.append(_fill(tx.DETAIL_WHEN, when=formatting.format_datetime(start, ctx.tz)))
    rows: Rows = []
    if await _group_chats(ctx):
        rows.append([ev.button(tx.PUBLISH_IN_GROUP, R_PUB, record.id)])
    rows.append([_event_button(ev, record.id, _fill(tx.VIEW_EVENT, label=ev.label))])
    rows.append([_list_button(ev)])
    ctx.reply("\n".join(lines), rows)


# --- announcement flow ---------------------------------------------------------------------------


async def _recipients(ctx: Ctx, ev: Events, record_id: int) -> list[str]:
    bookings = await ctx.store.list_records(ev.cap.key, status_in=[CONFIRMED], item_id=record_id)
    return list(dict.fromkeys(b.actor_id for b in bookings if b.actor_id))


async def _ann_ask(
    ctx: Ctx, ev: Events, record: Record, count: int, *, prefix: str | None = None, edit: bool | None = None
) -> None:
    lines = [_crumb(ev, _title(ctx, ev, record), tx.ANNOUNCE_TITLE), ""]
    if prefix:
        lines += [prefix, ""]
    lines.append(_fill(tx.ANNOUNCE_ASK, count=_num(count)))
    rows: Rows = [[_event_button(ev, record.id), Ctx.button(tx.CANCEL, ev.cap, ACT_STOP)]]
    ctx.reply("\n".join(lines), rows, edit=edit)


async def _ann_text(ctx: Ctx, ev: Events, session: dict[str, Any], text: str) -> None:
    v = session["vars"]
    record = await _get_event(ctx, ev, v.get("event") if isinstance(v.get("event"), int) else None)
    if record is None:
        await ctx.clear_session()
        _not_found(ctx, ev)
        return
    count = len(await _recipients(ctx, ev, record.id))
    message = text.strip()
    if not message:
        await _ann_ask(ctx, ev, record, count, prefix=tx.ANNOUNCE_EMPTY)
        return
    if len(message) > ANNOUNCEMENT_MAX_CHARS:
        await _ann_ask(
            ctx, ev, record, count, prefix=_fill(tx.ANNOUNCE_TOO_LONG, max=_num(ANNOUNCEMENT_MAX_CHARS))
        )
        return
    v["text"] = message
    await ctx.set_session(session)
    lines = [
        _crumb(ev, _title(ctx, ev, record), tx.ANNOUNCE_TITLE),
        "",
        _fill(tx.ANNOUNCE_PREVIEW, count=_num(count), message=message),
    ]
    rows: Rows = [
        [_ans(ev, _fill(tx.ANNOUNCE_SEND, count=_num(count)), "send")],
        [_ans(ev, tx.ANNOUNCE_REWRITE, "re")],
        [_event_button(ev, record.id), Ctx.button(tx.CANCEL, ev.cap, ACT_STOP)],
    ]
    ctx.reply("\n".join(lines), rows)


async def _ann_callback(ctx: Ctx, ev: Events, session: dict[str, Any], action: str, arg: str) -> None:
    v = session["vars"]
    record = await _get_event(ctx, ev, v.get("event") if isinstance(v.get("event"), int) else None)
    if record is None:
        await ctx.clear_session()
        _not_found(ctx, ev)
        return
    back = [[_event_button(ev, record.id)], [_list_button(ev)]]
    if action == ACT_STOP:
        await ctx.clear_session()
        ctx.reply(tx.ANNOUNCE_CANCELLED, back)
        return
    recipients = await _recipients(ctx, ev, record.id)
    if action == ACT_ANS and arg == "re":
        v["text"] = None
        await ctx.set_session(session)
        await _ann_ask(ctx, ev, record, len(recipients))
        return
    message = v.get("text")
    if not (action == ACT_ANS and arg == "send" and isinstance(message, str) and message):
        await _ann_ask(ctx, ev, record, len(recipients), prefix=tx.STEP_STALE, edit=False)
        return
    await ctx.clear_session()  # before sending: a second press finds no session
    text = _fill(tx.ANNOUNCE_MESSAGE, title=_title(ctx, ev, record), message=message)
    buttons: Rows = [[Ctx.button(_fill(tx.VIEW_EVENT, label=ev.label), ev.cap, ACT_ITEM, record.id)]]
    chats = [int(a) for a in recipients if _PRIVATE_CHAT.fullmatch(a)]
    if not await _enqueue(ctx, chats, text, buttons):
        for actor_id in recipients:
            ctx.notify(actor_id, "announcement", text, buttons)
    ctx.reply(_fill(tx.ANNOUNCE_SENT, count=_num(len(recipients))), back)


async def _start_announce(ctx: Ctx, ev: Events, record: Record) -> None:
    count = len(await _recipients(ctx, ev, record.id))
    if count == 0:
        lines = [_crumb(ev, _title(ctx, ev, record), tx.ANNOUNCE_TITLE), "", tx.ANNOUNCE_NOBODY]
        ctx.reply("\n".join(lines), [[_event_button(ev, record.id)]])
        return
    await ctx.set_session(
        {
            "capability": ev.cap.key,
            "step": STEP_ANN,
            "vars": {"event": record.id, "ord": ev.ordinal, "text": None},
        }
    )
    await _ann_ask(ctx, ev, record, count)


# --- step host (forms.register_step) -------------------------------------------------------------


class _Host:
    """Receives the sessions of both flows from ``runtime/forms.py``."""

    @staticmethod
    async def _load(ctx: Ctx, cap: AnyCapability, session: dict[str, Any]) -> Events | None:
        """The managed events, or None after answering a press that no longer applies."""
        ord_raw = session["vars"].get("ord")
        ordinal = ord_raw if isinstance(ord_raw, int) and ord_raw >= 1 else _ordinal_of(ctx.spec, cap)
        ev = _events_of(ctx.spec, cap, ordinal) if _is_manager(ctx) else None
        if ev is None or not session["vars"] or not isinstance(session["vars"].get("values", {}), dict):
            await ctx.clear_session()
            ctx.stale()
            return None
        return ev

    async def on_step_text(self, ctx: Ctx, cap: Any, session: dict[str, Any], text: str) -> None:
        ev = await self._load(ctx, cap, session)
        if ev is None:
            return
        if session.get("step") == STEP_ANN:
            await _ann_text(ctx, ev, session, text)
            return
        session["vars"].setdefault("values", {})
        await _new_text(ctx, ev, session, _steps(ev), text)

    async def on_step_callback(
        self, ctx: Ctx, cap: Any, session: dict[str, Any], action: str, arg: str
    ) -> None:
        ev = await self._load(ctx, cap, session)
        if ev is None:
            return
        if session.get("step") == STEP_ANN:
            await _ann_callback(ctx, ev, session, action, arg)
            return
        session["vars"].setdefault("values", {})
        await _new_callback(ctx, ev, session, _steps(ev), action, arg)


HOST = _Host()


# --- screens -------------------------------------------------------------------------------------


def _event_label(ev: Events, title: str, start: datetime | None, tz: str, going: int, capacity: int) -> str:
    when = jalali.day_month(formatting.to_local(start, tz).date()) if start is not None else tx.NO_DATE
    count = (
        _fill(tx.GOING_OF, going=_num(going), capacity=_num(capacity))
        if capacity > 0
        else _fill(tx.GOING, going=_num(going))
    )
    suffix = f" · {when} · {count}"
    room = max(listing.MAX_BUTTON_LABEL - len(suffix), 12)
    return listing.truncate(title, room) + suffix


async def _show_list(ctx: Ctx, ev: Events, *, past: bool, page: int) -> None:
    records = await ctx.store.list_records(ev.resource.key)
    start_field = ev.cap.start_field
    if start_field:
        upcoming = [r for r in records if not listing.is_past(r, start_field, ctx.now)]
        done = [r for r in records if listing.is_past(r, start_field, ctx.now)]
        items = (
            listing.sort_records(done, start_field, desc=True)
            if past
            else listing.sort_records(upcoming, start_field)
        )
    else:
        items = [] if past else listing.sort_records(records, None)
    shown, page, pages = listing.paginate(items, page)

    rows: Rows = [[ev.button(_fill(tx.NEW_BUTTON, label=ev.label), R_NEW)]]
    for record in shown:
        confirmed = await ctx.store.count_records(ev.cap.key, status_in=[CONFIRMED], item_id=record.id)
        label = _event_label(
            ev,
            _title(ctx, ev, record),
            _start(ev, record),
            ctx.tz,
            confirmed,
            BookingEngine._capacity(ev.cap, record),
        )
        rows.append([ev.button(label, R_LIST, record.id)])
    route = R_PAST if past else R_UP
    paging: list[Button] = []
    if page > 0:
        paging.append(ev.button(common.PREVIOUS, route, page - 1))
    if page < pages - 1:
        paging.append(ev.button(common.NEXT, route, page + 1))
    if paging:
        rows.append(paging)
    if past:
        rows.append([ev.button(tx.UPCOMING_BUTTON, R_LIST)])
    elif start_field:
        rows.append([ev.button(tx.PAST_BUTTON, R_PAST)])
    rows.append([nav.nav_button(tx.MANAGER_BUTTON, nav.MGR)])

    lines = [_crumb(ev, tx.PAST_TITLE if past else "")]
    if items:
        template = tx.PAST_COUNT if past else tx.UPCOMING_COUNT
        lines.append(_fill(template, count=_num(len(items)), label=ev.label))
        if pages > 1:
            lines.append(listing.page_indicator(page, pages))
    else:
        lines.append(_fill(tx.PAST_EMPTY if past else tx.UPCOMING_EMPTY, label=ev.label))
    ctx.reply("\n".join(lines), rows)


async def _show_detail(ctx: Ctx, ev: Events, record: Record) -> None:
    cap = ev.cap
    lines = [_crumb(ev, _title(ctx, ev, record)), ""]
    start = _start(ev, record)
    if start is not None:
        lines.append(_fill(tx.DETAIL_WHEN, when=formatting.format_datetime(start, ctx.tz)))
    place = record.data.get("location")
    if place not in (None, ""):
        lines.append(_fill(tx.DETAIL_PLACE, place=place))
    category = record.data.get(cap.category_field) if cap.category_field else None
    if category not in (None, ""):
        lines.append(_fill(tx.DETAIL_CATEGORY, category=category))
    capacity = BookingEngine._capacity(cap, record)
    lines.append(
        _fill(tx.DETAIL_CAPACITY, capacity=_num(capacity) if capacity > 0 else formatting.EMPTY_VALUE)
    )
    confirmed, waitlisted = await _counts(ctx, ev, record.id)
    if cap.waitlist.enabled or waitlisted:
        lines.append(_fill(tx.DETAIL_COUNTS, confirmed=_num(confirmed), waitlisted=_num(waitlisted)))
    else:
        lines.append(_fill(tx.DETAIL_COUNTS_NO_WAITLIST, confirmed=_num(confirmed)))
    description = record.data.get("description")
    if (
        isinstance(description, str)
        and description.strip()
        and description != record.data.get(ev.resource.title_field)
    ):
        lines += ["", listing.truncate(description.strip(), 600)]
    is_past = start is not None and start < ctx.now
    if is_past:
        lines += ["", _fill(tx.DETAIL_PAST, label=ev.label)]

    rows: Rows = [
        [ev.button(_fill(tx.ATTENDEES_BUTTON, count=_num(confirmed + waitlisted)), R_ATT, record.id)],
        [ev.button(tx.ANNOUNCE_BUTTON, R_ANN, record.id)],
    ]
    if not is_past and await _group_chats(ctx):
        rows.append([ev.button(tx.PUBLISH_IN_GROUP, R_PUB, record.id)])
    rows.append([ev.button(_fill(tx.BACK_TO_LIST, plural=ev.plural), R_PAST if is_past else R_LIST)])
    ctx.reply("\n".join(lines), rows)


async def _show_attendees(
    ctx: Ctx, ev: Events, record: Record, page: int, *, prefix: str | None = None
) -> None:
    bookings = await ctx.store.list_records(ev.cap.key, status_in=[CONFIRMED, WAITLISTED], item_id=record.id)
    confirmed = [b for b in bookings if b.status == CONFIRMED]
    waitlisted = [b for b in bookings if b.status == WAITLISTED]
    ordered = confirmed + waitlisted
    names = await _names(ctx, ordered)
    shown, page, pages = listing.paginate(ordered, page, ATTENDEES_PAGE)
    lines = [_crumb(ev, _title(ctx, ev, record), tx.ATTENDEES_TITLE), ""]
    if prefix:
        lines += [prefix, ""]
    can_cancel = can_run_owner_actions(ev.cap, ctx.actor)
    rows: Rows = []
    if not ordered:
        lines.append(tx.ATTENDEES_EMPTY)
    first = page * ATTENDEES_PAGE
    for n, booking in enumerate(shown, first + 1):
        name = _person(booking, names)
        if booking.status == WAITLISTED:
            position = next((i for i, w in enumerate(waitlisted, 1) if w.id == booking.id), 0)
            status = _fill(tx.STATUS_WAITLISTED, position=_num(position))
        else:
            status = tx.STATUS_CONFIRMED
        lines.append(_fill(tx.ATTENDEE_LINE, n=_num(n), name=name, status=status))
        if can_cancel:
            rows.append([ev.button(listing.truncate(_fill(tx.CANCEL_ATTENDEE, name=name)), R_CX, booking.id)])
    if pages > 1:
        lines.append(listing.page_indicator(page, pages))
        paging: list[Button] = []
        if page > 0:
            paging.append(ev.button(common.PREVIOUS, R_ATT, record.id, page - 1))
        if page < pages - 1:
            paging.append(ev.button(common.NEXT, R_ATT, record.id, page + 1))
        rows.append(paging)
    rows.append([_event_button(ev, record.id)])
    ctx.reply("\n".join(lines), rows)


async def _active_booking(ctx: Ctx, ev: Events, booking_id: int | None) -> Record | None:
    if booking_id is None:
        return None
    booking = await ctx.store.get_record(ev.cap.key, booking_id)
    return booking if booking is not None and booking.status in (CONFIRMED, WAITLISTED) else None


async def _confirm_cancel(ctx: Ctx, ev: Events, booking_id: int | None) -> None:
    booking = await _active_booking(ctx, ev, booking_id)
    record = await _get_event(ctx, ev, booking.item_id) if booking is not None else None
    if booking is None or record is None:
        ctx.reply(tx.BOOKING_GONE, [[_list_button(ev)]], edit=False)
        return
    name = _person(booking, await _names(ctx, [booking]))
    lines = [
        _crumb(ev, _title(ctx, ev, record), tx.ATTENDEES_TITLE),
        "",
        _fill(tx.CONFIRM_CANCEL, name=name, title=_title(ctx, ev, record)),
    ]
    rows: Rows = [
        [ev.button(tx.CONFIRM_CANCEL_YES, R_CXY, booking.id)],
        [ev.button(tx.BACK_TO_ATTENDEES, R_ATT, record.id)],
    ]
    ctx.reply("\n".join(lines), rows)


async def _do_cancel(ctx: Ctx, ev: Events, booking_id: int | None) -> None:
    """The booking engine's owner action ``cancel`` (notifies the customer, promotes the waitlist),
    then the attendee list again with the result on top."""
    booking = await _active_booking(ctx, ev, booking_id)
    record = await _get_event(ctx, ev, booking.item_id) if booking is not None else None
    if booking is None or record is None:
        ctx.reply(tx.BOOKING_GONE, [[_list_button(ev)]], edit=False)
        return
    if not can_run_owner_actions(ev.cap, ctx.actor):
        await nav.stale_home(ctx)
        return
    try:
        engine = get_engine(ev.cap.type)
    except EngineUnavailable:
        await nav.stale_home(ctx)
        return
    name = _person(booking, await _names(ctx, [booking]))
    before = len(ctx.messages)
    await engine.owner_action(ctx, ev.cap, booking.id, ACT_CANCEL)
    # The engine's own reply to the acting manager is replaced by the attendee list (its notices to
    # the customer and to promoted people stay as they are).
    own = [m for m in ctx.messages[before:] if m.to_actor_id == ctx.actor.id and m.notice is None]
    result = own[0].text if own else ""
    dropped = {id(m) for m in own}
    ctx.messages = ctx.messages[:before] + [m for m in ctx.messages[before:] if id(m) not in dropped]
    cancelled = any(o.action == "cancel" and o.result == "cancelled" for o in ctx.outcomes)
    prefix = _fill(tx.ATTENDEE_CANCELLED, name=name) if cancelled else result
    await _show_attendees(ctx, ev, record, 0, prefix=prefix)
    if own and own[0].edit:
        ctx.messages[-1].edit = True


async def _publish_card(ctx: Ctx, ev: Events, record: Record, chat_arg: str | None) -> None:
    groups = await _group_chats(ctx)
    back: Rows = [[_event_button(ev, record.id)]]
    title = _title(ctx, ev, record)
    if not groups:
        ctx.reply(tx.NO_GROUPS, back)
        return
    if chat_arg is None:
        rows: Rows = []
        for chat_id, group_title in groups:
            code = f"n{-chat_id}" if chat_id < 0 else f"p{chat_id}"
            try:
                rows.append(
                    [ev.button(listing.truncate(group_title or str(chat_id)), R_PUB, record.id, code)]
                )
            except CallbackError:
                continue
        lines = [_crumb(ev, title, tx.PUBLISH_IN_GROUP), "", _fill(tx.GROUPS_ASK, title=title)]
        ctx.reply("\n".join(lines), rows + back)
        return
    m = _CHAT_ARG.fullmatch(chat_arg)
    chat_id = (-int(m.group(2)) if m.group(1) == "n" else int(m.group(2))) if m is not None else None
    group = next((g for g in groups if g[0] == chat_id), None)
    if group is None:
        ctx.reply(tx.GROUP_GONE, back, edit=False)
        return
    from app.services.group_cards import render_for_item  # the web publish's card (pure, store-only)

    card = await render_for_item(ctx.store, ctx.spec, ev.cap, record.id, now=ctx.now)
    if card is None:
        _not_found(ctx, ev)
        return
    text, buttons = card
    if not await _enqueue(ctx, [group[0]], text, buttons):
        ctx.notify(str(group[0]), "announcement", text, buttons)
    ctx.reply(_fill(tx.GROUP_QUEUED, title=title, group=group[1]), [*back, [_list_button(ev)]])


# --- route resolvers -----------------------------------------------------------------------------


async def _events_or_stale(ctx: Ctx, target: nav.Target) -> Events | None:
    ev = _events_of(ctx.spec, target.cap, target.ordinal)
    if ev is None:
        await nav.stale_home(ctx)
    return ev


async def _resolve_main(ctx: Ctx, target: nav.Target) -> None:
    """``mgr.evt`` (the upcoming list) and ``mgr.evt.<id>`` (an event's detail)."""
    ev = await _events_or_stale(ctx, target)
    if ev is None:
        return
    if not target.args:
        await _show_list(ctx, ev, past=False, page=0)
        return
    record = await _get_event(ctx, ev, parse_int(target.arg))
    if record is None:
        _not_found(ctx, ev)
        return
    await _show_detail(ctx, ev, record)


async def _resolve_upcoming(ctx: Ctx, target: nav.Target) -> None:
    ev = await _events_or_stale(ctx, target)
    if ev is not None:
        await _show_list(ctx, ev, past=False, page=parse_int(target.arg) or 0)


async def _resolve_past(ctx: Ctx, target: nav.Target) -> None:
    ev = await _events_or_stale(ctx, target)
    if ev is not None:
        await _show_list(ctx, ev, past=True, page=parse_int(target.arg) or 0)


async def _resolve_new(ctx: Ctx, target: nav.Target) -> None:
    ev = await _events_or_stale(ctx, target)
    if ev is not None:
        await _start_form(ctx, ev)


def _event_resolver(screen: Any) -> nav.Resolver:
    async def resolve(ctx: Ctx, target: nav.Target) -> None:
        ev = await _events_or_stale(ctx, target)
        if ev is None:
            return
        record = await _get_event(ctx, ev, parse_int(target.arg))
        if record is None:
            _not_found(ctx, ev)
            return
        await screen(ctx, ev, record, target.args[1] if len(target.args) > 1 else None)

    return resolve


async def _attendees_screen(ctx: Ctx, ev: Events, record: Record, extra: str | None) -> None:
    await _show_attendees(ctx, ev, record, parse_int(extra or "") or 0)


async def _announce_screen(ctx: Ctx, ev: Events, record: Record, extra: str | None) -> None:
    await _start_announce(ctx, ev, record)


async def _publish_screen(ctx: Ctx, ev: Events, record: Record, extra: str | None) -> None:
    await _publish_card(ctx, ev, record, extra)


async def _resolve_confirm_cancel(ctx: Ctx, target: nav.Target) -> None:
    ev = await _events_or_stale(ctx, target)
    if ev is not None:
        await _confirm_cancel(ctx, ev, parse_int(target.arg))


async def _resolve_do_cancel(ctx: Ctx, target: nav.Target) -> None:
    ev = await _events_or_stale(ctx, target)
    if ev is not None:
        await _do_cancel(ctx, ev, parse_int(target.arg))


def _no_label(spec: BotSpec, cap: AnyCapability | None, named: bool) -> str:
    return ""


def register() -> None:
    """Make ``mgr.evt`` and ``mgr.evt.new`` real and add the sub-routes and form step hosts.
    Idempotent (re-registering replaces the same entries)."""
    base = nav.ROUTES[R_LIST]
    candidates = base.candidates
    nav.register_route(replace(base, resolve=_resolve_main, max_args=1, ready=True))
    nav.register_route(replace(nav.ROUTES[R_NEW], resolve=_resolve_new, ready=True))
    for route_id, resolver, max_args in (
        (R_UP, _resolve_upcoming, 1),
        (R_PAST, _resolve_past, 1),
        (R_ATT, _event_resolver(_attendees_screen), 2),
        (R_CX, _resolve_confirm_cancel, 1),
        (R_CXY, _resolve_do_cancel, 1),
        (R_ANN, _event_resolver(_announce_screen), 1),
        (R_PUB, _event_resolver(_publish_screen), 2),
    ):
        nav.register_route(
            nav.Route(
                route_id,
                R_LIST,
                resolver,
                _no_label,
                role="manager",
                candidates=candidates,
                max_args=max_args,
            )
        )
    forms.register_step(STEP_NEW, HOST)
    forms.register_step(STEP_ANN, HOST)


register()
