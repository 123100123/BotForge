"""``booking`` engine: capacity, waitlist, cancellation and automatic promotion (WP2).

Data model: bookable items are records of resource ``cap.resource``; bookings are records of
collection ``cap.key`` with ``item_id`` (item record id), ``actor_id`` (customer), ``status`` in
{confirmed, waitlisted, cancelled} and ``data`` = cleaned form values. Active = confirmed or
waitlisted.

Navigation (drivers locate buttons by parsed callback action/arg, never by label):
  open main / ``list:<page>``  items (start not passed when ``start_field`` is set), one
                               ``item:<id>`` button each; nav row; ``mine``; home
  ``item:<id>``                detail; ALWAYS ``book:<id>``; plus ``cancel:<booking id>`` for each
                               of the actor's active bookings on the item; back (list); home
  ``book:<id>``                checks -> rejected Outcome, or form (``data={"item_id": id}``) whose
                               completion re-runs every check, or immediate booking
  open mine / ``mine``         the actor's active bookings, one ``cancel:<booking id>`` each
  ``cancel:<booking id>``      own active booking only (else ``not_found``); cancellation rules;
                               after the item has started -> cancel_deadline_passed even
                               without ``deadline_hours`` (the event is over: no late promotion)
  owner_action(id, "cancel")   any active booking; ignores ``cancellation``; same promotion rule

Book checks, in order: item missing -> not_found; now > start, or now > start -
closes_hours_before_start -> booking_closed; active booking on the item and
one_active_per_user_per_item -> duplicate; active bookings in this capability on items that
have not started >= max_active_per_user -> user_limit; confirmed < capacity -> confirmed;
waitlist -> waitlisted; else capacity_full. Boundaries: exactly at a cutoff or deadline the action
is still allowed.

Promotion: after a *confirmed* booking is cancelled, if the waitlist is enabled with
auto_promote, waitlisted bookings on the item are confirmed oldest first (lowest id) while
confirmed < capacity. Capacity lowered below the confirmed count therefore promotes nobody.

All times come from ``ctx.now``; stored datetimes are UTC ISO strings. The engine is not safe
against two events for the same bot running concurrently: the adapter must serialize them.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, ClassVar

from app.botspec.models import BookingCapability, Resource
from app.botspec.text_keys import fill_text
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
from app.runtime.engines.base import EngineBase
from app.runtime.store import Record
from app.runtime.texts import booking as tx
from app.runtime.texts import common

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


class BookingEngine(EngineBase):
    type: ClassVar[str] = "booking"

    # --- entry points ------------------------------------------------------------------------

    async def open(self, ctx: Ctx, cap: BookingCapability, view: str) -> None:
        if view == "mine":
            await self._mine(ctx, cap)
        else:
            await self._list(ctx, cap, 0)

    async def on_callback(self, ctx: Ctx, cap: BookingCapability, action: str, arg: str) -> None:
        if action in FORM_ACTIONS:
            await forms.handle_callback(ctx, self, cap, action, arg)
        elif action == ACT_LIST:
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
                ctx.t(cap, "cancelled", title=title),
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

    def _started(self, ctx: Ctx, cap: BookingCapability, item: Record | None) -> bool:
        start = self._start(cap, item)
        return start is not None and ctx.now > start

    async def _upcoming_active_count(self, ctx: Ctx, cap: BookingCapability, actor_id: str) -> int:
        """Active bookings of ``actor_id`` that still hold a place. Bookings on an item that has
        started are history and no longer count towards ``max_active_per_user``."""
        bookings = await ctx.store.list_records(cap.key, status_in=ACTIVE, actor_id=actor_id)
        if cap.start_field is None:
            return len(bookings)
        count = 0
        for b in bookings:
            if not self._started(ctx, cap, await self._get_item(ctx, cap, b.item_id)):
                count += 1
        return count

    @staticmethod
    async def _confirmed_count(ctx: Ctx, cap: BookingCapability, item_id: int) -> int:
        return await ctx.store.count_records(cap.key, status_in=[CONFIRMED], item_id=item_id)

    @staticmethod
    async def _waitlist(ctx: Ctx, cap: BookingCapability, item_id: int) -> list[Record]:
        return await ctx.store.list_records(cap.key, status_in=[WAITLISTED], item_id=item_id)

    # --- buttons -----------------------------------------------------------------------------

    @staticmethod
    def _mine_row(cap: BookingCapability) -> list[Button]:
        return [Ctx.button(tx.MINE_BUTTON, cap, ACT_MINE)]

    @staticmethod
    def _item_row(cap: BookingCapability, item_id: int | None) -> list[Button]:
        if item_id is None:
            return [Ctx.button(tx.LIST_BUTTON, cap, ACT_LIST, 0)]
        return [Ctx.button(tx.LIST_BUTTON, cap, ACT_LIST, 0), Ctx.button(common.BACK, cap, ACT_ITEM, item_id)]

    # --- views -------------------------------------------------------------------------------

    async def _visible_items(self, ctx: Ctx, cap: BookingCapability, resource: Resource) -> list[Record]:
        return await listing.load_items(
            ctx, resource, upcoming_only_field=cap.start_field, sort_field=cap.start_field
        )

    async def _list(self, ctx: Ctx, cap: BookingCapability, page: int) -> None:
        resource = self._resource(ctx, cap)
        if resource is None:
            ctx.stale()
            return
        items = await self._visible_items(ctx, cap, resource)
        if not items:
            ctx.reply(ctx.t(cap, "empty", title=cap.title), [self._mine_row(cap), ctx.home_row()])
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
        lines = [ctx.t(cap, "list_header", title=cap.title)]
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
        text = ctx.t(
            cap,
            "item_detail",
            title=listing.record_title(ctx, resource, item),
            details=listing.detail_lines(ctx, resource, item, cap.detail_fields),
            remaining=formatting.format_int(remaining),
        )
        extra: list[str] = []
        waitlist = await self._waitlist(ctx, cap, item.id)
        if cap.waitlist.enabled:
            extra.append(_fill(tx.WAITLIST_COUNT_LINE, count=formatting.format_int(len(waitlist))))
        mine = await ctx.store.list_records(cap.key, status_in=ACTIVE, actor_id=ctx.actor.id, item_id=item.id)
        for b in mine:
            extra.append(_fill(tx.MY_STATUS_LINE, status=self._status_label(b, waitlist)))
        if self._booking_closed(ctx, cap, item):
            extra.append(tx.CLOSED_LINE)
        if extra:
            text += "\n\n" + "\n".join(extra)

        rows: Rows = [[ctx.button(tx.BOOK_BUTTON, cap, ACT_BOOK, item.id)]]
        rows += [[ctx.button(tx.CANCEL_BUTTON, cap, ACT_CANCEL, b.id)] for b in mine]
        page = listing.page_of(await self._visible_items(ctx, cap, resource), item.id)
        rows.append(ctx.back_home_row(cap, ACT_LIST, page))
        ctx.reply(text, rows)

    @staticmethod
    def _status_label(booking: Record, waitlist: list[Record]) -> str:
        if booking.status == WAITLISTED:
            position = next((i for i, w in enumerate(waitlist, 1) if w.id == booking.id), 0)
            return _fill(tx.MY_WAITLIST_STATUS, position=formatting.format_int(position))
        return tx.STATUS_LABELS.get(booking.status or "", booking.status or "")

    async def _mine(self, ctx: Ctx, cap: BookingCapability) -> None:
        bookings = await ctx.store.list_records(cap.key, status_in=ACTIVE, actor_id=ctx.actor.id)
        if not bookings:
            ctx.reply(
                ctx.t(cap, "mine_empty"),
                [[ctx.button(tx.LIST_BUTTON, cap, ACT_LIST, 0)], ctx.home_row()],
            )
            return
        lines = [ctx.t(cap, "mine_header")]
        rows: Rows = []
        waitlists: dict[int, list[Record]] = {}
        for b in bookings:
            item = await self._get_item(ctx, cap, b.item_id)
            title = self._title(ctx, cap, item, b.item_id)
            start = self._start(cap, item)
            when = _fill(tx.MINE_WHEN, when=ctx.fmt_datetime(start)) if start is not None else ""
            if b.status == WAITLISTED and b.item_id is not None and b.item_id not in waitlists:
                waitlists[b.item_id] = await self._waitlist(ctx, cap, b.item_id)
            if self._started(ctx, cap, item):
                status = tx.STARTED_STATUS
            else:
                status = self._status_label(b, waitlists.get(b.item_id or -1, []))
            lines.append(_fill(tx.MINE_LINE, title=title, when=when, status=status))
            label = listing.truncate(_fill(tx.CANCEL_BUTTON_FOR, title=title))
            rows.append([ctx.button(label, cap, ACT_CANCEL, b.id)])
        rows.append([ctx.button(tx.LIST_BUTTON, cap, ACT_LIST, 0)])
        rows.append(ctx.home_row())
        ctx.reply("\n".join(lines), rows)

    # --- booking -----------------------------------------------------------------------------

    async def _decide(self, ctx: Ctx, cap: BookingCapability, item_id: int | None) -> Decision:
        item = await self._get_item(ctx, cap, item_id)
        if item is None or self._resource(ctx, cap) is None:
            return Decision(None, reason="not_found", text=tx.ITEM_NOT_FOUND)
        title = self._title(ctx, cap, item, item.id)
        if self._booking_closed(ctx, cap, item):
            return Decision(item, reason="booking_closed", text=ctx.t(cap, "closed", title=title))
        actor = ctx.actor.id
        if cap.one_active_per_user_per_item and await ctx.store.count_records(
            cap.key, status_in=ACTIVE, actor_id=actor, item_id=item.id
        ):
            return Decision(item, reason="duplicate", text=ctx.t(cap, "duplicate", title=title))
        limit = cap.max_active_per_user
        if limit is not None and await self._upcoming_active_count(ctx, cap, actor) >= limit:
            return Decision(
                item, reason="user_limit", text=ctx.t(cap, "user_limit", limit=formatting.format_int(limit))
            )
        if await self._confirmed_count(ctx, cap, item.id) < self._capacity(cap, item):
            return Decision(item, status=CONFIRMED)
        if cap.waitlist.enabled:
            return Decision(item, status=WAITLISTED)
        return Decision(item, reason="capacity_full", text=ctx.t(cap, "full", title=title))

    async def _book(self, ctx: Ctx, cap: BookingCapability, item_id: int | None) -> None:
        decision = await self._decide(ctx, cap, item_id)
        if decision.status is not None and decision.item is not None and cap.form_fields:
            intro = _fill(tx.FORM_INTRO, title=self._title(ctx, cap, decision.item, decision.item.id))
            await forms.start(ctx, self, cap, data={"item_id": decision.item.id}, intro=intro)
            return
        await self._finish_book(ctx, cap, decision, {})

    async def _finish_book(
        self,
        ctx: Ctx,
        cap: BookingCapability,
        decision: Decision,
        values: dict[str, Any],
    ) -> None:
        item = decision.item
        if decision.status is None or item is None:
            reason: ReasonCode = decision.reason or "not_found"
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
            text = ctx.t(cap, "confirmed", title=title)
        else:
            position = len(await self._waitlist(ctx, cap, item.id))
            text = ctx.t(cap, "waitlisted", title=title, position=formatting.format_int(position))
        ctx.reply(text, [self._mine_row(cap), self._item_row(cap, item.id), ctx.home_row()])
        notice = "booked" if decision.status == CONFIRMED else "waitlisted"
        if notice in cap.notify_owner_on:
            key = "owner_booked" if notice == "booked" else "owner_waitlisted"
            ctx.notify_owner(notice, ctx.t(cap, key, title=title, user=ctx.actor.display_name))
        ctx.outcome(
            cap, "book", "confirmed" if decision.status == CONFIRMED else "waitlisted", record_id=booking.id
        )

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
            refusal = ("cancellation_disabled", ctx.t(cap, "cancellation_disabled", title=title))
        elif deadline is not None and start is not None and ctx.now > start - timedelta(hours=deadline):
            refusal = (
                "cancel_deadline_passed",
                ctx.t(cap, "cancel_deadline_passed", title=title, hours=formatting.format_int(deadline)),
            )
        elif start is not None and ctx.now > start:
            refusal = ("cancel_deadline_passed", _fill(tx.CANCEL_AFTER_START, title=title))
        if refusal is not None:
            rows = [self._mine_row(cap), ctx.home_row()]
            ctx.reject(cap, "cancel", refusal[0], refusal[1], rows, record_id=booking.id)
            return
        ctx.reply(ctx.t(cap, "cancelled", title=title), [self._mine_row(cap), ctx.home_row()])
        if "cancelled" in cap.notify_owner_on:
            ctx.notify_owner(
                "cancelled", ctx.t(cap, "owner_cancelled", title=title, user=ctx.actor.display_name)
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
            text = ctx.t(cap, "promoted", title=title)
            if promoted.actor_id == ctx.actor.id:
                ctx.reply(text, [self._mine_row(cap), ctx.home_row()], edit=False)
            else:
                ctx.notify(promoted.actor_id, "promoted", text, [self._mine_row(cap), ctx.home_row()])


ENGINE = BookingEngine()
