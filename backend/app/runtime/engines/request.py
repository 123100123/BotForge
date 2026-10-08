"""``request`` engine: form-based requests with owner-driven status changes (WP8).

Data model: requests are records of collection ``cap.key`` with ``actor_id`` (customer), ``status``
(a key of ``cap.statuses``, starting at ``cap.initial_status``), ``item_id`` (the picked record of
``cap.item_resource``, when set) and ``data`` = cleaned form values.

Navigation (drivers locate buttons by parsed callback action/arg, never by label):
  open main            intro; ``new`` button; ``mine`` button; home. For an actor who may run the
                       capability's owner actions (``roles.can_run_owner_actions``: staff and
                       managers, the owner included) the staff queue instead: the newest
                       ``QUEUE_LIMIT`` requests waiting for an owner action (a status some owner
                       action starts from), each with one ``own:<id>.<action key>`` button per
                       action allowed from its status, then the same ``new``/``mine``/home rows
  ``new[:<page>]``     with ``item_resource``: paginated items, one ``pick:<item id>`` each;
                       without: starts the form directly
  ``pick:<item id>``   starts the form, the item id is kept in the form ``data``
  form completion      creates the request (item re-checked), replies with the reference and the
                       status, Outcome submit/submitted, notifies the owner (``submitted``) with one
                       ``own:<id>.<action key>`` button per owner action allowed FROM the initial status
  open mine / ``mine`` the actor's requests, newest first
  ``own:<id>.<key>``   owner action (Telegram inline button or web ``admin`` event)

Owner action buttons always follow the record's *current* status; a stale button gets a
``not_allowed`` rejection naming the current status (never a crash). The runtime has already
checked ``roles.can_run_owner_actions`` before ``owner_action`` is reached. Notifications of new
requests still go to the owner only (``notify_owner``); staff see them in the queue.

All times come from ``ctx.now``. Like the booking engine it is not safe against two events for the
same bot running concurrently: the adapter must serialize them.
"""

from typing import Any, ClassVar

from app.botspec.models import FieldDef, OwnerAction, RequestCapability, Resource
from app.botspec.text_keys import fill_text
from app.roles import can_run_owner_actions
from app.runtime import formatting, forms, listing
from app.runtime.callbacks import (
    ACT_MINE,
    ACT_NEW,
    ACT_OWN,
    ACT_PICK,
    FORM_ACTIONS,
    CallbackError,
    make_callback,
)
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx, parse_int
from app.runtime.engines import chrome
from app.runtime.engines.base import EngineBase
from app.runtime.store import Record
from app.runtime.texts import request as tx

Rows = list[list[Button]]

# Staff queue (roles). Its fixed strings live here rather than in runtime/texts/request.py, which
# another work package owns; like those constants they are not overridable.
QUEUE_LIMIT = 5  # requests shown, newest first; the web admin lists every request
QUEUE_VALUE_CHARS = 80  # each form value is cut to this length in the queue
QUEUE_HEADER = "{title}\nدرخواست‌های در انتظار رسیدگی:"
QUEUE_EMPTY = "{title}\nدرخواستی در انتظار رسیدگی نیست."
QUEUE_DETAIL_LINE = "   {label}: {value}"
QUEUE_MORE = "… و {count} درخواست دیگر (فهرست کامل در پنل مدیریت)."
QUEUE_BUTTON = "{action} (کد {id})"


def _fill(template: str, **values: object) -> str:
    return fill_text(template, {k: str(v) for k, v in values.items()})


def _ref(record_id: int) -> str:
    return formatting.to_persian_digits(record_id)


