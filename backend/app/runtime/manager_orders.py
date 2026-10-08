"""Telegram manager screen «📦 سفارش‌ها»: the order queue of an orders capability (U6).

One route, ``mgr.ord`` (capability-bound, managers only; nav checks role, capability and gating),
whose first arg picks the screen. ``<f>`` is a status key of the capability or ``_`` for every
status; ``<p>`` is a 0-based page.

  mgr.ord~n                    the list, every status, newest first
  mgr.ord~n.l.<f>[.<p>]        the list filtered by status ``<f>``, page ``<p>`` (8 per page)
  mgr.ord~n.o.<id>[.<f>]       one order: items, total, customer, checkout answers, status, one
                               button per owner action allowed from its status; Back -> list <f>
  mgr.ord~n.a.<id>.<key>       run owner action ``<key>`` on order ``<id>``

Owner actions run through exactly the path the ``<cap>:own:<id>.<key>`` buttons use:
``roles.can_run_owner_actions`` and then ``OrdersEngine.owner_action``, so the status check, stock
moves, customer notification, Effects and Outcome are identical. Only the engine's reply to the
manager is replaced (the customer's notice and everything else it produced stay):
  ok                 the pressed message becomes the updated order, headed by the engine's
                     confirmation line (``action_done``, overridable per bot)
  rejected           a NEW message, the pressed one untouched: «این سفارش دیگر قابل این تغییر
  not_allowed        نیست.» + [مشاهدهٔ سفارش] [‹ سفارش‌ها]
  other rejections   a NEW message with the engine's explanation (not found, out of stock) and the
                     same buttons (no [مشاهدهٔ سفارش] when the order is gone)
The manager queue's action buttons are nav routes rather than the engine's ``own`` callbacks so the
result can be rendered as a manager screen without changing the orders engine.

Malformed args (unknown screen, bad id) -> nav's stale home. A filter naming a status the spec no
longer has shows every status. Payloads are kept within 64 bytes: the optional ``<f>`` is dropped
when it would not fit, and an action whose payload cannot fit has no button (the web admin can still
apply it), like the engine's own buttons.
"""

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.botspec.models import AnyCapability, OrdersCapability
from app.botspec.text_keys import fill_text
from app.roles import can_run_owner_actions
from app.runtime import formatting, nav
from app.runtime.callbacks import CallbackError
from app.runtime.contracts import Button, OutMessage
from app.runtime.engines import EngineUnavailable, get_engine
from app.runtime.manager_team import display_names, manager_button, screen_heading
from app.runtime.store import Record
from app.runtime.texts import common
from app.runtime.texts import manager as tx

if TYPE_CHECKING:
    from app.runtime.ctx import Ctx

ROUTE = "mgr.ord"
ALL = "_"  # the "every status" filter (status keys start with a letter, so it never collides)
LIST, ORDER, ACTION = "l", "o", "a"
PAGE_SIZE = 8
FILTERS_PER_ROW = 3
MAX_LABEL = 60
NAME_HINTS = ("name", "نام")

Rows = list[list[Button]]


def _fill(template: str, **values: object) -> str:
    return fill_text(template, {k: str(v) for k, v in values.items()})


def _num(value: int) -> str:
    return formatting.to_persian_digits(value)


def _amount(value: Any) -> str:
    amount = value if isinstance(value, int) and not isinstance(value, bool) else 0
    return formatting.format_int(amount)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_id(arg: str) -> int | None:
    return int(arg) if arg.isascii() and arg.isdigit() and len(arg) <= 18 else None


def _truncate(label: str) -> str:
    return label if len(label) <= MAX_LABEL else label[: MAX_LABEL - 1].rstrip() + "…"


def _candidates(spec: Any) -> list[AnyCapability]:
    route = nav.ROUTES[ROUTE]
    return route.candidates(spec) if route.candidates is not None else []


def ordinal(spec: Any, cap: AnyCapability) -> int:
    """The capability's ordinal among the route's candidates (1 when not found)."""
    return next((n for n, c in enumerate(_candidates(spec), 1) if c.key == cap.key), 1)


