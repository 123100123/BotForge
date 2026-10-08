"""``booking`` engine: capacity, waitlist, cancellation and automatic promotion (WP2).

Data model: bookable items are records of resource ``cap.resource``; bookings are records of
collection ``cap.key`` with ``item_id`` (item record id), ``actor_id`` (customer), ``status`` in
{confirmed, waitlisted, cancelled} and ``data`` = cleaned form values. Active = confirmed or
waitlisted.

Navigation (drivers locate buttons by parsed callback action/arg, never by label):
  open main / ``list:<page>``  items (start not passed when ``start_field`` is set), one
                               ``item:<id>`` button each; nav row; ``mine``; home
  ``item:<id>``                detail; ALWAYS ``book:<id>``; plus ``cancel:<booking id>`` for each
                               of the actor's active bookings on the item; back (the list's
                               ``nav`` route); home
  ``book:<id>``                checks -> rejected Outcome, or form (``data={"item_id": id}``) whose
                               completion re-runs every check, or immediate booking
  open mine / ``mine``         the actor's active bookings, one ``cancel:<booking id>`` each
  ``cancel:<booking id>``      own active booking only (else ``not_found``); cancellation rules
  owner_action(id, "cancel")   any active booking; ignores ``cancellation``; same promotion rule

Book checks, in order: item missing -> not_found; now > start, or now > start -
closes_hours_before_start -> booking_closed; active booking on the item and
one_active_per_user_per_item -> duplicate; active bookings in this capability >=
max_active_per_user -> user_limit; confirmed < capacity -> confirmed; waitlist -> waitlisted;
else capacity_full. Boundaries: exactly at a cutoff or deadline the action is still allowed.

Promotion: after a *confirmed* booking is cancelled, if the waitlist is enabled with
auto_promote, waitlisted bookings on the item are confirmed oldest first (lowest id) while
confirmed < capacity. Capacity lowered below the confirmed count therefore promotes nobody.

Events preset (``cap.preset == "events"``): same data model and rules, event wording (``events_*``
texts, ``texts.booking.EVENTS_WORDS``), and no new actions; everything extra is encoded in the
``list`` argument:
  ``list:<page>``              upcoming events (all categories)
  ``list:c<idx>.<page>``       only the category ``category_field.choices[idx]``
  ``list:sub``                 per-user category subscriptions: one toggle button per category
  ``list:sub.<idx>``           toggle category ``idx``; a subscription is a record of collection
                               ``<cap.key>.subs`` (actor_id = subscriber, data = {category: <choice>})
In a group chat (``event.chat_type == "group"``) ``book`` books when the capability has no form
fields and answers with ONE short text (no buttons, never an edit); every other action, and a
``book`` that needs a form, answers with ``EVENTS_GROUP_PRIVATE``. ``render_group_card`` builds the
card the publish endpoint posts into groups.

All times come from ``ctx.now``; stored datetimes are UTC ISO strings. The engine is not safe
against two events for the same bot running concurrently: the adapter must serialize them.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar

from app.botspec.models import BookingCapability, Resource
from app.botspec.text_keys import TEXT_KEYS, fill_text
from app.runtime import formatting, forms, listing
from app.runtime.callbacks import (
    ACT_BOOK,
    ACT_CANCEL,
    ACT_ITEM,
    ACT_LIST,
    ACT_MINE,
    FORM_ACTIONS,
)
from app.runtime.contracts import Button, ReasonCode
from app.runtime.ctx import Ctx, parse_int
from app.runtime.engines import chrome
from app.runtime.engines.base import EngineBase
from app.runtime.store import Record
from app.runtime.texts import booking as tx
from app.runtime.texts import common
from app.runtime.texts.booking import Words, words

CONFIRMED = "confirmed"
WAITLISTED = "waitlisted"
CANCELLED = "cancelled"
ACTIVE = [CONFIRMED, WAITLISTED]

Rows = list[list[Button]]


@dataclass
class Decision:
    """Result of the booking checks: ``status`` to create, or ``reason`` + ``text`` to reject."""

    item: Record | None
    status: str | None = None
    reason: ReasonCode | None = None
    text: str = ""


def _fill(template: str, **values: object) -> str:
    return fill_text(template, {k: str(v) for k, v in values.items()})


def _is_events(cap: BookingCapability) -> bool:
    return cap.preset == "events"


def _has_override(cap: BookingCapability, key: str) -> bool:
    return any(o.key == key for o in cap.texts)


def _t(ctx: Ctx, cap: BookingCapability, key: str, **placeholders: object) -> str:
    """Bot text for ``cap``'s preset: the events preset prefers ``events_<key>`` (unless the owner
    overrode only the plain ``key``); every other case is exactly ``ctx.t(cap, key)``."""
    if _is_events(cap):
        ekey = f"events_{key}"
        if ekey in TEXT_KEYS["booking"] and (_has_override(cap, ekey) or not _has_override(cap, key)):
            return ctx.t(cap, ekey, **placeholders)
    return ctx.t(cap, key, **placeholders)


def render_group_card(
    cap: BookingCapability,
    item: Record,
    going: int,
    capacity: int | None,
    *,
    now: datetime,
    resource: Resource | None = None,
    tz: str = formatting.DEFAULT_TZ,
) -> tuple[str, list[list[Button]]]:
    """Group-chat card of one event: title, Jalali date and time, location, attendance and ONE
    ``[شرکت می‌کنم]`` button (``book:<item id>``). Pure: no Store access.

    ``capacity`` None means unlimited/unknown (``N نفر شرکت می‌کنند``), else ``N / capacity``.
    ``resource`` (for its ``title_field``) and ``tz`` (the bot's timezone) are optional; without
    them the title falls back to the record's ``title`` value and the time is shown in Tehran.
    A closed event (started, or past ``closes_hours_before_start``) gets a closed line; the button
    stays, since pressing it answers with the booking-closed text.
    """
    title_key = resource.title_field if resource is not None else "title"
    raw_title = item.data.get(title_key)
    title = str(raw_title) if raw_title not in (None, "") else "#" + formatting.to_persian_digits(item.id)
    lines = [f"📅 {title}"]
    start = formatting.parse_datetime(item.data.get(cap.start_field)) if cap.start_field else None
    if start is not None:
        lines.append(f"🗓 {formatting.format_datetime(start, tz)}")
    location = item.data.get("location")
    if location not in (None, ""):
        lines.append(f"📍 {location}")
    n = formatting.format_int(going)
    if capacity is None:
        lines.append(_fill(tx.EVENTS_GOING_LINE, going=n))
    else:
        lines.append(_fill(tx.EVENTS_GOING_OF_LINE, going=n, capacity=formatting.format_int(capacity)))
    if start is not None:
        hours = cap.closes_hours_before_start
        if now > start or (hours is not None and now > start - timedelta(hours=hours)):
            lines.append(tx.EVENTS_CARD_CLOSED)
    return "\n".join(lines), [[Ctx.button(words(cap.preset).book_button, cap, ACT_BOOK, item.id)]]


class BookingEngine(EngineBase):
    type: ClassVar[str] = "booking"

    # --- entry points ------------------------------------------------------------------------

    async def open(self, ctx: Ctx, cap: BookingCapability, view: str) -> None:
        if view == "mine":
            await self._mine(ctx, cap)
        else:
            await self._list(ctx, cap, 0)

    async def on_callback(self, ctx: Ctx, cap: BookingCapability, action: str, arg: str) -> None:
        if _is_events(cap) and ctx.event.chat_type == "group":
            await self._group_callback(ctx, cap, action, arg)
        elif action in FORM_ACTIONS:
            await forms.handle_callback(ctx, self, cap, action, arg)
        elif action == ACT_LIST:
            if _is_events(cap):
                await self._events_list_action(ctx, cap, arg)
            else:
                await self._list(ctx, cap, parse_int(arg) or 0)
        elif action == ACT_ITEM:
            await self._item(ctx, cap, parse_int(arg))
        elif action == ACT_BOOK:
            await self._book(ctx, cap, parse_int(arg))
        elif action == ACT_MINE:
            await self._mine(ctx, cap)
        elif action == ACT_CANCEL:
            await self._user_cancel(ctx, cap, parse_int(arg))
        else:
            ctx.stale()

    async def on_text(self, ctx: Ctx, cap: BookingCapability, text: str) -> None:
        await forms.handle_text(ctx, self, cap, text)

    async def on_form_done(
        self, ctx: Ctx, cap: BookingCapability, values: dict[str, Any], data: dict[str, Any]
    ) -> None:
        raw = data.get("item_id")
        item_id = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        decision = await self._decide(ctx, cap, item_id)  # state may have changed during the form
        await self._finish_book(ctx, cap, decision, values)

    async def owner_action(self, ctx: Ctx, cap: BookingCapability, record_id: int, action: str) -> None:
        if action != ACT_CANCEL:
            ctx.reject(cap, "owner_action", "not_allowed", tx.OWNER_ACTION_UNKNOWN, record_id=record_id)
            return
        booking = await self._active_booking(ctx, cap, record_id)
        if booking is None:
            ctx.reject(cap, "cancel", "not_found", tx.BOOKING_NOT_FOUND, record_id=record_id)
            return
        item = await self._get_item(ctx, cap, booking.item_id)
        title = self._title(ctx, cap, item, booking.item_id)
        ctx.reply(_fill(tx.OWNER_CANCEL_DONE, user=booking.actor_id or "—", title=title))
        if booking.actor_id is not None and booking.actor_id != ctx.actor.id:
            ctx.notify(
                booking.actor_id,
                "cancelled",
                _t(ctx, cap, "cancelled", title=title),
                [self._mine_row(cap), ctx.home_row()],
            )
        await self._cancel(ctx, cap, booking, item)
        ctx.outcome(cap, "cancel", "cancelled", record_id=booking.id)

    # --- lookups -----------------------------------------------------------------------------

    @staticmethod
    def _resource(ctx: Ctx, cap: BookingCapability) -> Resource | None:
        return ctx.spec.resource(cap.resource)

    @staticmethod
    async def _get_item(ctx: Ctx, cap: BookingCapability, item_id: int | None) -> Record | None:
        if item_id is None:
            return None
        return await ctx.store.get_record(cap.resource, item_id)

    @staticmethod
    async def _active_booking(ctx: Ctx, cap: BookingCapability, booking_id: int | None) -> Record | None:
        if booking_id is None:
            return None
        rec = await ctx.store.get_record(cap.key, booking_id)
        return rec if rec is not None and rec.status in ACTIVE else None

    def _title(self, ctx: Ctx, cap: BookingCapability, item: Record | None, item_id: int | None) -> str:
        resource = self._resource(ctx, cap)
        if item is None or resource is None:
            return "#" + formatting.to_persian_digits(item_id if item_id is not None else "?")
        return listing.record_title(ctx, resource, item)

    @staticmethod
    def _start(cap: BookingCapability, item: Record | None) -> datetime | None:
        if item is None or cap.start_field is None:
            return None
        return formatting.parse_datetime(item.data.get(cap.start_field))

    @staticmethod
    def _capacity(cap: BookingCapability, item: Record | None) -> int:
        if cap.capacity.mode == "fixed":
            return max(cap.capacity.value or 0, 0)
        if item is None or cap.capacity.field is None:
            return 0
        raw = item.data.get(cap.capacity.field)
        value: int | None = None
        if isinstance(raw, int) and not isinstance(raw, bool):
            value = raw
        elif isinstance(raw, float) and raw.is_integer():
            value = int(raw)
        elif isinstance(raw, str):
            s = formatting.to_ascii_digits(raw.strip())
            value = int(s) if s.isascii() and s.isdigit() else None
        return value if value is not None and value > 0 else 0

    def _booking_closed(self, ctx: Ctx, cap: BookingCapability, item: Record) -> bool:
        start = self._start(cap, item)
        if start is None:
            return False
        if ctx.now > start:
            return True
        hours = cap.closes_hours_before_start
        return hours is not None and ctx.now > start - timedelta(hours=hours)

    @staticmethod
    async def _confirmed_count(ctx: Ctx, cap: BookingCapability, item_id: int) -> int:
        return await ctx.store.count_records(cap.key, status_in=[CONFIRMED], item_id=item_id)

    @staticmethod
    async def _waitlist(ctx: Ctx, cap: BookingCapability, item_id: int) -> list[Record]:
        return await ctx.store.list_records(cap.key, status_in=[WAITLISTED], item_id=item_id)

    # --- buttons -----------------------------------------------------------------------------

    @staticmethod
    def _mine_row(cap: BookingCapability) -> list[Button]:
        return [Ctx.button(words(cap.preset).mine_button, cap, ACT_MINE)]

    @staticmethod
    def _item_row(cap: BookingCapability, item_id: int | None) -> list[Button]:
        label = words(cap.preset).list_button
        if item_id is None:
            return [Ctx.button(label, cap, ACT_LIST, 0)]
        return [Ctx.button(label, cap, ACT_LIST, 0), Ctx.button(common.BACK, cap, ACT_ITEM, item_id)]

    # --- views -------------------------------------------------------------------------------

    async def _visible_items(self, ctx: Ctx, cap: BookingCapability, resource: Resource) -> list[Record]:
        return await listing.load_items(
            ctx, resource, upcoming_only_field=cap.start_field, sort_field=cap.start_field
        )

    async def _list(self, ctx: Ctx, cap: BookingCapability, page: int) -> None:
        if _is_events(cap):
            await self._events_list(ctx, cap, None, page)
            return
        resource = self._resource(ctx, cap)
        if resource is None:
            ctx.stale()
            return
        items = await self._visible_items(ctx, cap, resource)
        head = chrome.heading(ctx, cap)
        if not items:
            ctx.reply(
                f"{head}\n{_t(ctx, cap, 'empty', title=cap.title)}", [self._mine_row(cap), ctx.home_row()]
            )
            return
        shown, page, pages = listing.paginate(items, page)
        rows: Rows = [
            [ctx.button(listing.truncate(listing.record_title(ctx, resource, r)), cap, ACT_ITEM, r.id)]
            for r in shown
        ]
        nav = listing.nav_row(cap, page, pages)
        if nav:
            rows.append(nav)
        rows.append(self._mine_row(cap))
        rows.append(ctx.home_row())
        lines = [head, _t(ctx, cap, "list_header", title=cap.title)]
        for r in shown:  # titles also in the text, so the reply reads without the buttons
            start = self._start(cap, r)
            when = _fill(tx.MINE_WHEN, when=ctx.fmt_datetime(start)) if start is not None else ""
            lines.append(_fill(tx.LIST_LINE, title=listing.record_title(ctx, resource, r), when=when))
        if pages > 1:
            lines.append(listing.page_indicator(page, pages))
        ctx.reply("\n".join(lines), rows)

    async def _item(self, ctx: Ctx, cap: BookingCapability, item_id: int | None) -> None:
        resource = self._resource(ctx, cap)
        item = await self._get_item(ctx, cap, item_id)
        if resource is None or item is None:
            ctx.stale()
            return
        confirmed = await self._confirmed_count(ctx, cap, item.id)
        remaining = max(self._capacity(cap, item) - confirmed, 0)
        title = listing.record_title(ctx, resource, item)
        text = _t(
            ctx,
            cap,
            "item_detail",
            title=title,
            details=listing.detail_lines(ctx, resource, item, self._detail_keys(cap)),
            remaining=formatting.format_int(remaining),
        )
        text = f"{chrome.heading(ctx, cap, 'main', title)}\n{text}".rstrip()
        w = words(cap.preset)
        extra: list[str] = []
        waitlist = await self._waitlist(ctx, cap, item.id)
        if cap.waitlist.enabled:
            extra.append(_fill(w.waitlist_count_line, count=formatting.format_int(len(waitlist))))
        mine = await ctx.store.list_records(cap.key, status_in=ACTIVE, actor_id=ctx.actor.id, item_id=item.id)
        for b in mine:
            extra.append(_fill(tx.MY_STATUS_LINE, status=self._status_label(cap, b, waitlist)))
        if self._booking_closed(ctx, cap, item):
            extra.append(w.closed_line)
        if extra:
            text += "\n\n" + "\n".join(extra)

        rows: Rows = [[ctx.button(w.book_button, cap, ACT_BOOK, item.id)]]
        rows += [[ctx.button(w.cancel_button, cap, ACT_CANCEL, b.id)] for b in mine]
        rows.append([chrome.to_route(chrome.route_of(ctx, cap)), ctx.home_button()])
        ctx.reply(text, rows)

    @staticmethod
    def _detail_keys(cap: BookingCapability) -> list[str]:
        """Detail fields of the item view; the events preset also shows start and category."""
        if not _is_events(cap):
            return cap.detail_fields
        extra = [k for k in (cap.start_field, cap.category_field) if k and k not in cap.detail_fields]
        return [*extra, *cap.detail_fields]

    @staticmethod
    def _status_label(cap: BookingCapability, booking: Record, waitlist: list[Record]) -> str:
        w: Words = words(cap.preset)
        if booking.status == WAITLISTED:
            position = next((i for i, x in enumerate(waitlist, 1) if x.id == booking.id), 0)
            return _fill(w.my_waitlist_status, position=formatting.format_int(position))
        return w.status_labels.get(booking.status or "", booking.status or "")

    async def _mine(self, ctx: Ctx, cap: BookingCapability) -> None:
        bookings = await ctx.store.list_records(cap.key, status_in=ACTIVE, actor_id=ctx.actor.id)
        head = chrome.heading(ctx, cap, "mine")
        if not bookings:
            ctx.reply(
                f"{head}\n{_t(ctx, cap, 'mine_empty')}",
                [[ctx.button(words(cap.preset).list_button, cap, ACT_LIST, 0)], ctx.home_row()],
            )
            return
        lines = [head, _t(ctx, cap, "mine_header")]
        rows: Rows = []
        waitlists: dict[int, list[Record]] = {}
        for b in bookings:
            item = await self._get_item(ctx, cap, b.item_id)
            title = self._title(ctx, cap, item, b.item_id)
            start = self._start(cap, item)
            when = _fill(tx.MINE_WHEN, when=ctx.fmt_datetime(start)) if start is not None else ""
            if b.status == WAITLISTED and b.item_id is not None and b.item_id not in waitlists:
                waitlists[b.item_id] = await self._waitlist(ctx, cap, b.item_id)
            status = self._status_label(cap, b, waitlists.get(b.item_id or -1, []))
            lines.append(_fill(tx.MINE_LINE, title=title, when=when, status=status))
            label = listing.truncate(_fill(words(cap.preset).cancel_button_for, title=title))
            rows.append([ctx.button(label, cap, ACT_CANCEL, b.id)])
        rows.append([ctx.button(words(cap.preset).list_button, cap, ACT_LIST, 0)])
        rows.append(ctx.home_row())
        ctx.reply("\n".join(lines), rows)

    # --- booking -----------------------------------------------------------------------------

    async def _decide(self, ctx: Ctx, cap: BookingCapability, item_id: int | None) -> Decision:
        item = await self._get_item(ctx, cap, item_id)
        if item is None or self._resource(ctx, cap) is None:
            return Decision(None, reason="not_found", text=words(cap.preset).item_not_found)
        title = self._title(ctx, cap, item, item.id)
        if self._booking_closed(ctx, cap, item):
            return Decision(item, reason="booking_closed", text=_t(ctx, cap, "closed", title=title))
        actor = ctx.actor.id
        if cap.one_active_per_user_per_item and await ctx.store.count_records(
            cap.key, status_in=ACTIVE, actor_id=actor, item_id=item.id
        ):
            return Decision(item, reason="duplicate", text=_t(ctx, cap, "duplicate", title=title))
        limit = cap.max_active_per_user
        if limit is not None and (
            await ctx.store.count_records(cap.key, status_in=ACTIVE, actor_id=actor) >= limit
        ):
            return Decision(
                item, reason="user_limit", text=_t(ctx, cap, "user_limit", limit=formatting.format_int(limit))
            )
        if await self._confirmed_count(ctx, cap, item.id) < self._capacity(cap, item):
            return Decision(item, status=CONFIRMED)
        if cap.waitlist.enabled:
            return Decision(item, status=WAITLISTED)
        return Decision(item, reason="capacity_full", text=_t(ctx, cap, "full", title=title))

    async def _book(self, ctx: Ctx, cap: BookingCapability, item_id: int | None) -> None:
        decision = await self._decide(ctx, cap, item_id)
        if decision.status is not None and decision.item is not None and cap.form_fields:
            intro = _fill(
                words(cap.preset).form_intro, title=self._title(ctx, cap, decision.item, decision.item.id)
            )
            await forms.start(ctx, self, cap, data={"item_id": decision.item.id}, intro=intro)
            return
        await self._finish_book(ctx, cap, decision, {})

    async def _finish_book(
        self,
        ctx: Ctx,
        cap: BookingCapability,
        decision: Decision,
        values: dict[str, Any],
        *,
        quiet: bool = False,
    ) -> None:
        """``quiet``: group chat, answer with one plain text (no buttons, never an edit)."""
        item = decision.item
        if decision.status is None or item is None:
            reason: ReasonCode = decision.reason or "not_found"
            if quiet:
                ctx.reply(decision.text, edit=False)
                ctx.outcome(cap, "book", "rejected", reason=reason)
                return
            rows: Rows = []
            if reason in ("duplicate", "user_limit"):
                rows.append(self._mine_row(cap))
            rows.append(self._item_row(cap, item.id if item is not None else None))
            rows.append(ctx.home_row())
            ctx.reject(cap, "book", reason, decision.text, rows)
            return
        booking = await ctx.create_record(cap.key, values, status=decision.status, item_id=item.id)
        title = self._title(ctx, cap, item, item.id)
        if decision.status == CONFIRMED:
            text = _t(ctx, cap, "confirmed", title=title)
        else:
            position = len(await self._waitlist(ctx, cap, item.id))
            text = _t(ctx, cap, "waitlisted", title=title, position=formatting.format_int(position))
        if quiet:
            ctx.reply(text, edit=False)
        else:
            ctx.reply(text, [self._mine_row(cap), self._item_row(cap, item.id), ctx.home_row()])
        notice = "booked" if decision.status == CONFIRMED else "waitlisted"
        if notice in cap.notify_owner_on:
            key = "owner_booked" if notice == "booked" else "owner_waitlisted"
            ctx.notify_owner(notice, _t(ctx, cap, key, title=title, user=ctx.actor.display_name))
        ctx.outcome(
            cap, "book", "confirmed" if decision.status == CONFIRMED else "waitlisted", record_id=booking.id
        )

    # --- events preset ---------------------------------------------------------------------

    async def _group_callback(self, ctx: Ctx, cap: BookingCapability, action: str, arg: str) -> None:
        """Group chat: only ``book`` (without form fields) acts; everything else points to the
        private chat. One short text either way."""
        if action == ACT_BOOK and not cap.form_fields:
            decision = await self._decide(ctx, cap, parse_int(arg))
            await self._finish_book(ctx, cap, decision, {}, quiet=True)
        else:
            ctx.reply(tx.EVENTS_GROUP_PRIVATE, edit=False)

    @staticmethod
    def _categories(resource: Resource, cap: BookingCapability) -> list[str]:
        field = listing.field_of(resource, cap.category_field)
        return list(field.choices or []) if field is not None else []

    @staticmethod
    def _subs_collection(cap: BookingCapability) -> str:
        return f"{cap.key}.subs"

    async def _events_list_action(self, ctx: Ctx, cap: BookingCapability, arg: str) -> None:
        """``list`` argument of the events preset: ``<page>``, ``c<idx>.<page>``, ``sub``,
        ``sub.<idx>`` (module docstring)."""
        arg = formatting.to_ascii_digits(arg.strip())
        if arg == "sub" or arg.startswith("sub."):
            if arg == "sub":
                await self._subs(ctx, cap)
            else:
                await self._toggle_sub(ctx, cap, parse_int(arg[4:]))
            return
        if arg.startswith("c"):
            idx, _, page = arg[1:].partition(".")
            await self._events_list(ctx, cap, parse_int(idx), parse_int(page) or 0)
            return
        await self._events_list(ctx, cap, None, parse_int(arg) or 0)

    @staticmethod
    def _events_nav(cap: BookingCapability, page: int, pages: int, cat_idx: int | None) -> list[Button]:
        prefix = "" if cat_idx is None else f"c{cat_idx}."
        row: list[Button] = []
        if page > 0:
            row.append(Ctx.button(common.PREVIOUS, cap, ACT_LIST, f"{prefix}{page - 1}"))
        if page < pages - 1:
            row.append(Ctx.button(common.NEXT, cap, ACT_LIST, f"{prefix}{page + 1}"))
        return row

    async def _events_list(self, ctx: Ctx, cap: BookingCapability, cat_idx: int | None, page: int) -> None:
        resource = self._resource(ctx, cap)
        if resource is None:
            ctx.stale()
            return
        categories = self._categories(resource, cap)
        if cat_idx is not None and cat_idx >= len(categories):
            cat_idx = None  # the category list changed since the button was shown
        items = await self._visible_items(ctx, cap, resource)
        if cat_idx is not None and cap.category_field:
            items = [r for r in items if r.data.get(cap.category_field) == categories[cat_idx]]
        shown, page, pages = listing.paginate(items, page)
        rows: Rows = [
            [ctx.button(listing.truncate(listing.record_title(ctx, resource, r)), cap, ACT_ITEM, r.id)]
            for r in shown
        ]
        nav = self._events_nav(cap, page, pages, cat_idx)
        if nav:
            rows.append(nav)
        if categories:
            rows.extend(self._filter_rows(cap, categories, cat_idx))
            rows.append([ctx.button(tx.EVENTS_SUBS_BUTTON, cap, ACT_LIST, "sub")])
        rows.append(self._mine_row(cap))
        rows.append(ctx.home_row())
        head = chrome.heading(ctx, cap)
        if not items:
            ctx.reply(f"{head}\n{_t(ctx, cap, 'empty', title=cap.title)}", rows)
            return
        lines = [head, _t(ctx, cap, "list_header", title=cap.title)]
        if cat_idx is not None:
            lines.append(_fill(tx.EVENTS_CATEGORY_LINE, category=categories[cat_idx]))
        for r in shown:
            lines.append(await self._events_line(ctx, cap, resource, r))
        if pages > 1:
            lines.append(listing.page_indicator(page, pages))
        ctx.reply("\n".join(lines), rows)

    @staticmethod
    def _filter_rows(cap: BookingCapability, categories: list[str], selected: int | None) -> Rows:
        """``[همه] [cat]...`` in rows of three; the selected one is marked with a check."""
        mark = tx.EVENTS_SUB_ON + " "
        buttons = [
            Ctx.button((mark if selected is None else "") + tx.EVENTS_ALL_CATEGORIES, cap, ACT_LIST, 0)
        ]
        for i, cat in enumerate(categories):
            label = listing.truncate((mark if selected == i else "") + cat, 30)
            buttons.append(Ctx.button(label, cap, ACT_LIST, f"c{i}.0"))
        return [buttons[i : i + 3] for i in range(0, len(buttons), 3)]

    async def _events_line(self, ctx: Ctx, cap: BookingCapability, resource: Resource, item: Record) -> str:
        """``• title — date | category | going/capacity``."""
        parts: list[str] = []
        start = self._start(cap, item)
        if start is not None:
            parts.append(ctx.fmt_datetime(start))
        category = item.data.get(cap.category_field) if cap.category_field else None
        if category not in (None, ""):
            parts.append(str(category))
        going = formatting.format_int(await self._confirmed_count(ctx, cap, item.id))
        capacity = self._capacity(cap, item)
        parts.append(
            _fill(tx.EVENTS_GOING_OF_LINE, going=going, capacity=formatting.format_int(capacity))
            if capacity > 0
            else _fill(tx.EVENTS_GOING_LINE, going=going)
        )
        title = listing.record_title(ctx, resource, item)
        return f"• {title} — " + " | ".join(parts)

    async def _subs(self, ctx: Ctx, cap: BookingCapability) -> None:
        resource = self._resource(ctx, cap)
        categories = self._categories(resource, cap) if resource is not None else []
        if not categories:
            await self._events_list(ctx, cap, None, 0)
            return
        subscribed = {
            r.data.get("category")
            for r in await ctx.store.list_records(self._subs_collection(cap), actor_id=ctx.actor.id)
        }
        rows: Rows = [
            [
                ctx.button(
                    listing.truncate(f"{tx.EVENTS_SUB_ON if c in subscribed else tx.EVENTS_SUB_OFF} {c}"),
                    cap,
                    ACT_LIST,
                    f"sub.{i}",
                )
            ]
            for i, c in enumerate(categories)
        ]
        rows.append(self._item_row(cap, None))
        rows.append(ctx.home_row())
        head = chrome.heading(ctx, cap, "main", tx.EVENTS_SUBS_BUTTON)
        ctx.reply(f"{head}\n{_t(ctx, cap, 'subs_header')}", rows)

    async def _toggle_sub(self, ctx: Ctx, cap: BookingCapability, idx: int | None) -> None:
        """Create or delete the actor's ``<cap.key>.subs`` record of category ``idx``, then show
        the subscriptions again."""
        resource = self._resource(ctx, cap)
        categories = self._categories(resource, cap) if resource is not None else []
        if idx is not None and idx < len(categories):
            collection = self._subs_collection(cap)
            existing = [
                r
                for r in await ctx.store.list_records(collection, actor_id=ctx.actor.id)
                if r.data.get("category") == categories[idx]
            ]
            if existing:
                for r in existing:
                    await ctx.delete_record(collection, r.id)
            else:
                await ctx.create_record(collection, {"category": categories[idx]})
        await self._subs(ctx, cap)

    # --- cancellation ------------------------------------------------------------------------

    async def _user_cancel(self, ctx: Ctx, cap: BookingCapability, booking_id: int | None) -> None:
        booking = await self._active_booking(ctx, cap, booking_id)
        if booking is None or booking.actor_id != ctx.actor.id:
            ctx.reject(
                cap,
                "cancel",
                "not_found",
                tx.BOOKING_NOT_FOUND,
                [self._mine_row(cap), ctx.home_row()],
                record_id=booking_id,
            )
            return
        item = await self._get_item(ctx, cap, booking.item_id)
        title = self._title(ctx, cap, item, booking.item_id)
        refusal: tuple[ReasonCode, str] | None = None
        deadline = cap.cancellation.deadline_hours
        start = self._start(cap, item)
        if not cap.cancellation.enabled:
            refusal = ("cancellation_disabled", _t(ctx, cap, "cancellation_disabled", title=title))
        elif deadline is not None and start is not None and ctx.now > start - timedelta(hours=deadline):
            refusal = (
                "cancel_deadline_passed",
                _t(ctx, cap, "cancel_deadline_passed", title=title, hours=formatting.format_int(deadline)),
            )
        if refusal is not None:
            rows = [self._mine_row(cap), ctx.home_row()]
            ctx.reject(cap, "cancel", refusal[0], refusal[1], rows, record_id=booking.id)
            return
        ctx.reply(_t(ctx, cap, "cancelled", title=title), [self._mine_row(cap), ctx.home_row()])
        if "cancelled" in cap.notify_owner_on:
            ctx.notify_owner(
                "cancelled", _t(ctx, cap, "owner_cancelled", title=title, user=ctx.actor.display_name)
            )
        await self._cancel(ctx, cap, booking, item)
        ctx.outcome(cap, "cancel", "cancelled", record_id=booking.id)

    async def _cancel(self, ctx: Ctx, cap: BookingCapability, booking: Record, item: Record | None) -> None:
        """Set ``cancelled`` and apply the promotion rule. Promotion notices are appended here, so
        callers send their reply and cancel notices first (message order: reply, cancel notice,
        promotion notices)."""
        await ctx.update_record(cap.key, booking.id, status=CANCELLED)
        if booking.status == CONFIRMED and booking.item_id is not None:
            await self._promote(ctx, cap, booking.item_id, item)

    async def _promote(self, ctx: Ctx, cap: BookingCapability, item_id: int, item: Record | None) -> None:
        if not (cap.waitlist.enabled and cap.waitlist.auto_promote):
            return
        capacity = self._capacity(cap, item)
        title = self._title(ctx, cap, item, item_id)
        while await self._confirmed_count(ctx, cap, item_id) < capacity:
            nxt = await ctx.store.list_records(
                cap.key, status_in=[WAITLISTED], item_id=item_id, order_by="id", limit=1
            )
            if not nxt:
                return
            promoted = await ctx.update_record(cap.key, nxt[0].id, status=CONFIRMED)
            if "promoted" not in cap.notify_user_on or promoted.actor_id is None:
                continue
            text = _t(ctx, cap, "promoted", title=title)
            if promoted.actor_id == ctx.actor.id:
                ctx.reply(text, [self._mine_row(cap), ctx.home_row()], edit=False)
            else:
                ctx.notify(promoted.actor_id, "promoted", text, [self._mine_row(cap), ctx.home_row()])


ENGINE = BookingEngine()
