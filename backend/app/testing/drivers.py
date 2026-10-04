"""Scenario drivers: perform semantic steps by sending the RuntimeEvents a user would send (WP3).

A driver never calls engine internals. It sends ``start``, the menu callback, the item callback,
the action callback and form texts through ``BotRuntime.handle``; at each hop it locates the next
button in the previous response by *parsed callback action and arg* (never by label) and fails the
step, naming the missing button, if it is not there. State expectations read the ``Store``.

Extension point: ``DRIVERS`` maps a capability type to a ``CapabilityDriver``. A later package
registers its driver with ``register_driver("request", RequestDriver())``; until then the
``request`` entry is a placeholder that fails every request step with "not supported yet".

``execute_step`` returns a short Persian result phrase for the narrative on success and raises
``StepFailure`` (Persian message stating expected vs actual) on failure. ``describe_step`` builds
the Persian sentence that names the step; the runner joins them as «sentence ← result».
"""

from datetime import datetime, timedelta
from typing import ClassVar, Protocol

from app.botspec.models import AnyCapability, BookingCapability, BotSpec, FieldDef, FieldType
from app.botspec.records import validate_record
from app.runtime import formatting
from app.runtime.callbacks import (
    ACT_ANS,
    ACT_BOOK,
    ACT_CANCEL,
    ACT_ITEM,
    ACT_LIST,
    ACT_OPEN,
    ACT_SKIP,
    MENU,
    CallbackError,
    make_callback,
    parse_callback,
)
from app.runtime.contracts import Actor, Button, Outcome, OutMessage, RuntimeEvent, RuntimeResponse
from app.runtime.runtime import BotRuntime
from app.runtime.store import Record, Store
from app.testing.scenario import OWNER, Step, TranscriptEntry

DISPLAY_NAMES: dict[str, str] = {"ali": "علی", "sara": "سارا", "reza": "رضا", OWNER: "مدیر"}
ACTIVE = ["confirmed", "waitlisted"]
MAX_PAGES = 100

REASON_FA: dict[str, str] = {
    "capacity_full": "تکمیل بودن ظرفیت",
    "duplicate": "ثبت‌نام تکراری",
    "user_limit": "سقف ثبت‌نام فعال هر کاربر",
    "booking_closed": "بسته شدن ثبت‌نام",
    "cancel_deadline_passed": "گذشتن مهلت لغو",
    "cancellation_disabled": "غیرفعال بودن لغو",
    "not_found": "پیدا نشدن مورد",
    "invalid_input": "ورودی نامعتبر",
    "not_allowed": "نداشتن دسترسی",
}
STATUS_FA: dict[str, str] = {
    "confirmed": "قطعی",
    "waitlisted": "در لیست انتظار",
    "cancelled": "لغو شده",
    "none": "بدون ثبت‌نام",
}
NOTICE_FA: dict[str, str] = {
    "booked": "ثبت‌نام جدید",
    "waitlisted": "ورود به لیست انتظار",
    "cancelled": "لغو ثبت‌نام",
    "promoted": "ارتقا از لیست انتظار",
    "submitted": "ثبت درخواست",
    "status_changed": "تغییر وضعیت",
}


