"""``orders`` engine: browse, cart, checkout, order status and stock (Business OS, W1-ORD).

Record layout (``botspec/models.py`` module docstring), capability key ``K``:
  ``K``        orders: ``actor_id`` = customer, ``status`` = a key of ``cap.statuses`` (starts at
               ``cap.initial_status``), data = {...checkout answers, "items": [{"item_id", "title",
               "qty", "unit_price"}], "total", "payment_status": "unpaid"}. The system keys are
               written after the answers, so a checkout field can never overwrite them.
  ``K.cart``   at most one record per actor, data = {"items": [{"item_id", "qty"}]}.
  ``K.lines``  one record per order item, data = {"order_id", "item_id", "title", "qty",
               "unit_price"}, ``item_id`` column set too.
Money is integer tomans. ``payment_status`` is written once ("unpaid") and never changed here.

Navigation (drivers locate buttons by parsed callback action/arg, never by label):
  open main / ``list:<page>`` / ``open:[<page>]`` / ``home``  paginated item list (title + price;
                       out-of-stock items marked), one ``item:<id>`` per item, ``cart``, ``mine``
  ``item:<id>``        details, ``add:<id>``, ``cart``, back (to the item's page), home
  ``add:<id>``         qty + 1 in the actor's cart (rejected ``out_of_stock`` beyond the stock,
                       ``not_found`` for a missing/unpriced item, ``invalid_input`` beyond the caps)
  ``dec:<id>``         qty - 1 (the line goes at 0, the cart record when empty), then the cart
  ``cart``             lines (qty x unit price), total, ``chk``, ``open``, one ``dec:<id>`` per line
  ``chk``              empty cart -> rejected ``invalid_input``; stock pre-check; then the shared
                       form collector over ``checkout_fields`` (``ans``/``skip``/``stop``); on
                       completion everything is re-checked BEFORE the first write, then: order,
                       lines, stock decrements, cart deleted, Outcome order/submitted, owner notice
                       ``ordered`` with one ``own:<id>.<key>`` button per allowed owner action
  open mine / ``mine`` the actor's latest orders; ``show:<id>`` and, when cancellable,
                       ``cancel:<id>`` per order
  ``show:<id>``        one of the actor's orders in detail
  ``cancel:<id>``      status -> "cancelled" (must be a declared status key and the current status
                       must be in ``cancellable_statuses``), restock, owner notice when
                       "cancelled" is in ``notify_owner_on``
  ``own:<id>.<key>``   owner action (Telegram button or web ``admin`` event), customer notice
                       ``order_status_changed`` when "status_changed" is in ``notify_user_on``

Stock invariant: an order holds its quantities out of ``stock_field`` exactly while its status is
not "cancelled". Entering "cancelled" (customer cancel or owner action) restocks; an owner action
leaving "cancelled" re-reserves and is rejected ``out_of_stock`` when the stock is short. A missing
stock value (or no ``stock_field``) means unlimited.

Group chats (``event.chat_type == "group"``): every callback gets one short "continue in private
chat" reply (never an edit of the group message) and nothing else.

Like the other engines this relies on the adapter serializing events per bot (dispatch takes the
bot's advisory lock and runs the event in one transaction), which makes checkout atomic.
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from app.botspec.models import OrdersCapability, OwnerAction, Resource
from app.botspec.text_keys import fill_text
from app.runtime import formatting, forms, listing
from app.runtime.callbacks import (
    ACT_ADD,
    ACT_CANCEL,
    ACT_CART,
    ACT_CHK,
    ACT_DEC,
    ACT_HOME,
    ACT_ITEM,
    ACT_LIST,
    ACT_MINE,
    ACT_OPEN,
    ACT_OWN,
    ACT_SHOW,
    FORM_ACTIONS,
    CallbackError,
    make_callback,
)
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx, parse_int
from app.runtime.store import Record
from app.runtime.texts import orders as tx

Rows = list[list[Button]]

CANCELLED = "cancelled"  # the status key a customer cancellation moves to
UNPAID = "unpaid"
MAX_QTY = 99  # per cart line
MAX_LINES = 20  # distinct items in one cart
MINE_LIMIT = 10  # orders listed in "my orders"


def cart_collection(cap: OrdersCapability) -> str:
    return f"{cap.key}.cart"


def lines_collection(cap: OrdersCapability) -> str:
    return f"{cap.key}.lines"


def _fill(template: str, **values: object) -> str:
    return fill_text(template, {k: str(v) for k, v in values.items()})


def _num(value: int) -> str:
    return formatting.to_persian_digits(value)


def money(amount: int) -> str:
    """``120000 -> "۱۲۰٬۰۰۰ تومان"``."""
    return _fill(tx.PRICE, amount=formatting.format_int(amount))


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class Line:
    item: Record
    title: str
    qty: int
    unit_price: int
    stock: int | None  # None = unlimited

    @property
    def subtotal(self) -> int:
        return self.qty * self.unit_price

    @property
    def short(self) -> bool:
        return self.stock is not None and self.qty > self.stock


def _cart_items(cart: Record | None) -> list[tuple[int, int]]:
    """``[(item_id, qty)]`` from a cart record: invalid entries dropped, duplicates merged."""
    merged: dict[int, int] = {}
    raw = cart.data.get("items") if cart is not None else None
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        item_id, qty = _int(entry.get("item_id")), _int(entry.get("qty"))
        if item_id is not None and qty is not None and qty > 0:
            merged[item_id] = merged.get(item_id, 0) + qty
    return list(merged.items())


def _order_items(order: Record) -> list[dict[str, Any]]:
    raw = order.data.get("items")
    out = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict) and _int(entry.get("item_id")) is not None and _int(entry.get("qty")):
            out.append(entry)
    return out


def _owner_label(act: OwnerAction) -> str:
    return listing.truncate(act.label)


class OrdersEngine:
    type: ClassVar[str] = "orders"

    # --- entry points ------------------------------------------------------------------------

    async def open(self, ctx: Ctx, cap: OrdersCapability, view: str) -> None:
        if self._group(ctx):
            return
        if view == "mine":
            await self._mine(ctx, cap)
        else:
            await self._list(ctx, cap, 0)

    async def on_callback(self, ctx: Ctx, cap: OrdersCapability, action: str, arg: str) -> None:
        if self._group(ctx):
            return
        if action in FORM_ACTIONS:
            await forms.handle_callback(ctx, self, cap, action, arg, fields=cap.checkout_fields)
        elif action in (ACT_LIST, ACT_OPEN, ACT_HOME):
            await self._list(ctx, cap, parse_int(arg) or 0)
        elif action == ACT_ITEM:
            await self._item(ctx, cap, parse_int(arg))
        elif action == ACT_ADD:
            await self._add(ctx, cap, parse_int(arg))
        elif action == ACT_DEC:
            await self._dec(ctx, cap, parse_int(arg))
        elif action == ACT_CART:
            await self._cart(ctx, cap)
        elif action == ACT_CHK:
            await self._checkout(ctx, cap)
        elif action == ACT_MINE:
            await self._mine(ctx, cap)
        elif action == ACT_SHOW:
            await self._show(ctx, cap, parse_int(arg))
        elif action == ACT_CANCEL:
            await self._cancel(ctx, cap, parse_int(arg))
        else:
            ctx.stale()

    async def on_text(self, ctx: Ctx, cap: OrdersCapability, text: str) -> None:
        if self._group(ctx):
            return
        await forms.handle_text(ctx, self, cap, text, fields=cap.checkout_fields)

    async def on_form_done(
        self, ctx: Ctx, cap: OrdersCapability, values: dict[str, Any], data: dict[str, Any]
    ) -> None:
        resource = ctx.spec.resource(cap.resource)
        if resource is None:
            ctx.stale()
            return
        loaded = await self._checked_lines(ctx, cap, resource)
        if loaded is None:
            return
        cart, lines = loaded
        # Every check passed above; from here on only writes (one transaction under dispatch).
        total = sum(line.subtotal for line in lines)
        items = [
            {"item_id": ln.item.id, "title": ln.title, "qty": ln.qty, "unit_price": ln.unit_price}
            for ln in lines
        ]
        order = await ctx.create_record(
            cap.key,
            {**values, "items": items, "total": total, "payment_status": UNPAID},
            status=cap.initial_status,
        )
        for ln in lines:
            await ctx.create_record(
                lines_collection(cap),
                {
                    "order_id": order.id,
                    "item_id": ln.item.id,
                    "title": ln.title,
                    "qty": ln.qty,
                    "unit_price": ln.unit_price,
                },
                item_id=ln.item.id,
            )
            if ln.stock is not None and cap.stock_field is not None:
                await ctx.update_record(resource.key, ln.item.id, data={cap.stock_field: ln.stock - ln.qty})
        await ctx.delete_record(cart_collection(cap), cart.id)
        ctx.outcome(cap, "order", "submitted", record_id=order.id)
        placed = ctx.t(cap, "placed", title=cap.title, id=_num(order.id), total=money(total))
        status_line = _fill(tx.STATUS_LINE, status=self._status_label(cap, order.status))
        ctx.reply(f"{placed}\n{status_line}", [self._mine_row(cap), self._continue_row(cap), ctx.home_row()])
        if "placed" in cap.notify_owner_on:
            details = "\n".join(f"{f.label}: {ctx.fmt(f, values.get(f.key))}" for f in cap.checkout_fields)
            ctx.notify_owner(
                "ordered",
                ctx.t(
                    cap,
                    "owner_placed",
                    title=cap.title,
                    id=_num(order.id),
                    user=ctx.actor.display_name,
                    lines=self._items_text(items),
                    total=money(total),
                    details=details,
                ),
                self._owner_rows(cap, order),
            )

    async def owner_action(self, ctx: Ctx, cap: OrdersCapability, record_id: int, action: str) -> None:
        order = await ctx.store.get_record(cap.key, record_id)
        if order is None:
            ctx.reject(cap, "owner_action", "not_found", tx.ORDER_NOT_FOUND, record_id=record_id)
            return
        act = next((a for a in cap.owner_actions if a.key == action), None)
        if act is None:
            text = ctx.t(cap, "not_allowed")
            ctx.reject(
                cap, "owner_action", "not_allowed", text, self._owner_rows(cap, order), record_id=record_id
            )
            return
        if order.status not in act.from_statuses:
            text = _fill(tx.NOT_ALLOWED_FROM, status=self._status_label(cap, order.status))
            ctx.reject(
                cap, "owner_action", "not_allowed", text, self._owner_rows(cap, order), record_id=record_id
            )
            return
        entering = act.to_status == CANCELLED and order.status != CANCELLED
        leaving = order.status == CANCELLED and act.to_status != CANCELLED
        if leaving:
            short = await self._short_for_order(ctx, cap, order)
            if short is not None:
                text = ctx.t(cap, "out_of_stock", title=short)
                ctx.reject(
                    cap,
                    "owner_action",
                    "out_of_stock",
                    text,
                    self._owner_rows(cap, order),
                    record_id=record_id,
                )
                return
        updated = await ctx.update_record(cap.key, order.id, status=act.to_status)
        if entering:
            await self._move_stock(ctx, cap, order, +1)
        elif leaving:
            await self._move_stock(ctx, cap, order, -1)
        label = self._status_label(cap, updated.status)
        ctx.reply(
            ctx.t(cap, "action_done", id=_num(updated.id), status=label), self._owner_rows(cap, updated)
        )
        if "status_changed" in cap.notify_user_on and updated.actor_id not in (None, ctx.actor.id):
            ctx.notify(
                updated.actor_id,
                "order_status_changed",
                ctx.t(cap, "status_changed", title=cap.title, id=_num(updated.id), status=label),
                [self._mine_row(cap), ctx.home_row()],
            )
        ctx.outcome(cap, "owner_action", "ok", record_id=updated.id)

    # --- group -------------------------------------------------------------------------------

    @staticmethod
    def _group(ctx: Ctx) -> bool:
        if ctx.event.chat_type != "group":
            return False
        ctx.reply(tx.GROUP_PRIVATE, edit=False)  # never replace the group message
        return True

    # --- lookups -----------------------------------------------------------------------------

    @staticmethod
    def _price(cap: OrdersCapability, item: Record) -> int | None:
        price = _int(item.data.get(cap.price_field))
        return price if price is not None and price >= 0 else None

    @staticmethod
    def _stock(cap: OrdersCapability, item: Record) -> int | None:
        if cap.stock_field is None:
            return None
        stock = _int(item.data.get(cap.stock_field))
        return None if stock is None else max(stock, 0)

    @staticmethod
    def _status_label(cap: OrdersCapability, status: str | None) -> str:
        return next((s.label for s in cap.statuses if s.key == status), status or "—")

    @staticmethod
    def _cancellable(cap: OrdersCapability, order: Record) -> bool:
        return (
            order.status != CANCELLED
            and order.status in cap.cancellable_statuses
            and any(s.key == CANCELLED for s in cap.statuses)
        )

    async def _get_cart(self, ctx: Ctx, cap: OrdersCapability) -> Record | None:
        rows = await ctx.store.list_records(
            cart_collection(cap), actor_id=ctx.actor.id, order_by="-id", limit=1
        )
        return rows[0] if rows else None

    async def _lines(
        self, ctx: Ctx, cap: OrdersCapability, resource: Resource, cart: Record | None
    ) -> tuple[list[Line], list[int]]:
        """Cart lines with current titles/prices/stock, plus the ids of items that are gone
        (deleted or without a valid price)."""
        lines: list[Line] = []
        gone: list[int] = []
        for item_id, qty in _cart_items(cart):
            item = await ctx.store.get_record(resource.key, item_id)
            price = self._price(cap, item) if item is not None else None
            if item is None or price is None:
                gone.append(item_id)
                continue
            title = listing.record_title(ctx, resource, item)
            lines.append(Line(item, title, qty, price, self._stock(cap, item)))
        return lines, gone

    async def _save_cart(
        self, ctx: Ctx, cap: OrdersCapability, cart: Record | None, items: list[tuple[int, int]]
    ) -> None:
        payload = {"items": [{"item_id": i, "qty": q} for i, q in items if q > 0]}
        if cart is None:
            if payload["items"]:
                await ctx.create_record(cart_collection(cap), payload)
        elif payload["items"]:
            await ctx.update_record(cart_collection(cap), cart.id, data=payload)
        else:
            await ctx.delete_record(cart_collection(cap), cart.id)

    async def _checked_lines(
        self, ctx: Ctx, cap: OrdersCapability, resource: Resource
    ) -> tuple[Record, list[Line]] | None:
        """The actor's cart, ready to order; otherwise reject (empty cart, gone items, short
        stock) and return None. Gone items are removed from the cart before rejecting."""
        cart = await self._get_cart(ctx, cap)
        lines, gone = await self._lines(ctx, cap, resource, cart)
        if gone and cart is not None:
            await self._save_cart(ctx, cap, cart, [(ln.item.id, ln.qty) for ln in lines])
            ctx.reject(cap, "order", "not_found", tx.CART_ITEMS_REMOVED, self._cart_nav(ctx, cap))
            return None
        if cart is None or not lines:
            ctx.reject(cap, "order", "invalid_input", ctx.t(cap, "cart_empty"), self._shop_nav(ctx, cap))
            return None
        short = next((ln for ln in lines if ln.short), None)
        if short is not None:
            text = ctx.t(cap, "out_of_stock", title=short.title)
            ctx.reject(cap, "order", "out_of_stock", text, self._cart_nav(ctx, cap))
            return None
        return cart, lines

    async def _short_for_order(self, ctx: Ctx, cap: OrdersCapability, order: Record) -> str | None:
        """Title of the first order item whose current stock cannot cover it, else None."""
        if cap.stock_field is None:
            return None
        needed: dict[int, int] = {}
        titles: dict[int, str] = {}
        for entry in _order_items(order):
            needed[entry["item_id"]] = needed.get(entry["item_id"], 0) + entry["qty"]
            titles[entry["item_id"]] = str(entry.get("title") or "")
        for item_id, qty in needed.items():
            item = await ctx.store.get_record(cap.resource, item_id)
            stock = self._stock(cap, item) if item is not None else None
            if stock is not None and qty > stock:
                return titles[item_id] or "#" + _num(item_id)
        return None

    async def _move_stock(self, ctx: Ctx, cap: OrdersCapability, order: Record, sign: int) -> None:
        """Add (+1, restock) or remove (-1, reserve) the order's quantities on the item records.
        Items that are gone or have no stock value (unlimited) are skipped."""
        if cap.stock_field is None:
            return
        for entry in _order_items(order):
            item = await ctx.store.get_record(cap.resource, entry["item_id"])
            stock = self._stock(cap, item) if item is not None else None
            if item is None or stock is None:
                continue
            await ctx.update_record(
                cap.resource, item.id, data={cap.stock_field: stock + sign * entry["qty"]}
            )

    # --- rendering ---------------------------------------------------------------------------

    @staticmethod
    def _items_text(items: list[dict[str, Any]]) -> str:
        lines = []
        for entry in items:
            qty, price = _int(entry.get("qty")) or 0, _int(entry.get("unit_price")) or 0
            lines.append(
                _fill(tx.CART_LINE, title=entry.get("title") or "—", qty=_num(qty), total=money(qty * price))
            )
        return "\n".join(lines)

    def _item_line(self, ctx: Ctx, cap: OrdersCapability, resource: Resource, item: Record) -> str:
        price = self._price(cap, item)
        line = ctx.t(
            cap,
            "item_line",
            title=listing.record_title(ctx, resource, item),
            price=money(price) if price is not None else "—",
        )
        if price is None or self._stock(cap, item) == 0:
            line = _fill(tx.MARKED_LINE, line=line, mark=tx.OUT_OF_STOCK_MARK)
        return line

    # --- buttons -----------------------------------------------------------------------------

    @staticmethod
    def _mine_row(cap: OrdersCapability) -> list[Button]:
        return [Ctx.button(tx.MINE_BUTTON, cap, ACT_MINE)]

    @staticmethod
    def _continue_row(cap: OrdersCapability) -> list[Button]:
        return [Ctx.button(tx.CONTINUE_BUTTON, cap, ACT_OPEN)]

    @staticmethod
    def _cart_row(cap: OrdersCapability) -> list[Button]:
        return [Ctx.button(tx.CART_BUTTON, cap, ACT_CART)]

    def _shop_nav(self, ctx: Ctx, cap: OrdersCapability) -> Rows:
        return [self._continue_row(cap), ctx.home_row()]

    def _cart_nav(self, ctx: Ctx, cap: OrdersCapability) -> Rows:
        return [self._cart_row(cap), self._continue_row(cap), ctx.home_row()]

    @staticmethod
    def _owner_rows(cap: OrdersCapability, order: Record) -> Rows:
        """One button per owner action allowed from the order's current status."""
        rows: Rows = []
        for act in cap.owner_actions:
            if order.status not in act.from_statuses:
                continue
            try:
                data = make_callback(cap.key, ACT_OWN, f"{order.id}.{act.key}")
            except CallbackError:  # too long for Telegram; the web admin can still apply it
                continue
            rows.append([Button(label=_owner_label(act), data=data)])
        return rows

    # --- views -------------------------------------------------------------------------------

    async def _list(self, ctx: Ctx, cap: OrdersCapability, page: int) -> None:
        resource = ctx.spec.resource(cap.resource)
        if resource is None:
            ctx.stale()
            return
        items = await listing.load_items(ctx, resource)
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
        rows.append([*self._cart_row(cap), *self._mine_row(cap)])
        rows.append(ctx.home_row())
        lines = [ctx.t(cap, "list_header", title=cap.title)]
        lines += [self._item_line(ctx, cap, resource, r) for r in shown]
        if pages > 1:
            lines.append(listing.page_indicator(page, pages))
        ctx.reply("\n".join(lines), rows)

    async def _item(self, ctx: Ctx, cap: OrdersCapability, item_id: int | None) -> None:
        resource = ctx.spec.resource(cap.resource)
        item = await ctx.store.get_record(resource.key, item_id) if resource and item_id is not None else None
        if resource is None or item is None:
            ctx.stale()
            return
        hidden = {resource.title_field, cap.price_field, cap.stock_field}
        details = listing.detail_lines(
            ctx,
            resource,
            item,
            [f.key for f in resource.fields if f.key not in hidden and item.data.get(f.key) is not None],
        )
        stock = self._stock(cap, item)
        if stock is not None:
            stock_text = _num(stock) if stock > 0 else tx.OUT_OF_STOCK_MARK
            details = "\n".join(x for x in (details, _fill(tx.STOCK_LINE, stock=stock_text)) if x)
        price = self._price(cap, item)
        text = ctx.t(
            cap,
            "item_detail",
            title=listing.record_title(ctx, resource, item),
            details=details,
            price=money(price) if price is not None else tx.OUT_OF_STOCK_MARK,
        )
        items = await listing.load_items(ctx, resource)
        rows: Rows = [
            [ctx.button(tx.ADD_BUTTON, cap, ACT_ADD, item.id)],
            self._cart_row(cap),
            ctx.back_home_row(cap, ACT_LIST, listing.page_of(items, item.id)),
        ]
        ctx.reply(text, rows)

    async def _add(self, ctx: Ctx, cap: OrdersCapability, item_id: int | None) -> None:
        resource = ctx.spec.resource(cap.resource)
        item = await ctx.store.get_record(resource.key, item_id) if resource and item_id is not None else None
        if resource is None or item is None or self._price(cap, item) is None:
            ctx.reject(cap, "order", "not_found", tx.ITEM_UNAVAILABLE, self._cart_nav(ctx, cap))
            return
        title = listing.record_title(ctx, resource, item)
        cart = await self._get_cart(ctx, cap)
        items = _cart_items(cart)
        current = dict(items).get(item.id, 0)
        qty = current + 1
        stock = self._stock(cap, item)
        if stock is not None and qty > stock:
            text = ctx.t(cap, "out_of_stock", title=title)
            ctx.reject(cap, "order", "out_of_stock", text, self._cart_nav(ctx, cap))
            return
        if qty > MAX_QTY or (current == 0 and len(items) >= MAX_LINES):
            ctx.reject(cap, "order", "invalid_input", tx.CART_LIMIT, self._cart_nav(ctx, cap))
            return
        if current:
            items = [(i, qty if i == item.id else q) for i, q in items]
        else:
            items.append((item.id, qty))
        await self._save_cart(ctx, cap, cart, items)
        ctx.reply(
            ctx.t(cap, "added_to_cart", title=title, qty=_num(qty)),
            [
                [ctx.button(tx.ADD_BUTTON, cap, ACT_ADD, item.id), *self._cart_row(cap)],
                self._continue_row(cap),
                ctx.home_row(),
            ],
        )

    async def _dec(self, ctx: Ctx, cap: OrdersCapability, item_id: int | None) -> None:
        cart = await self._get_cart(ctx, cap)
        items = _cart_items(cart)
        if item_id is not None and any(i == item_id for i, _ in items):
            await self._save_cart(ctx, cap, cart, [(i, q - 1 if i == item_id else q) for i, q in items])
        await self._cart(ctx, cap)

    async def _cart(self, ctx: Ctx, cap: OrdersCapability) -> None:
        resource = ctx.spec.resource(cap.resource)
        if resource is None:
            ctx.stale()
            return
        lines, _ = await self._lines(ctx, cap, resource, await self._get_cart(ctx, cap))
        if not lines:
            ctx.reply(ctx.t(cap, "cart_empty"), self._shop_nav(ctx, cap))
            return
        text_lines = [
            _fill(tx.CART_LINE, title=ln.title, qty=_num(ln.qty), total=money(ln.subtotal)) for ln in lines
        ]
        total = sum(ln.subtotal for ln in lines)
        rows: Rows = [
            [
                ctx.button(
                    listing.truncate(_fill(tx.DEC_LINE_BUTTON, title=ln.title)), cap, ACT_DEC, ln.item.id
                )
            ]
            for ln in lines
        ]
        rows += [[ctx.button(tx.CHECKOUT_BUTTON, cap, ACT_CHK)], self._continue_row(cap), ctx.home_row()]
        ctx.reply(ctx.t(cap, "cart_summary", lines="\n".join(text_lines), total=money(total)), rows)

    async def _checkout(self, ctx: Ctx, cap: OrdersCapability) -> None:
        resource = ctx.spec.resource(cap.resource)
        if resource is None:
            ctx.stale()
            return
        loaded = await self._checked_lines(ctx, cap, resource)
        if loaded is None:
            return
        total = sum(ln.subtotal for ln in loaded[1])
        intro = ctx.t(cap, "checkout_prompt", total=money(total))
        await forms.start(ctx, self, cap, fields=cap.checkout_fields, intro=intro)

    async def _mine(self, ctx: Ctx, cap: OrdersCapability) -> None:
        orders = await ctx.store.list_records(
            cap.key, actor_id=ctx.actor.id, order_by="-id", limit=MINE_LIMIT
        )
        if not orders:
            ctx.reply(ctx.t(cap, "mine_empty"), self._shop_nav(ctx, cap))
            return
        lines = [ctx.t(cap, "mine_header")]
        rows: Rows = []
        for order in orders:
            lines.append(
                _fill(
                    tx.MINE_LINE,
                    id=_num(order.id),
                    status=self._status_label(cap, order.status),
                    total=money(_int(order.data.get("total")) or 0),
                    when=formatting.format_jalali_date(order.created_at, ctx.tz),
                )
            )
            row = [ctx.button(_fill(tx.ORDER_BUTTON, id=_num(order.id)), cap, ACT_SHOW, order.id)]
            if self._cancellable(cap, order):
                row.append(
                    ctx.button(_fill(tx.CANCEL_ORDER_BUTTON, id=_num(order.id)), cap, ACT_CANCEL, order.id)
                )
            rows.append(row)
        rows += [self._continue_row(cap), ctx.home_row()]
        ctx.reply("\n".join(lines), rows)

    async def _own_order(self, ctx: Ctx, cap: OrdersCapability, order_id: int | None) -> Record | None:
        order = await ctx.store.get_record(cap.key, order_id) if order_id is not None else None
        return order if order is not None and order.actor_id == ctx.actor.id else None

    async def _show(self, ctx: Ctx, cap: OrdersCapability, order_id: int | None) -> None:
        order = await self._own_order(ctx, cap, order_id)
        if order is None:
            ctx.stale()
            return
        text = _fill(
            tx.ORDER_DETAIL,
            id=_num(order.id),
            lines=self._items_text(_order_items(order)),
            total=money(_int(order.data.get("total")) or 0),
            status=self._status_label(cap, order.status),
        )
        rows: Rows = []
        if self._cancellable(cap, order):
            rows.append([ctx.button(tx.CANCEL_BUTTON, cap, ACT_CANCEL, order.id)])
        rows += [self._mine_row(cap), ctx.home_row()]
        ctx.reply(text, rows)

    async def _cancel(self, ctx: Ctx, cap: OrdersCapability, order_id: int | None) -> None:
        order = await self._own_order(ctx, cap, order_id)
        if order is None:
            rows = [self._mine_row(cap), ctx.home_row()]
            ctx.reject(cap, "cancel", "not_found", tx.ORDER_NOT_FOUND, rows, record_id=order_id)
            return
        if not self._cancellable(cap, order):
            text = ctx.t(
                cap, "not_cancellable", id=_num(order.id), status=self._status_label(cap, order.status)
            )
            ctx.reject(
                cap, "cancel", "not_allowed", text, [self._mine_row(cap), ctx.home_row()], record_id=order.id
            )
            return
        await ctx.update_record(cap.key, order.id, status=CANCELLED)
        await self._move_stock(ctx, cap, order, +1)
        ctx.reply(
            ctx.t(cap, "cancelled", id=_num(order.id)),
            [self._mine_row(cap), self._continue_row(cap), ctx.home_row()],
        )
        if "cancelled" in cap.notify_owner_on:
            ctx.notify_owner(
                "cancelled",
                ctx.t(
                    cap, "owner_cancelled", title=cap.title, id=_num(order.id), user=ctx.actor.display_name
                ),
            )
        ctx.outcome(cap, "cancel", "cancelled", record_id=order.id)


ENGINE = OrdersEngine()
