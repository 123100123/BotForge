"""Telegram manager screens: the manager home's summary and attention lines, reports, and the
request queue's manager frame; deterministic, no LLM (U6).

The manager home itself is compiled by ``runtime/nav.py`` (heading, Manage entries, customer view).
This module (and the screens it imports, which register themselves on import; nav imports this
module lazily through ``nav.load_extensions``) fills it in:

  summary      «امروز: ۳ سفارش · ۲ ثبت‌نام · ۱ درخواست» (records created since local midnight, per
               enabled capability type), then «فعلاً موردی منتظر شما نیست.» when no attention
               item was collected
  attention    orders still in their initial status (``manager_orders.attention``) -> the list
               filtered by that status; requests still in their initial status -> ``mgr.req``;
               events starting within 24 hours with registered/capacity -> ``mgr.evt`` (read only)
  screens      ``mgr.ord`` (``manager_orders.py``), ``mgr.team`` (``manager_team.py``), ``mgr.req``
               (the request engine's queue under a manager heading, «🏠 خانه» swapped for
               «🧭 مدیریت»), ``mgr.rep`` (below)

Reports (``nav:go:mgr.rep``; listed on the manager home as «📊 گزارش‌ها»):

  nav:go:mgr.rep             the report list: "خلاصه کسب‌وکار" plus one button per enabled
                             capability that has metrics; [🧭 مدیریت]
  nav:go:mgr.rep.all         the Overview (``reporting.service.overview``) of the last 7 days
  nav:go:mgr.rep.<cap_key>   that capability's report (``capability_report``), same period;
                             [‹ گزارش‌ها] [🧭 مدیریت]

Legacy buttons sent before nav routes existed keep working through the runtime's ``menu:open``
aliases (``legacy_route``): ``menu:open:_mgr`` -> the manager home, ``menu:open:_rep.<k>`` ->
``mgr.rep.<k>`` (spec menu keys cannot start with ``_``, so they never collide with a real item).

Only managers (``actor.effective_role``; the owner is a manager) reach these screens; nav answers
anyone else with the stale home. Everything goes through ``Ctx``, so the simulator shows it too.
The reporting engine depends only on ``Store``, ``botspec`` and the REST schemas, so this module
keeps the runtime free of database and API imports. Records are only read here.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.botspec.models import AnyCapability, BookingCapability, OrdersCapability, RequestCapability
from app.botspec.text_keys import fill_text
from app.reporting import service as reporting
from app.reporting.metrics import metrics_for
from app.reporting.telegram import render_overview_text, render_report_text
from app.runtime import formatting, nav
from app.runtime import manager_orders as manager_orders  # registers mgr.ord and its attention
from app.runtime import manager_team as manager_team  # registers mgr.team
from app.runtime.contracts import Button
from app.runtime.engines import EngineUnavailable, get_engine
from app.runtime.manager_team import manager_button, screen_heading
from app.runtime.texts import manager as tx

if TYPE_CHECKING:
    from app.runtime.ctx import Ctx

PANEL_ITEM = "_mgr"  # legacy menu:open item
REPORT_PREFIX = "_rep."  # legacy menu:open item prefix
ALL_REPORT = "all"
PERIOD = "7d"
REPORTS_ROUTE = "mgr.rep"
REQUESTS_ROUTE = "mgr.req"
EVENTS_ROUTE = "mgr.evt"

OVERVIEW_LABEL = tx.OVERVIEW
PANEL_HINT = tx.REPORTS_HINT

TODAY_SCAN_LIMIT = 500  # newest records looked at per capability for the «امروز» line
EVENTS_WINDOW = timedelta(hours=24)
EVENTS_SHOWN = 3  # per capability; a line counts the rest
ACTIVE_BOOKINGS = ["confirmed", "waitlisted"]
CONFIRMED = "confirmed"


def _fill(template: str, **values: object) -> str:
    return fill_text(template, {k: str(v) for k, v in values.items()})


def _num(value: int) -> str:
    return formatting.to_persian_digits(value)


def is_manager_item(item_key: str) -> bool:
    """A legacy ``menu:open`` pseudo item of the old manager panel."""
    return item_key == PANEL_ITEM or item_key.startswith(REPORT_PREFIX)


def legacy_route(item_key: str) -> str:
    """The nav route a legacy pseudo item now opens (``""`` -> nav's stale home)."""
    if item_key == PANEL_ITEM:
        return nav.MGR
    key = item_key.removeprefix(REPORT_PREFIX)
    return f"{REPORTS_ROUTE}.{key}" if key else ""


# --- reports ---------------------------------------------------------------------------------------


def _report_button(label: str, key: str) -> Button | None:
    try:
        return nav.nav_button(label, f"{REPORTS_ROUTE}.{key}")
    except ValueError:  # CallbackError: cannot happen for a valid capability key
        return None


def show_panel(ctx: "Ctx") -> None:
    """The report list (``nav:go:mgr.rep``)."""
    rows: list[list[Button]] = []
    for label, key in [(OVERVIEW_LABEL, ALL_REPORT)] + [
        (cap.title, cap.key)
        for cap in ctx.spec.capabilities
        if cap.enabled and cap.key != ALL_REPORT and metrics_for(cap)
    ]:
        button = _report_button(label, key)
        if button is not None:
            rows.append([button])
    rows.append([manager_button()])
    ctx.reply(f"{screen_heading(ctx, REPORTS_ROUTE)}\n{PANEL_HINT}", rows)


async def show_report(ctx: "Ctx", key: str) -> bool:
    """The overview (``all``) or one capability's report; False when there is no such report (a
    missing or disabled capability, or one without metrics)."""
    back = [[nav.nav_button(tx.BACK_TO_REPORTS, REPORTS_ROUTE), manager_button()]]
    if key == ALL_REPORT:
        overview = await reporting.overview(ctx.store, ctx.spec, PERIOD, ctx.now)
        ctx.reply(render_overview_text(overview), back)
        return True
    cap = ctx.spec.capability(key)
    if cap is None or not cap.enabled or not metrics_for(cap):
        return False
    report = await reporting.capability_report(ctx.store, ctx.spec, cap, PERIOD, ctx.now)
    ctx.reply(render_report_text(report), back)
    return True


# --- request queue ---------------------------------------------------------------------------------


async def show_requests(ctx: "Ctx", target: nav.Target) -> None:
    """``mgr.req``: the request engine's staff queue (unchanged: its ``own`` buttons, Outcomes and
    rules), framed as a manager screen: the manager heading on top and «🧭 مدیریت» in place of the
    engine's «🏠 خانه» row."""
    cap = target.cap
    if cap is None:
        await nav.stale_home(ctx)
        return
    try:
        engine = get_engine(cap.type)
    except EngineUnavailable:
        await nav.stale_home(ctx)
        return
    start = len(ctx.messages)
    await engine.open(ctx, cap, "main")
    home = nav.home_button().data
    several = sum(1 for c in _manager_caps(ctx) if isinstance(c, RequestCapability)) > 1
    heading = screen_heading(ctx, target.payload, *((cap.title,) if several else ()))
    for i in range(start, len(ctx.messages)):
        msg = ctx.messages[i]
        if msg.to_actor_id != ctx.actor.id or msg.notice is not None:
            continue
        rows = [row for row in msg.buttons if not (len(row) == 1 and row[0].data == home)]
        ctx.messages[i] = msg.model_copy(
            update={"text": f"{heading}\n{msg.text}", "buttons": [*rows, [manager_button()]]}
        )


# --- manager home: summary and attention -------------------------------------------------------------


def _manager_caps(ctx: "Ctx") -> list[AnyCapability]:
    return [c for c in ctx.spec.capabilities if nav.usable(c, ctx.actor)]


def _local_midnight(ctx: "Ctx") -> datetime:
    local = formatting.to_local(ctx.now, ctx.tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


async def _created_since(ctx: "Ctx", collection: str, since: datetime, status_in: list[str] | None) -> int:
    newest = await ctx.store.list_records(
        collection, status_in=status_in, order_by="-id", limit=TODAY_SCAN_LIMIT
    )
    return sum(1 for r in newest if since <= r.created_at <= ctx.now)


async def _today_line(ctx: "Ctx") -> str | None:
    """«امروز: …» for the enabled orders, booking and request capabilities (None without any)."""
    since = _local_midnight(ctx)
    totals: dict[str, int] = {}
    for cap in _manager_caps(ctx):
        if isinstance(cap, OrdersCapability):
            word, status_in = tx.TODAY_ORDERS, None
        elif isinstance(cap, BookingCapability):
            word = tx.TODAY_REGISTRATIONS if cap.preset == "events" else tx.TODAY_BOOKINGS
            status_in = ACTIVE_BOOKINGS
        elif isinstance(cap, RequestCapability):
            word, status_in = tx.TODAY_REQUESTS, None
        else:
            continue
        totals[word] = totals.get(word, 0) + await _created_since(ctx, cap.key, since, status_in)
    if not totals:
        return None
    parts = [_fill(word, count=_num(n)) for word, n in totals.items() if n]
    if not parts:
        return tx.TODAY_NOTHING
    return _fill(tx.TODAY, parts=tx.TODAY_PART_SEPARATOR.join(parts))


async def summary(ctx: "Ctx", attention: list[nav.AttentionItem]) -> list[str]:
    lines: list[str] = []
    today = await _today_line(ctx)
    if today:
        lines.append(today)
    if not attention:
        lines.append(tx.NOTHING_WAITING)
    return lines


def _route_payload(route_id: str, ctx: "Ctx", cap: AnyCapability) -> str | None:
    route = nav.ROUTES.get(route_id)
    if route is None or route.candidates is None:
        return None
    n = next((i for i, c in enumerate(route.candidates(ctx.spec), 1) if c.key == cap.key), None)
    return nav.route_payload(route_id, n) if n is not None else None


async def request_attention(ctx: "Ctx") -> list[nav.AttentionItem]:
    """One line per request capability with requests still in its initial status."""
    items: list[nav.AttentionItem] = []
    for cap in _manager_caps(ctx):
        if not isinstance(cap, RequestCapability):
            continue
        count = await ctx.store.count_records(cap.key, status_in=[cap.initial_status])
        route = _route_payload(REQUESTS_ROUTE, ctx, cap)
        if not count or route is None:
            continue
        text = _fill(tx.ATTENTION_REQUESTS, count=_num(count), title=cap.title)
        label = _fill(tx.ATTENTION_REQUESTS_BUTTON, count=_num(count))
        items.append(nav.AttentionItem(text, nav.nav_button(label, route)))
    return items


def _capacity(cap: BookingCapability, item: Any) -> int:
    """The item's capacity (0 = unknown or unlimited), read like the booking engine does."""
    if cap.capacity.mode == "fixed":
        return max(cap.capacity.value or 0, 0)
    raw = item.data.get(cap.capacity.field) if cap.capacity.field else None
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return max(raw, 0)
    if isinstance(raw, float) and raw.is_integer():
        return max(int(raw), 0)
    if isinstance(raw, str):
        s = formatting.to_ascii_digits(raw.strip())
        return int(s) if s.isascii() and s.isdigit() else 0
    return 0


async def event_attention(ctx: "Ctx") -> list[nav.AttentionItem]:
    """Events (booking capabilities with the events preset and a start field) starting within
    the next 24 hours, soonest first, with registered/capacity; one button to the events screen."""
    items: list[nav.AttentionItem] = []
    for cap in _manager_caps(ctx):
        if not isinstance(cap, BookingCapability) or cap.preset != "events" or cap.start_field is None:
            continue
        route = _route_payload(EVENTS_ROUTE, ctx, cap)
        resource = ctx.spec.resource(cap.resource)
        if route is None or resource is None:
            continue
        soon: list[tuple[datetime, Any]] = []
        for record in await ctx.store.list_records(resource.key):
            start = formatting.parse_datetime(record.data.get(cap.start_field))
            if start is not None and ctx.now <= start <= ctx.now + EVENTS_WINDOW:
                soon.append((start, record))
        if not soon:
            continue
        soon.sort(key=lambda pair: (pair[0], pair[1].id))
        lines: list[str] = []
        for start, record in soon[:EVENTS_SHOWN]:
            going = await ctx.store.count_records(cap.key, status_in=[CONFIRMED], item_id=record.id)
            capacity = _capacity(cap, record)
            people = (
                _fill(tx.GOING_OF, going=_num(going), capacity=_num(capacity))
                if capacity
                else _fill(tx.GOING, going=_num(going))
            )
            title = record.data.get(resource.title_field) or "#" + _num(record.id)
            when = formatting.format_datetime(start, ctx.tz)
            lines.append(_fill(tx.ATTENTION_EVENT, title=title, when=when, going=people))
        if len(soon) > EVENTS_SHOWN:
            lines.append(_fill(tx.ATTENTION_EVENT_MORE, count=_num(len(soon) - EVENTS_SHOWN)))
        button = nav.nav_button(_fill(tx.ATTENTION_EVENTS_BUTTON, count=_num(len(soon))), route)
        items.append(nav.AttentionItem(lines[0], button))
        items += [nav.AttentionItem(line) for line in lines[1:]]
    return items


nav.register_route(replace(nav.ROUTES[REQUESTS_ROUTE], resolve=show_requests))
nav.register_attention(request_attention)
nav.register_attention(event_attention)
nav.register_summary(summary)