def _heading(ctx: "Ctx", cap: OrdersCapability, *extra: str) -> str:
    """``🧭 مدیریت › 📦 سفارش‌ها[ › title] › extra``: the title only when several shops exist."""
    several = sum(1 for c in _candidates(ctx.spec) if nav.usable(c, ctx.actor)) > 1
    named = (cap.title, *extra) if several else extra
    return screen_heading(ctx, nav.route_payload(ROUTE, ordinal(ctx.spec, cap)), *named)


def payload(spec: Any, cap: AnyCapability, *args: str | int) -> str | None:
    """``mgr.ord~n.<args>`` or None when it cannot be a callback (over 64 bytes)."""
    try:
        return nav.route_payload(ROUTE, ordinal(spec, cap), *args)
    except CallbackError:
        return None


def list_payload(spec: Any, cap: AnyCapability, status: str = ALL, page: int = 0) -> str | None:
    if status == ALL and page == 0:
        return payload(spec, cap)
    return payload(spec, cap, LIST, status, page) if page else payload(spec, cap, LIST, status)


def order_payload(spec: Any, cap: AnyCapability, order_id: int, status: str = ALL) -> str | None:
    if status != ALL:
        with_filter = payload(spec, cap, ORDER, order_id, status)
        if with_filter is not None:
            return with_filter
    return payload(spec, cap, ORDER, order_id)


def _button(label: str, route: str | None) -> Button | None:
    return nav.nav_button(_truncate(label), route) if route is not None else None


def _row(*buttons: Button | None) -> list[Button]:
    return [b for b in buttons if b is not None]


def _status_label(cap: OrdersCapability, status: str | None) -> str:
    return next((s.label for s in cap.statuses if s.key == status), status or "—")


def _status_filter(cap: OrdersCapability, arg: str) -> str:
    return arg if any(s.key == arg for s in cap.statuses) else ALL


def _customer(order: Record, names: dict[str, str], cap: OrdersCapability) -> str:
    """The customer's display name; else a checkout answer that looks like a name."""
    if order.actor_id and order.actor_id in names:
        return names[order.actor_id]
    for field in cap.checkout_fields:
        value = order.data.get(field.key)
        hinted = any(h in field.key.lower() or h in field.label for h in NAME_HINTS)
        if hinted and isinstance(value, str) and value.strip():
            return value.strip()
    return tx.CUSTOMER_UNKNOWN


def _back_rows(ctx: "Ctx", cap: OrdersCapability, status: str = ALL) -> Rows:
    return [_row(_button(tx.BACK_TO_ORDERS, list_payload(ctx.spec, cap, status)), manager_button())]


# --- list ------------------------------------------------------------------------------------------


async def _counts(ctx: "Ctx", cap: OrdersCapability) -> dict[str, int]:
    counts = {s.key: await ctx.store.count_records(cap.key, status_in=[s.key]) for s in cap.statuses}
    counts[ALL] = await ctx.store.count_records(cap.key)
    return counts


def _filter_rows(ctx: "Ctx", cap: OrdersCapability, counts: dict[str, int], current: str) -> Rows:
    options = [(ALL, tx.ORDERS_ALL)] + [(s.key, s.label) for s in cap.statuses]
    buttons: list[Button] = []
    for key, label in options:
        text = _fill(tx.FILTER_BUTTON, status=label, count=_num(counts.get(key, 0)))
        if key == current:
            text = _fill(tx.FILTER_ACTIVE, label=text)
        button = _button(text, list_payload(ctx.spec, cap, key))
        if button is not None:
            buttons.append(button)
    return [buttons[i : i + FILTERS_PER_ROW] for i in range(0, len(buttons), FILTERS_PER_ROW)]