class StepFailure(Exception):
    """A step did not pass. ``message`` is Persian; ``result`` is an optional narrative phrase."""

    def __init__(self, message: str, result: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.result = result


def _digits(value: int | float) -> str:
    return formatting.format_decimal(float(value))


# --- run context ---------------------------------------------------------------------------------


class RunContext:
    """Mutable state of one scenario run: clock, store, inboxes, transcript, seed refs."""

    def __init__(
        self,
        spec: BotSpec,
        store: Store,
        now: datetime,
        runtime: BotRuntime | None = None,
    ) -> None:
        self.spec = spec
        self.store = store
        self.now = now
        self.runtime = runtime or BotRuntime()
        self.refs: dict[str, int] = {}  # seed ref -> record id
        self.titles: dict[str, str] = {}  # seed ref -> rendered title of the seeded record
        self.inbox: dict[str, list[OutMessage]] = {}
        self.transcript: list[TranscriptEntry] = []
        self._labels: dict[str, dict[str, str]] = {}  # actor -> callback data -> label last shown

    # --- naming ----------------------------------------------------------------------------------

    @staticmethod
    def name(actor_id: str | None) -> str:
        if actor_id is None:
            return DISPLAY_NAMES[OWNER]
        return DISPLAY_NAMES.get(actor_id, actor_id)

    def cap_title(self, key: str | None) -> str:
        cap = self.spec.capability(key) if key else None
        return cap.title if cap is not None else (key or "؟")

    def item_title(self, ref: str | None) -> str:
        return self.titles.get(ref, ref or "؟") if ref else "؟"

    def item_id(self, step: Step) -> int:
        if step.item is None:
            raise StepFailure("این گام به آیتم (item) نیاز دارد ولی آیتمی مشخص نشده است.")
        rid = self.refs.get(step.item)
        if rid is None:
            raise StepFailure(f"آیتم «{step.item}» در داده‌های اولیهٔ سناریو وجود ندارد.")
        return rid

    # --- events ----------------------------------------------------------------------------------

    async def send(
        self, actor_id: str, kind: str, *, text: str | None = None, data: str | None = None
    ) -> RuntimeResponse:
        """Send one event as ``actor_id`` through the real runtime and record it."""
        actor = Actor(id=actor_id, display_name=self.name(actor_id), is_owner=actor_id == OWNER)
        event = RuntimeEvent(
            bot_id="scenario",
            env="sandbox",
            actor=actor,
            kind=kind,  # type: ignore[arg-type]
            text=text,
            data=data,
            now=self.now,
        )
        shown = self._labels.get(actor_id, {})
        if kind == "start":
            said = "/start"
        elif kind == "text":
            said = text or ""
        elif kind == "admin":
            said = f"[مدیریت] {data}"
        else:
            said = shown.get(data or "", data or "")
        self.transcript.append(TranscriptEntry(actor=actor_id, direction="in", text=said))
        resp = await self.runtime.handle(event, self.spec, self.store)
        mine: dict[str, str] = {}
        for msg in resp.messages:
            labels = [b.label for row in msg.buttons for b in row]
            self.transcript.append(
                TranscriptEntry(actor=msg.to_actor_id, direction="out", text=msg.text, buttons=labels)
            )
            if msg.to_actor_id != actor_id:
                self.inbox.setdefault(msg.to_actor_id, []).append(msg)
            else:
                mine.update({b.data: b.label for row in msg.buttons for b in row})
        if mine:
            self._labels[actor_id] = mine
        return resp

    async def press(self, actor_id: str, button: Button) -> RuntimeResponse:
        return await self.send(actor_id, "callback", data=button.data)

    def advance(self, hours: float) -> None:
        self.now = self.now + timedelta(hours=hours)


# --- response helpers ----------------------------------------------------------------------------


def find_button(
    resp: RuntimeResponse, actor_id: str, cap_key: str, action: str, arg: str | None = None
) -> Button | None:
    """The button (in a message to ``actor_id``) whose parsed callback is ``cap_key:action:arg``.

    ``arg=None`` matches any arg. Labels are never consulted. The latest message wins.
    """
    for msg in reversed(resp.messages):
        if msg.to_actor_id != actor_id:
            continue
        for row in msg.buttons:
            for button in row:
                try:
                    c, a, g = parse_callback(button.data)
                except CallbackError:
                    continue
                if c == cap_key and a == action and (arg is None or g == arg):
                    return button
    return None


def actor_messages(resp: RuntimeResponse, actor_id: str) -> list[OutMessage]:
    return [m for m in resp.messages if m.to_actor_id == actor_id]


def snippet(resp: RuntimeResponse, actor_id: str, limit: int = 140) -> str:
    """The last message the bot sent to ``actor_id``, squeezed onto one line."""
    msgs = actor_messages(resp, actor_id)
    if not msgs:
        return "(ربات پیامی برای این کاربر نفرستاد)"
    flat = " ".join(msgs[-1].text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _missing_button(what: str, resp: RuntimeResponse, actor_id: str) -> StepFailure:
    return StepFailure(f"دکمهٔ {what} در پاسخ ربات پیدا نشد. آخرین پیام ربات: «{snippet(resp, actor_id)}»")


def _last_outcome(resp: RuntimeResponse, cap_key: str, actions: tuple[str, ...]) -> Outcome | None:
    found = [o for o in resp.outcomes if o.capability == cap_key and o.action in actions]
    return found[-1] if found else None


def _reason(code: str | None) -> str:
    return f"«{REASON_FA.get(code, code)}» ({code})" if code else "نامشخص"


def _describe_outcome(o: Outcome) -> str:
    if o.result == "rejected":
        return f"رد شد به دلیل {_reason(o.reason)}"
    labels = {
        "confirmed": "تأیید قطعی (confirmed)",
        "waitlisted": "قرار گرفتن در لیست انتظار (waitlisted)",
        "cancelled": "لغو شد (cancelled)",
        "submitted": "ثبت شد (submitted)",
        "ok": "انجام شد (ok)",
    }
    return labels.get(o.result, o.result)


def _result_phrase(o: Outcome) -> str:
    if o.result == "rejected":
        return f"رد شد ({REASON_FA.get(o.reason or '', o.reason or 'نامشخص')})"
    return {
        "confirmed": "تأیید شد",
        "waitlisted": "در لیست انتظار قرار گرفت",
        "cancelled": "لغو شد",
        "submitted": "ثبت شد",
        "ok": "انجام شد",
    }.get(o.result, o.result)


def _expected_outcome(step: Step, ok_results: tuple[str, ...]) -> str:
    if step.expect == "rejected":
        base = "رد شدن"
        return f"{base} به دلیل {_reason(step.reason)}" if step.reason else base
    if step.expect == "ok" and ok_results:
        return "انجام موفق (ok/cancelled)"
    labels = {
        "confirmed": "تأیید قطعی (confirmed)",
        "waitlisted": "قرار گرفتن در لیست انتظار (waitlisted)",
        "cancelled": "لغو شدن (cancelled)",
        "submitted": "ثبت شدن (submitted)",
    }
    return labels.get(step.expect or "", step.expect or "")


def _check_outcome(
    step: Step,
    resp: RuntimeResponse,
    actor_id: str,
    cap_key: str,
    actions: tuple[str, ...],
    ok_results: tuple[str, ...] = (),
) -> str:
    """Compare the runtime Outcome with the step's expectation; return the narrative phrase."""
    outcome = _last_outcome(resp, cap_key, actions)
    if outcome is None:
        raise StepFailure(
            f"ربات نتیجهٔ مشخصی برای این اقدام برنگرداند. آخرین پیام ربات: «{snippet(resp, actor_id)}»",
            "بدون نتیجه",
        )
    phrase = _result_phrase(outcome)
    expect = step.expect
    if expect is None:
        return phrase
    if expect == "rejected":
        ok = outcome.result == "rejected" and (step.reason is None or outcome.reason == step.reason)
    elif ok_results:
        ok = outcome.result in ok_results
    else:
        ok = outcome.result == expect
    if not ok:
        raise StepFailure(
            f"انتظار: {_expected_outcome(step, ok_results)}؛ نتیجهٔ واقعی: {_describe_outcome(outcome)}. "
            f"پاسخ ربات: «{snippet(resp, actor_id)}»",
            phrase,
        )
    return phrase


# --- navigation ----------------------------------------------------------------------------------


def _menu_item_key(ctx: RunContext, cap: AnyCapability, view: str) -> str:
    item = next((m for m in ctx.spec.menu if m.capability == cap.key and m.view == view), None)
    if item is None:
        raise StepFailure(
            f"منوی ربات گزینه‌ای برای «{cap.title}» (نمای {view}) ندارد؛ کاربر نمی‌تواند به آن برسد."
        )
    return item.key


async def open_menu(ctx: RunContext, actor_id: str, cap: AnyCapability, view: str) -> RuntimeResponse:
    """``start``, then press the menu button that opens ``cap``'s ``view``."""
    key = _menu_item_key(ctx, cap, view)
    resp = await ctx.send(actor_id, "start")
    button = find_button(resp, actor_id, MENU, ACT_OPEN, key)
    if button is None:
        raise _missing_button(f"منوی «{key}» ({make_callback(MENU, ACT_OPEN, key)})", resp, actor_id)
    return await ctx.press(actor_id, button)


async def reach_item(
    ctx: RunContext, actor_id: str, cap: AnyCapability, item_id: int, title: str, view: str = "main"
) -> RuntimeResponse:
    """Open the menu, page through ``list`` until ``item:<id>`` shows, press it; return the detail."""
    resp = await open_menu(ctx, actor_id, cap, view)
    for page in range(MAX_PAGES):
        button = find_button(resp, actor_id, cap.key, ACT_ITEM, str(item_id))
        if button is not None:
            return await ctx.press(actor_id, button)
        nxt = find_button(resp, actor_id, cap.key, ACT_LIST, str(page + 1))
        if nxt is None:
            break
        resp = await ctx.press(actor_id, nxt)
    raise _missing_button(f"آیتم «{title}» ({cap.key}:{ACT_ITEM}:{item_id}) در فهرست", resp, actor_id)


# --- driver protocol and registry ------------------------------------------------------------------


class CapabilityDriver(Protocol):
    supported: ClassVar[frozenset[str]]  # Step.do values this driver performs

    async def perform(self, ctx: RunContext, step: Step, cap: AnyCapability) -> str: ...


async def _active_booking(ctx: RunContext, cap_key: str, actor_id: str, item_id: int) -> Record | None:
    rows = await ctx.store.list_records(cap_key, status_in=ACTIVE, actor_id=actor_id, item_id=item_id)
    return rows[-1] if rows else None


def _form_answer(step: Step, field: FieldDef) -> str | None:
    for kv in step.form:
        if kv.key == field.key and kv.value.strip():
            return kv.value
    return None


class BookingDriver:
    supported: ClassVar[frozenset[str]] = frozenset(
        {"book", "cancel", "owner_action", "expect_booking", "expect_counts"}
    )

    async def perform(self, ctx: RunContext, step: Step, cap: AnyCapability) -> str:
        if not isinstance(cap, BookingCapability):  # pragma: no cover - registry guarantees the type
            raise StepFailure(f"«{cap.key}» یک قابلیت رزرو نیست.")
        if step.do == "book":
            return await self._book(ctx, step, cap)
        if step.do == "cancel":
            return await self._cancel(ctx, step, cap)
        if step.do == "owner_action":
            return await self._owner_cancel(ctx, step, cap)
        if step.do == "expect_booking":
            return await self._expect_booking(ctx, step, cap)
        return await self._expect_counts(ctx, step, cap)

    # --- actions ---------------------------------------------------------------------------------

    async def _book(self, ctx: RunContext, step: Step, cap: BookingCapability) -> str:
        actor = step.actor or ""
        item_id = ctx.item_id(step)
        resp = await reach_item(ctx, actor, cap, item_id, ctx.item_title(step.item))
        button = find_button(resp, actor, cap.key, ACT_BOOK, str(item_id))
        if button is None:
            raise _missing_button(f"ثبت‌نام ({cap.key}:{ACT_BOOK}:{item_id})", resp, actor)
        resp = await ctx.press(actor, button)
        resp = await self._fill_form(ctx, step, cap, resp)
        return _check_outcome(step, resp, actor, cap.key, ("book",))

    async def _fill_form(
        self, ctx: RunContext, step: Step, cap: BookingCapability, resp: RuntimeResponse
    ) -> RuntimeResponse:
        """Answer the form questions the bot asks, by field key, until the booking is decided."""
        actor = step.actor or ""
        asked: dict[str, int] = {}
        for _ in range(len(cap.form_fields) * 2 + 4):
            if _last_outcome(resp, cap.key, ("book",)) is not None:
                return resp
            session = await ctx.store.get_session(actor)
            if not session:
                return resp
            key = (session.get("vars") or {}).get("field")
            field = next((f for f in cap.form_fields if f.key == key), None)
            if field is None:
                return resp
            asked[field.key] = asked.get(field.key, 0) + 1
            if asked[field.key] > 1:
                raise StepFailure(
                    f"پاسخ فیلد «{field.label}» ({field.key}) از سوی ربات پذیرفته نشد. "
                    f"پیام ربات: «{snippet(resp, actor)}»"
                )
            resp = await self._answer(ctx, actor, cap, field, _form_answer(step, field), resp)
        return resp

    async def _answer(
        self,
        ctx: RunContext,
        actor: str,
        cap: BookingCapability,
        field: FieldDef,
        raw: str | None,
        resp: RuntimeResponse,
    ) -> RuntimeResponse:
        if raw is None:
            if field.required:
                raise StepFailure(
                    f"فیلد الزامی «{field.label}» ({field.key}) در form این گام مقدار ندارد "
                    "ولی ربات آن را می‌پرسد."
                )
            skip = find_button(resp, actor, cap.key, ACT_SKIP)
            if skip is None:
                raise _missing_button(f"«رد کردن» ({cap.key}:{ACT_SKIP}) برای «{field.label}»", resp, actor)
            return await ctx.press(actor, skip)
        index = _choice_index(field, raw)
        if index is not None:
            button = find_button(resp, actor, cap.key, ACT_ANS, str(index))
            if button is None:
                raise _missing_button(f"گزینهٔ «{raw}» ({cap.key}:{ACT_ANS}:{index})", resp, actor)
            return await ctx.press(actor, button)
        return await ctx.send(actor, "text", text=raw)

    async def _cancel(self, ctx: RunContext, step: Step, cap: BookingCapability) -> str:
        actor = step.actor or ""
        item_id = ctx.item_id(step)
        title = ctx.item_title(step.item)
        booking = await _active_booking(ctx, cap.key, actor, item_id)
        if booking is None:
            raise StepFailure(f"{ctx.name(actor)} ثبت‌نام فعالی در «{title}» ندارد که لغو شود.")
        resp = await reach_item(ctx, actor, cap, item_id, title)
        button = find_button(resp, actor, cap.key, ACT_CANCEL, str(booking.id))
        if button is None:
            raise _missing_button(f"لغو ({cap.key}:{ACT_CANCEL}:{booking.id})", resp, actor)
        resp = await ctx.press(actor, button)
        return _check_outcome(step, resp, actor, cap.key, ("cancel",))

    async def _owner_cancel(self, ctx: RunContext, step: Step, cap: BookingCapability) -> str:
        actor = step.actor or OWNER
        if step.action != "cancel":
            raise StepFailure(
                f"عمل «{step.action}» برای قابلیت رزرو تعریف نشده است؛ تنها عمل مالک «cancel» است."
            )
        if step.item is None:
            raise StepFailure(
                "لغو توسط مدیر برای قابلیت رزرو به آیتم (item) نیاز دارد ولی آیتمی مشخص نشده است."
            )
        item_id = ctx.item_id(step)
        target = step.target_actor or ""
        booking = await _active_booking(ctx, cap.key, target, item_id)
        if booking is None:
            title = ctx.item_title(step.item)
            raise StepFailure(f"{ctx.name(target)} ثبت‌نام فعالی در «{title}» ندارد که مدیر آن را لغو کند.")
        resp = await ctx.send(actor, "admin", data=make_callback(cap.key, ACT_CANCEL, str(booking.id)))
        return _check_outcome(step, resp, actor, cap.key, ("cancel", "owner_action"), ("ok", "cancelled"))

    # --- expectations ----------------------------------------------------------------------------

    async def _expect_booking(self, ctx: RunContext, step: Step, cap: BookingCapability) -> str:
        actor = step.actor or ""
        item_id = ctx.item_id(step)
        rows = await ctx.store.list_records(cap.key, actor_id=actor, item_id=item_id)
        actual = (rows[-1].status or "none") if rows else "none"
        phrase = STATUS_FA.get(actual, actual)
        if actual != step.expect:
            expected = step.expect or ""
            wanted = f"«{STATUS_FA.get(expected, expected)}» ({expected})"
            raise StepFailure(
                f"انتظار: وضعیت ثبت‌نام {ctx.name(actor)} {wanted} باشد؛ نتیجهٔ واقعی: «{phrase}» ({actual})",
                phrase,
            )
        return phrase

    async def _expect_counts(self, ctx: RunContext, step: Step, cap: BookingCapability) -> str:
        item_id = ctx.item_id(step)
        confirmed = await ctx.store.count_records(cap.key, status_in=["confirmed"], item_id=item_id)
        waitlisted = await ctx.store.count_records(cap.key, status_in=["waitlisted"], item_id=item_id)
        phrase = f"{_digits(confirmed)} قطعی، {_digits(waitlisted)} در لیست انتظار"
        problems = []
        if step.confirmed is not None and step.confirmed != confirmed:
            problems.append(f"انتظار: {_digits(step.confirmed)} نفر قطعی؛ نتیجهٔ واقعی: {_digits(confirmed)}")
        if step.waitlisted is not None and step.waitlisted != waitlisted:
            problems.append(
                f"انتظار: {_digits(step.waitlisted)} نفر در لیست انتظار؛ نتیجهٔ واقعی: {_digits(waitlisted)}"
            )
        if problems:
            raise StepFailure("، ".join(problems), phrase)
        return phrase


def _choice_index(field: FieldDef, raw: str) -> int | None:
    """Button index for a choice/boolean answer, or None when it must be typed as text."""
    if field.type == FieldType.choice:
        choices = field.choices or []
        return choices.index(raw.strip()) if raw.strip() in choices else None
    if field.type == FieldType.boolean:
        cleaned, errors = validate_record([field], {field.key: raw})
        if errors:
            return None
        return 0 if cleaned[field.key] else 1
    return None


class PendingRequestDriver:
    """Placeholder for ``request`` capabilities (implemented by a later package)."""

    supported: ClassVar[frozenset[str]] = frozenset({"submit_request", "owner_action", "expect_request"})

    async def perform(self, ctx: RunContext, step: Step, cap: AnyCapability) -> str:
        raise StepFailure(
            f"گام «{step.do}» برای قابلیت درخواست («{cap.key}») هنوز پشتیبانی نمی‌شود (not supported yet).",
            "پشتیبانی نمی‌شود",
        )


DRIVERS: dict[str, CapabilityDriver] = {
    "booking": BookingDriver(),
    "request": PendingRequestDriver(),
}


def register_driver(cap_type: str, driver: CapabilityDriver) -> None:
    """Install (or replace) the driver for a capability type, e.g. ``"request"``."""
    DRIVERS[cap_type] = driver


# --- generic steps -------------------------------------------------------------------------------


def _any_text(resp: RuntimeResponse, actor_id: str, needle: str) -> bool:
    for msg in actor_messages(resp, actor_id):
        if needle in msg.text or any(needle in b.label for row in msg.buttons for b in row):
            return True
    return False


async def _open(ctx: RunContext, step: Step, cap: AnyCapability) -> str:
    actor = step.actor or ""
    view = step.view or "main"
    if step.item is not None:
        if cap.type not in ("booking", "catalog"):
            raise StepFailure(f"باز کردن آیتم برای قابلیت «{cap.key}» از نوع {cap.type} معنی ندارد.")
        resp = await reach_item(ctx, actor, cap, ctx.item_id(step), ctx.item_title(step.item), view)
    else:
        resp = await open_menu(ctx, actor, cap, view)
    if step.contains is not None and not _any_text(resp, actor, step.contains):
        labels = [b.label for m in actor_messages(resp, actor) for row in m.buttons for b in row]
        raise StepFailure(
            f"متن «{step.contains}» در پاسخ ربات (متن پیام‌ها یا برچسب دکمه‌ها) پیدا نشد. "
            f"پیام ربات: «{snippet(resp, actor)}»؛ دکمه‌ها: {labels}",
            "یافت نشد",
        )
    return "نمایش داده شد" if step.contains is None else f"«{step.contains}» دیده شد"


def _expect_notified(ctx: RunContext, step: Step) -> str:
    actor = step.actor or ""
    box = ctx.inbox.get(actor, [])
    matching = [
        m
        for m in box
        if (step.event is None or m.notice == step.event)
        and (step.contains is None or step.contains in m.text)
    ]
    if not matching:
        wanted = f"از نوع «{step.event}» " if step.event else ""
        if step.contains:
            wanted += f"حاوی «{step.contains}» "
        got = (
            "، ".join(f"{m.notice or 'بدون نوع'}: «{' '.join(m.text.split())[:60]}»" for m in box)
            if box
            else "هیچ پیامی"
        )
        raise StepFailure(
            f"انتظار: {ctx.name(actor)} پیامی {wanted}دریافت کند؛ نتیجهٔ واقعی: {got} در صندوق او است.",
            "پیامی نرسید",
        )
    ctx.inbox[actor] = []
    return "پیام رسید"


async def execute_step(ctx: RunContext, step: Step) -> str:
    """Run one step; return the Persian result phrase or raise ``StepFailure``."""
    if step.do == "advance_time":
        ctx.advance(step.hours or 0)
        return "زمان جلو رفت"
    if step.do == "expect_notified":
        return _expect_notified(ctx, step)
    cap = ctx.spec.capability(step.capability) if step.capability else None
    if cap is None:
        raise StepFailure(f"قابلیت «{step.capability}» در مشخصات ربات وجود ندارد.")
    if step.do == "open":
        return await _open(ctx, step, cap)
    driver = DRIVERS.get(cap.type)
    if driver is None or step.do not in driver.supported:
        raise StepFailure(
            f"گام «{step.do}» برای قابلیت «{cap.key}» از نوع {cap.type} پشتیبانی نمی‌شود (not supported)."
        )
    return await driver.perform(ctx, step, cap)


# --- narratives ----------------------------------------------------------------------------------


def _menu_label(ctx: RunContext, cap_key: str | None, view: str) -> str:
    item = next((m for m in ctx.spec.menu if m.capability == cap_key and m.view == view), None)
    return item.label if item is not None else ctx.cap_title(cap_key)


def describe_step(ctx: RunContext, step: Step) -> str:
    """One Persian sentence naming what the step does (without its result)."""
    who = ctx.name(step.actor)
    cap_title = ctx.cap_title(step.capability)
    item = ctx.item_title(step.item)
    do = step.do
    if do == "book":
        return f"{who} در «{item}» ثبت‌نام می‌کند"
    if do == "cancel":
        return f"{who} ثبت‌نام خود در «{item}» را لغو می‌کند"
    if do == "owner_action":
        who = ctx.name(step.actor or OWNER)
        target = ctx.name(step.target_actor)
        cap = ctx.spec.capability(step.capability) if step.capability else None
        if cap is not None and cap.type == "booking":
            return f"{who} ثبت‌نام {target} در «{item}» را لغو می‌کند"
        label = step.action or "؟"
        if cap is not None and cap.type == "request":
            label = next((a.label for a in cap.owner_actions if a.key == step.action), label)
        return f"{who} روی درخواست {target} در «{cap_title}» اقدام «{label}» را انجام می‌دهد"
    if do == "submit_request":
        return f"{who} در «{cap_title}» درخواست ثبت می‌کند"
    if do == "expect_booking":
        return f"بررسی وضعیت ثبت‌نام {who} در «{item}»"
    if do == "expect_counts":
        return f"بررسی تعداد ثبت‌نام‌های «{item}»"
    if do == "expect_request":
        return f"بررسی وضعیت درخواست {who} در «{cap_title}»"
    if do == "expect_notified":
        kind = f"«{NOTICE_FA.get(step.event, step.event)}»" if step.event else "یک"
        return f"بررسی دریافت پیام {kind} توسط {who}"
    if do == "open":
        text = f"{who} بخش «{_menu_label(ctx, step.capability, step.view or 'main')}» را باز می‌کند"
        return text + (f" و «{item}» را انتخاب می‌کند" if step.item else "")
    return f"{_digits(step.hours or 0)} ساعت می‌گذرد"


def narrative(sentence: str, result: str) -> str:
    return f"{sentence} ← {result}" if result else sentence


__all__ = [
    "DISPLAY_NAMES",
    "DRIVERS",
    "BookingDriver",
    "CapabilityDriver",
    "PendingRequestDriver",
    "RunContext",
    "StepFailure",
    "describe_step",
    "execute_step",
    "find_button",
    "narrative",
    "register_driver",
]