class RequestEngine(EngineBase):
    type: ClassVar[str] = "request"

    # --- entry points ------------------------------------------------------------------------

    async def open(self, ctx: Ctx, cap: RequestCapability, view: str) -> None:
        if view == "mine":
            await self._mine(ctx, cap)
        elif can_run_owner_actions(cap, ctx.actor):
            await self._queue(ctx, cap)
        else:
            self._main(ctx, cap)

    async def on_callback(self, ctx: Ctx, cap: RequestCapability, action: str, arg: str) -> None:
        if action in FORM_ACTIONS:
            await forms.handle_callback(ctx, self, cap, action, arg)
        elif action == ACT_NEW:
            await self._new(ctx, cap, parse_int(arg) or 0)
        elif action == ACT_PICK:
            await self._pick(ctx, cap, parse_int(arg))
        elif action == ACT_MINE:
            await self._mine(ctx, cap)
        else:
            ctx.stale()

    async def on_text(self, ctx: Ctx, cap: RequestCapability, text: str) -> None:
        await forms.handle_text(ctx, self, cap, text)

    async def on_form_done(
        self, ctx: Ctx, cap: RequestCapability, values: dict[str, Any], data: dict[str, Any]
    ) -> None:
        item: Record | None = None
        if cap.item_resource is not None:
            raw = data.get("item_id")
            item_id = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
            item = await self._get_item(ctx, cap, item_id)  # state may have changed during the form
            if item is None:
                ctx.reject(cap, "submit", "not_found", tx.ITEM_NOT_FOUND, self._back_rows(ctx, cap))
                return
        request = await ctx.create_record(
            cap.key, values, status=cap.initial_status, item_id=item.id if item is not None else None
        )
        confirmation = ctx.t(cap, "submitted", title=cap.title, id=_ref(request.id))
        status_line = _fill(tx.STATUS_LINE, status=self._status_label(cap, request.status))
        ctx.reply(f"{confirmation}\n{status_line}", [self._mine_row(cap), ctx.home_row()])
        if "submitted" in cap.notify_owner_on:
            ctx.notify_owner(
                "submitted",
                ctx.t(
                    cap,
                    "owner_submitted",
                    title=cap.title,
                    id=_ref(request.id),
                    user=ctx.actor.display_name,
                    details=self._details(ctx, cap, values, item),
                ),
                self._owner_rows(cap, request),
            )
        ctx.outcome(cap, "submit", "submitted", record_id=request.id)

    async def owner_action(self, ctx: Ctx, cap: RequestCapability, record_id: int, action: str) -> None:
        request = await ctx.store.get_record(cap.key, record_id)
        if request is None:
            ctx.reject(cap, "owner_action", "not_found", tx.REQUEST_NOT_FOUND, record_id=record_id)
            return
        owner_action = next((a for a in cap.owner_actions if a.key == action), None)
        if owner_action is None:
            ctx.reject(
                cap,
                "owner_action",
                "not_allowed",
                ctx.t(cap, "not_allowed"),
                self._owner_rows(cap, request),
                record_id=record_id,
            )
            return
        if request.status not in owner_action.from_statuses:
            text = _fill(tx.NOT_ALLOWED_FROM, status=self._status_label(cap, request.status))
            ctx.reject(
                cap, "owner_action", "not_allowed", text, self._owner_rows(cap, request), record_id=record_id
            )
            return
        updated = await ctx.update_record(cap.key, request.id, status=owner_action.to_status)
        label = self._status_label(cap, updated.status)
        ctx.reply(
            ctx.t(cap, "action_done", id=_ref(updated.id), status=label), self._owner_rows(cap, updated)
        )
        if "status_changed" in cap.notify_user_on and updated.actor_id not in (None, ctx.actor.id):
            ctx.notify(
                updated.actor_id,
                "status_changed",
                ctx.t(cap, "status_changed", title=cap.title, id=_ref(updated.id), status=label),
                [self._mine_row(cap), ctx.home_row()],
            )
        ctx.outcome(cap, "owner_action", "ok", record_id=updated.id)

    # --- lookups -----------------------------------------------------------------------------

    @staticmethod
    def _resource(ctx: Ctx, cap: RequestCapability) -> Resource | None:
        return ctx.spec.resource(cap.item_resource) if cap.item_resource is not None else None

    async def _get_item(self, ctx: Ctx, cap: RequestCapability, item_id: int | None) -> Record | None:
        if item_id is None or cap.item_resource is None or self._resource(ctx, cap) is None:
            return None
        return await ctx.store.get_record(cap.item_resource, item_id)

    def _item_title(self, ctx: Ctx, cap: RequestCapability, item: Record | None, item_id: int | None) -> str:
        resource = self._resource(ctx, cap)
        if item is None or resource is None:
            return "#" + formatting.to_persian_digits(item_id if item_id is not None else "?")
        return listing.record_title(ctx, resource, item)

    @staticmethod
    def _status_label(cap: RequestCapability, status: str | None) -> str:
        return next((s.label for s in cap.statuses if s.key == status), status or "—")

    def _details(self, ctx: Ctx, cap: RequestCapability, values: dict[str, Any], item: Record | None) -> str:
        lines = []
        if item is not None:
            lines.append(_fill(tx.ITEM_DETAIL_LINE, item=self._item_title(ctx, cap, item, item.id)))
        fields: list[FieldDef] = cap.form_fields
        lines += [f"{f.label}: {ctx.fmt(f, values.get(f.key))}" for f in fields]
        return "\n".join(lines)

    # --- buttons -----------------------------------------------------------------------------

    @staticmethod
    def _mine_row(cap: RequestCapability) -> list[Button]:
        return [Ctx.button(tx.MINE_BUTTON, cap, ACT_MINE)]

    @staticmethod
    def _new_row(cap: RequestCapability) -> list[Button]:
        return [Ctx.button(tx.NEW_BUTTON, cap, ACT_NEW)]

    def _entry_rows(self, ctx: Ctx, cap: RequestCapability) -> Rows:
        """«درخواست جدید» and «درخواست‌های من» side by side, then Home."""
        return [[*self._new_row(cap), *self._mine_row(cap)], ctx.home_row()]

    def _back_rows(self, ctx: Ctx, cap: RequestCapability) -> Rows:
        return self._entry_rows(ctx, cap)

    @staticmethod
    def _head(ctx: Ctx, cap: RequestCapability, view: str = "main", *extra: str) -> str:
        return chrome.heading(ctx, cap, view, *extra)

    @staticmethod
    def _back_main_row(ctx: Ctx, cap: RequestCapability) -> list[Button]:
        """«‹ بازگشت» to the capability's main screen, then Home."""
        return [chrome.to_route(chrome.route_of(ctx, cap)), ctx.home_button()]

    @staticmethod
    def _owner_rows(cap: RequestCapability, request: Record, numbered: bool = False) -> Rows:
        """One button per owner action allowed from the request's current status. ``numbered``
        (the staff queue, which lists several requests) puts the request's code in the label."""
        rows: Rows = []
        for act in cap.owner_actions:
            if request.status not in act.from_statuses:
                continue
            try:
                data = make_callback(cap.key, ACT_OWN, f"{request.id}.{act.key}")
            except CallbackError:  # too long for Telegram; the web admin can still apply it
                continue
            label = (
                listing.truncate(_fill(QUEUE_BUTTON, action=act.label, id=_ref(request.id)))
                if numbered
                else _owner_label(act)
            )
            rows.append([Button(label=label, data=data)])
        return rows

    # --- views -------------------------------------------------------------------------------

    def _main(self, ctx: Ctx, cap: RequestCapability) -> None:
        ctx.reply(f"{self._head(ctx, cap)}\n{tx.MAIN_INTRO}", self._entry_rows(ctx, cap))

    async def _queue(self, ctx: Ctx, cap: RequestCapability) -> None:
        """The main view for staff and managers: requests waiting for an owner action (their status
        is one some owner action starts from), newest first, each with its action buttons, above
        the usual entries. Only the newest ``QUEUE_LIMIT`` are listed; a line counts the rest."""
        entries = self._entry_rows(ctx, cap)
        pending = sorted({status for act in cap.owner_actions for status in act.from_statuses})
        requests = (
            await ctx.store.list_records(cap.key, status_in=pending, order_by="-id", limit=QUEUE_LIMIT)
            if pending
            else []
        )
        if not requests:
            ctx.reply(_fill(QUEUE_EMPTY, title=cap.title), entries)
            return
        lines = [_fill(QUEUE_HEADER, title=cap.title)]
        rows: Rows = []
        for r in requests:
            lines.append(await self._queue_entry(ctx, cap, r))
            rows += self._owner_rows(cap, r, numbered=True)
        total = await ctx.store.count_records(cap.key, status_in=pending)
        if total > len(requests):
            lines.append(_fill(QUEUE_MORE, count=formatting.to_persian_digits(total - len(requests))))
        ctx.reply("\n".join(lines), rows + entries)

    async def _queue_entry(self, ctx: Ctx, cap: RequestCapability, request: Record) -> str:
        """One queued request: the line ``mine`` uses, then its form values (each on one line, cut
        short)."""
        item = ""
        if request.item_id is not None:
            found = await self._get_item(ctx, cap, request.item_id)
            item = _fill(tx.MINE_ITEM, item=self._item_title(ctx, cap, found, request.item_id))
        lines = [
            _fill(
                tx.MINE_LINE,
                id=_ref(request.id),
                item=item,
                status=self._status_label(cap, request.status),
                when=formatting.format_jalali_date(request.created_at, ctx.tz),
            )
        ]
        for f in cap.form_fields:
            value = listing.truncate(" ".join(ctx.fmt(f, request.data.get(f.key)).split()), QUEUE_VALUE_CHARS)
            lines.append(_fill(QUEUE_DETAIL_LINE, label=f.label, value=value))
        return "\n".join(lines)

    async def _new(self, ctx: Ctx, cap: RequestCapability, page: int) -> None:
        if cap.item_resource is None:
            head = self._head(ctx, cap, "main", tx.NEW_CRUMB)
            await forms.start(ctx, self, cap, intro=f"{head}\n{ctx.t(cap, 'form_intro', title=cap.title)}")
            return
        resource = self._resource(ctx, cap)
        if resource is None:
            ctx.stale()
            return
        items = await listing.load_items(ctx, resource)
        if not items:
            ctx.reply(
                f"{self._head(ctx, cap, 'main', tx.NEW_CRUMB)}\n{tx.NO_ITEMS}", self._entry_rows(ctx, cap)
            )
            return
        shown, page, pages = listing.paginate(items, page)
        rows: Rows = [
            [ctx.button(listing.truncate(listing.record_title(ctx, resource, r)), cap, ACT_PICK, r.id)]
            for r in shown
        ]
        nav = listing.nav_row(cap, page, pages, ACT_NEW)
        if nav:
            rows.append(nav)
        rows.append(self._back_main_row(ctx, cap))
        lines = [self._head(ctx, cap, "main", tx.NEW_CRUMB), ctx.t(cap, "pick_item", title=cap.title)]
        lines += [_fill(tx.PICK_LINE, title=listing.record_title(ctx, resource, r)) for r in shown]
        if pages > 1:
            lines.append(listing.page_indicator(page, pages))
        ctx.reply("\n".join(lines), rows)

    async def _pick(self, ctx: Ctx, cap: RequestCapability, item_id: int | None) -> None:
        if cap.item_resource is None:
            ctx.stale()
            return
        item = await self._get_item(ctx, cap, item_id)
        if item is None:
            ctx.reject(cap, "submit", "not_found", tx.ITEM_NOT_FOUND, self._back_rows(ctx, cap))
            return
        intro = (
            self._head(ctx, cap, "main", tx.NEW_CRUMB)
            + "\n"
            + ctx.t(cap, "form_intro", title=cap.title)
            + "\n"
            + _fill(tx.PICKED_LINE, item=self._item_title(ctx, cap, item, item.id))
        )
        await forms.start(ctx, self, cap, data={"item_id": item.id}, intro=intro)

    async def _mine(self, ctx: Ctx, cap: RequestCapability) -> None:
        requests = await ctx.store.list_records(cap.key, actor_id=ctx.actor.id, order_by="-id")
        head = self._head(ctx, cap, "mine")
        back = [chrome.back_to(ctx, chrome.route_of(ctx, cap, "mine")), ctx.home_button()]
        if not requests:
            ctx.reply(f"{head}\n{ctx.t(cap, 'mine_empty')}", [self._new_row(cap), back])
            return
        lines = [head, ctx.t(cap, "mine_header")]
        for r in requests:
            item = ""
            if r.item_id is not None:
                title = self._item_title(ctx, cap, await self._get_item(ctx, cap, r.item_id), r.item_id)
                item = _fill(tx.MINE_ITEM, item=title)
            lines.append(
                _fill(
                    tx.MINE_LINE,
                    id=_ref(r.id),
                    item=item,
                    status=self._status_label(cap, r.status),
                    when=formatting.format_jalali_date(r.created_at, ctx.tz),
                )
            )
        ctx.reply("\n".join(lines), [self._new_row(cap), back])


def _owner_label(act: OwnerAction) -> str:
    return listing.truncate(act.label)


ENGINE = RequestEngine()