async def show_list(ctx: "Ctx", cap: OrdersCapability, status: str = ALL, page: int = 0) -> None:
    counts = await _counts(ctx, cap)
    total = counts.get(status, 0)
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    status_in = None if status == ALL else [status]
    newest = await ctx.store.list_records(
        cap.key, status_in=status_in, order_by="-id", limit=(page + 1) * PAGE_SIZE
    )
    shown = newest[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    names = await display_names(ctx, (o.actor_id for o in shown))

    filter_label = tx.ORDERS_ALL if status == ALL else _status_label(cap, status)
    lines = [
        _heading(ctx, cap),
        _fill(tx.FILTER_LINE, status=filter_label, count=_num(total)),
    ]
    rows: Rows = _filter_rows(ctx, cap, counts, status)
    if not shown:
        lines.append(tx.ORDERS_EMPTY)
    for order in shown:
        values = {
            "id": _num(order.id),
            "customer": _customer(order, names, cap),
            "total": _amount(order.data.get("total")),
        }
        template = tx.ORDER_LINE_WITH_STATUS if status == ALL else tx.ORDER_LINE
        lines.append(_fill(template, **values, status=_status_label(cap, order.status)))
        button = _button(_fill(tx.ORDER_LINE, **values), order_payload(ctx.spec, cap, order.id, status))
        if button is not None:
            rows.append([button])
    if pages > 1:
        lines.append(_fill(common.PAGE_INDICATOR, page=_num(page + 1), pages=_num(pages)))
        rows.append(
            _row(
                _button(common.PREVIOUS, list_payload(ctx.spec, cap, status, page - 1)) if page > 0 else None,
                _button(common.NEXT, list_payload(ctx.spec, cap, status, page + 1))
                if page < pages - 1
                else None,
            )
        )
    rows.append([manager_button()])
    ctx.reply("\n".join(lines), rows)


# --- one order -------------------------------------------------------------------------------------


def _when(ctx: "Ctx", value: datetime) -> str:
    return formatting.format_datetime(value, ctx.tz)


def _order_text(ctx: "Ctx", cap: OrdersCapability, order: Record, customer: str) -> str:
    lines = [
        _heading(ctx, cap, _fill(tx.ORDER_CRUMB, id=_num(order.id))),
        _fill(tx.ORDER_CUSTOMER, name=customer),
        _fill(tx.ORDER_STATUS, status=_status_label(cap, order.status)),
        _fill(tx.ORDER_WHEN, when=_when(ctx, order.created_at)),
    ]
    items = order.data.get("items")
    entries = [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []
    if entries:
        lines.append(tx.ORDER_ITEMS)
        for entry in entries:
            qty, price = _int(entry.get("qty")) or 0, _int(entry.get("unit_price")) or 0
            lines.append(
                _fill(
                    tx.ORDER_ITEM,
                    title=entry.get("title") or "—",
                    qty=_num(qty),
                    total=formatting.format_int(qty * price),
                )
            )
    lines.append(_fill(tx.ORDER_TOTAL, total=_amount(order.data.get("total"))))
    for field in cap.checkout_fields:
        lines.append(f"{field.label}: {ctx.fmt(field, order.data.get(field.key))}")
    return "\n".join(lines)


def _action_rows(ctx: "Ctx", cap: OrdersCapability, order: Record) -> Rows:
    rows: Rows = []
    for act in cap.owner_actions:
        if order.status not in act.from_statuses:
            continue
        button = _button(act.label, payload(ctx.spec, cap, ACTION, order.id, act.key))
        if button is not None:
            rows.append([button])
    return rows


async def render_order(
    ctx: "Ctx",
    cap: OrdersCapability,
    order: Record,
    *,
    back_status: str = ALL,
    notice: str | None = None,
    edit: bool | None = None,
) -> None:
    names = await display_names(ctx, [order.actor_id])
    text = _order_text(ctx, cap, order, _customer(order, names, cap))
    if notice:
        text = f"{notice}\n\n{text}"
    if not any(order.status in act.from_statuses for act in cap.owner_actions):
        text = f"{text}\n\n{tx.ORDER_NO_ACTIONS}"
    rows = _action_rows(ctx, cap, order) + _back_rows(ctx, cap, back_status)
    ctx.reply(text, rows, edit=edit)


async def show_order(ctx: "Ctx", cap: OrdersCapability, order_id: int, status: str = ALL) -> None:
    order = await ctx.store.get_record(cap.key, order_id)
    if order is None:
        ctx.reply(tx.ORDER_GONE, _back_rows(ctx, cap, status), edit=False)
        return
    await render_order(ctx, cap, order, back_status=status)


# --- owner actions ---------------------------------------------------------------------------------


def _take_replies(ctx: "Ctx", start: int) -> list[OutMessage]:
    """Remove and return the messages to the acting actor (not notices) added since ``start``."""
    added = ctx.messages[start:]
    mine = [m for m in added if m.to_actor_id == ctx.actor.id and m.notice is None]
    ctx.messages[start:] = [m for m in added if not any(m is r for r in mine)]
    return mine


async def run_action(ctx: "Ctx", cap: OrdersCapability, order_id: int, key: str) -> None:
    if not can_run_owner_actions(cap, ctx.actor):  # the runtime's own check, kept identical
        ctx.reject(cap, "owner_action", "not_allowed", common.NOT_ALLOWED)
        return
    try:
        engine = get_engine(cap.type)
    except EngineUnavailable:
        ctx.reply(common.NOT_AVAILABLE, [[manager_button()]])
        return
    before = await ctx.store.get_record(cap.key, order_id)
    from_status = before.status if before is not None and before.status else ALL
    msg_start, outcome_start = len(ctx.messages), len(ctx.outcomes)
    await engine.owner_action(ctx, cap, order_id, key)
    replies = _take_replies(ctx, msg_start)
    outcome = next((o for o in reversed(ctx.outcomes[outcome_start:]) if o.action == "owner_action"), None)
    back = _status_filter(cap, from_status)
    after = await ctx.store.get_record(cap.key, order_id)
    if outcome is not None and outcome.result == "ok" and after is not None:
        confirmation = replies[0].text if replies else ""
        notice = _fill(tx.DONE_MARK, text=confirmation) if confirmation else None
        await render_order(
            ctx, cap, after, back_status=back, notice=notice, edit=replies[0].edit if replies else None
        )
        return
    reason = outcome.reason if outcome is not None else None
    if reason == "not_allowed":
        text = tx.ACTION_STALE
    elif after is None:
        text = tx.ORDER_GONE
    else:
        text = replies[0].text if replies else tx.ACTION_STALE
    rows: Rows = []
    if after is not None:
        view = _button(tx.VIEW_ORDER, order_payload(ctx.spec, cap, after.id))
        if view is not None:
            rows.append([view])
    rows += _back_rows(ctx, cap, back)
    ctx.reply(text, rows, edit=False)  # a rejection never rewrites the pressed message


# --- route -----------------------------------------------------------------------------------------


async def resolve(ctx: "Ctx", target: nav.Target) -> None:
    cap = target.cap
    if not isinstance(cap, OrdersCapability):
        await nav.stale_home(ctx)
        return
    args = target.args
    if not args:
        await show_list(ctx, cap)
        return
    screen, rest = args[0], args[1:]
    if screen == LIST and len(rest) in (1, 2):
        page = _parse_id(rest[1]) if len(rest) == 2 else 0
        if page is not None:
            await show_list(ctx, cap, _status_filter(cap, rest[0]), page)
            return
    elif screen == ORDER and len(rest) in (1, 2):
        order_id = _parse_id(rest[0])
        if order_id is not None:
            status = _status_filter(cap, rest[1]) if len(rest) == 2 else ALL
            await show_order(ctx, cap, order_id, status)
            return
    elif screen == ACTION and len(rest) == 2:
        order_id = _parse_id(rest[0])
        if order_id is not None:
            await run_action(ctx, cap, order_id, rest[1])
            return
    await nav.stale_home(ctx)


# --- manager home ----------------------------------------------------------------------------------


async def attention(ctx: "Ctx") -> list[nav.AttentionItem]:
    """One line per orders capability with orders still in its initial status."""
    caps = [c for c in _candidates(ctx.spec) if isinstance(c, OrdersCapability) and nav.usable(c, ctx.actor)]
    items: list[nav.AttentionItem] = []
    for cap in caps:
        count = await ctx.store.count_records(cap.key, status_in=[cap.initial_status])
        if not count:
            continue
        status = _status_label(cap, cap.initial_status)
        template = tx.ATTENTION_ORDERS_NAMED if len(caps) > 1 else tx.ATTENTION_ORDERS
        text = _fill(template, count=_num(count), status=status, title=cap.title)
        label = _fill(tx.ATTENTION_ORDERS_BUTTON, status=status, count=_num(count))
        items.append(nav.AttentionItem(text, _button(label, list_payload(ctx.spec, cap, cap.initial_status))))
    return items


nav.register_route(replace(nav.ROUTES[ROUTE], resolve=resolve, ready=True, max_args=3))
nav.register_attention(attention)
