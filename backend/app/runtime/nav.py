"""Deterministic Telegram navigation: role homes, stable routes, Back/Home, stale handling (U4).

The menu a user sees is compiled here from the spec's enabled capabilities and the actor's role.
``spec.menu`` (LLM-written) no longer drives navigation: it is only a legacy lookup for old
``menu:open:<key>`` buttons (``runtime.py``). Labels are central copy (``texts/nav.py``) plus the
business nouns the spec already holds (a resource's ``label_plural``, a capability's ``title``).

Callback contract (``runtime/callbacks.py``, additive): ``nav:go:<route>``, at most 64 bytes, ASCII
machine ids only. A route is ``<route id>[~<n>][.<arg>...]``:

  route id   a key of ``ROUTES`` (it may itself contain dots, e.g. ``evt.mine``, ``mgr.evt.new``);
             the longest registered id wins, the remaining dot segments are args
  ~<n>       capability-bound routes only: the n-th capability (1-based, no suffix = 1) of the
             route's candidate list, which is EVERY capability of the bound type in spec order,
             enabled or not, so enabling or disabling one capability never renumbers the others
  args       record ids, page keys, capability keys (``[a-z0-9_]``)

Route table (id -> binding -> parent; role is the minimum effective role):

  home         role home: managers -> the manager home, everyone else -> the user home      (root)
  cust         the user home for the actor's role; managers reach it as «👁 نمای مشتری»      (root)
  shop         orders capabilities, then catalog capabilities -> engine.open(main)          home
  shop.i.<id>  same candidates as shop -> engine.on_callback(item, <id>)                    shop
  cart         orders capabilities -> engine.on_callback(cart)                              shop
  ord          orders capabilities -> engine.open(mine)                                     home
  evt          booking capabilities with preset "events" -> engine.open(main)               home
  evt.mine     same -> engine.open(mine)                                                    home
  bkg          booking capabilities with preset "booking" -> engine.open(main)              home
  bkg.mine     same -> engine.open(mine)                                                    home
  sup          request capabilities -> engine.open(main) (the engine shows staff its queue) home
  sup.mine     request capabilities -> engine.open(mine)                                    sup
  info[.<pg>]  info capabilities -> engine.open(main), or on_callback(show, <pg>)           home
  staff.q      request capabilities (staff) -> engine.open(main), the staff queue           home
  mgr          manager home (managers)                                                      (root)
  mgr.ord[.<a>] orders capabilities (managers) -> the order queue (``runtime/manager_orders.py``) mgr
  mgr.evt[.<id>] events capabilities (managers) -> the events screens (``runtime/manager_events.py``) mgr
  mgr.evt.new  events capabilities (managers) -> the new-event form (same module)           mgr.evt
  mgr.req      request capabilities (managers) -> engine.open(main), the request queue,     mgr
               framed with the manager heading by ``runtime/manager.py``
  mgr.rep[.<k>] reports (managers): the report list; <k> = "all" or a capability key       mgr
  mgr.team     managers -> the team screen (``runtime/manager_team.py``)                    mgr

A route with ``ready=False`` is a placeholder: role homes leave it out and pressing it answers with
a short "not ready yet" notice plus the manager home. A later unit makes it real by registering a
replacement with ``register_route(replace(ROUTES["mgr.ord"], resolve=..., ready=True))``.

Resolution (``go``): unknown route, a role below the route's, or a capability that is missing,
disabled or not allowed for the actor -> the role home sent as a NEW message headed by the stale
notice (the pressed message is never modified). Every navigation clears the actor's session
(the runtime does it before calling ``go``), like the legacy menu did.

Homes (``compile_home``): fixed canonical order, only enabled capabilities the role may use.
  user home   shop entries, ord, evt, evt.mine, bkg, bkg.mine, sup, info; staff add staff.q.
              A catalog is left out when an orders capability the role may use sells from the
              same resource (one shop). One entry per capability; when a route has several
              entries their labels name the capability.
  manager     summary lines (``register_summary``), attention lines (``register_attention``),
              then mgr.ord, mgr.evt, mgr.req, mgr.rep (when a capability has metrics), mgr.team,
              and «👁 نمای مشتری» (cust). The manager screens live in ``runtime/manager.py`` and
              the modules it imports; they register their routes and providers on import, and
              ``load_extensions`` imports them lazily before any route or home is resolved, so the
              registry is complete whoever imported nav first (a top-level import would be circular).
  Owners and managers land on the manager home on /start and on Home; the customer home stays
  reachable through ``cust``. Back is the route's parent (for a manager, a user route's parent
  ``home`` becomes ``cust``); Home is always ``nav:go:home``.

Public API for later units:
  ROUTES / register_route(route)            the registry; replace or add routes
  route_payload(route_id, ordinal, *args)   build a route string (validated, <= 64 bytes)
  nav_data(route) / nav_button(label, route) callback data / a Button for a route
  compile_home(spec, role) / compile_user_home(spec, role) / virtual_menu(spec)
  heading(spec, route, *extra, cap=None)    "title › extra" breadcrumb line (also ``ctx.heading``)
  back_route(ctx, route) / back_button(ctx, route)
  route_for(spec, cap, view)                the user route that opens (cap, view), or None
  show_home(ctx, ...), show_user_home(ctx, ...), stale_home(ctx), go(ctx, route)
  register_attention(provider)              manager-home attention lines (async, U6)
  register_summary(provider)                manager-home lines under the heading (async, U6)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.botspec.models import (
    AnyCapability,
    BookingCapability,
    BotSpec,
    CatalogCapability,
    InfoCapability,
    OrdersCapability,
    RequestCapability,
    Role,
)
from app.botspec.text_keys import fill_text
from app.reporting.metrics import metrics_for
from app.roles import can_run_owner_actions
from app.runtime.callbacks import (
    ACT_CART,
    ACT_GO,
    ACT_ITEM,
    ACT_SHOW,
    NAV,
    CallbackError,
    make_callback,
)
from app.runtime.contracts import Actor, Button, audience_allows
from app.runtime.engines import EngineUnavailable, get_engine
from app.runtime.engines.base import Engine
from app.runtime.texts import common
from app.runtime.texts import nav as tx

if TYPE_CHECKING:
    from app.runtime.ctx import Ctx

Rows = list[list[Button]]
Resolver = Callable[["Ctx", "Target"], Awaitable[None]]
Candidates = Callable[[BotSpec], list[AnyCapability]]
Labeler = Callable[[BotSpec, AnyCapability | None, bool], str]

HOME = "home"
CUST = "cust"
MGR = "mgr"
_ROLE_RANK: dict[Role, int] = {"customer": 0, "staff": 1, "manager": 2}
_MAX_ORDINAL_DIGITS = 3


# --- model ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    """One navigation route.

    ``label(spec, cap, named)`` is both the entry label and the breadcrumb title (``named``: the
    route has several entries, so the label names its capability; an empty label is left out of
    breadcrumbs). ``candidates`` makes the route capability-bound (``~<n>`` indexes it).
    ``max_args`` is the number of dot-separated args the route accepts after its id.
    """

    id: str
    parent: str | None
    resolve: Resolver
    label: Labeler
    role: Role = "customer"
    candidates: Candidates | None = None
    view: str = "main"
    max_args: int = 0
    ready: bool = True


@dataclass(frozen=True)
class Target:
    """A parsed and checked route: what a resolver gets."""

    route: Route
    payload: str
    ordinal: int
    args: tuple[str, ...]
    cap: AnyCapability | None

    @property
    def arg(self) -> str:
        return self.args[0] if self.args else ""


@dataclass(frozen=True)
class Entry:
    """One home entry. ``key``/``label``/``capability``/``view`` mirror ``MenuItem`` so testing code
    can use an Entry where it used a menu item; ``key`` is the route (``nav:go:<key>``).
    ``on_home`` is False for entries reached inside another screen (``sup.mine``)."""

    key: str
    label: str
    capability: str | None = None
    view: str | None = None
    on_home: bool = True

    @property
    def data(self) -> str:
        return nav_data(self.key)

    def button(self) -> Button:
        return Button(label=self.label, data=self.data)


@dataclass(frozen=True)
class AttentionItem:
    """One "needs attention" line on the manager home, with an optional button into the list."""

    text: str
    button: Button | None = None


AttentionProvider = Callable[["Ctx"], Awaitable[list[AttentionItem]]]
ATTENTION: list[AttentionProvider] = []


def register_attention(provider: AttentionProvider) -> None:
    """Add a provider of manager-home attention items (called in registration order)."""
    if provider not in ATTENTION:
        ATTENTION.append(provider)


SummaryProvider = Callable[["Ctx", list[AttentionItem]], Awaitable[list[str]]]
SUMMARY: list[SummaryProvider] = []


def register_summary(provider: SummaryProvider) -> None:
    """Add a provider of manager-home lines shown right under the heading (before the attention
    block). It gets the attention items already collected, so it can also say that nothing is
    waiting."""
    if provider not in SUMMARY:
        SUMMARY.append(provider)


def load_extensions() -> None:
    """Import the manager screens (``runtime/manager.py`` and what it imports) and the event
    management screens (``runtime/manager_events.py``), which register their routes and home
    providers on import. Cached by Python after the first call."""
    from app.runtime import manager, manager_events  # noqa: F401  (they import nav: no top-level import)


# --- payloads ------------------------------------------------------------------------------------


def nav_data(route: str) -> str:
    """``nav:go:<route>``; raises CallbackError if it is not ASCII machine ids or over 64 bytes."""
    return make_callback(NAV, ACT_GO, route)


def nav_button(label: str, route: str) -> Button:
    return Button(label=label, data=nav_data(route))


def route_payload(route_id: str, ordinal: int = 1, *args: str | int) -> str:
    """``("shop.i", 2, 15) -> "shop.i~2.15"``; validated like ``nav_data``."""
    head = route_id if ordinal <= 1 else f"{route_id}~{ordinal}"
    payload = ".".join([head, *(str(a) for a in args)])
    nav_data(payload)  # raises CallbackError when invalid or too long
    return payload


def home_button() -> Button:
    return nav_button(tx.HOME, HOME)


def parse_route(payload: str) -> tuple[Route, int, tuple[str, ...]] | None:
    """``(route, ordinal, args)`` for a route string, or None when no registered route matches."""
    if not payload:
        return None
    try:
        nav_data(payload)
    except CallbackError:
        return None
    tokens = payload.split(".")
    for k in range(len(tokens), 0, -1):
        last, sep, num = tokens[k - 1].partition("~")
        ordinal = 1
        if sep:
            if not (num.isascii() and num.isdigit()) or len(num) > _MAX_ORDINAL_DIGITS or int(num) < 1:
                return None
            ordinal = int(num)
        route = ROUTES.get(".".join([*tokens[: k - 1], last]))
        if route is None:
            continue
        args = tuple(tokens[k:])
        if len(args) > route.max_args or any(not a or "~" in a for a in args):
            return None
        if ordinal != 1 and route.candidates is None:
            return None
        return route, ordinal, args
    return None


# --- capability helpers --------------------------------------------------------------------------


def _role_actor(role: Role) -> Actor:
    return Actor(id="_nav", display_name="", role=role)


def usable(cap: AnyCapability, actor: Actor) -> bool:
    """Enabled and allowed for the actor (``ctx.capability_available``)."""
    return cap.enabled and audience_allows(cap.audience, actor)


def _role_allows(min_role: Role, actor: Actor) -> bool:
    return _ROLE_RANK[actor.effective_role] >= _ROLE_RANK[min_role]


def _orders(spec: BotSpec) -> list[AnyCapability]:
    return [c for c in spec.capabilities if isinstance(c, OrdersCapability)]


def _shop(spec: BotSpec) -> list[AnyCapability]:
    return _orders(spec) + [c for c in spec.capabilities if isinstance(c, CatalogCapability)]


def _events(spec: BotSpec) -> list[AnyCapability]:
    return [c for c in spec.capabilities if isinstance(c, BookingCapability) and c.preset == "events"]


def _bookings(spec: BotSpec) -> list[AnyCapability]:
    return [c for c in spec.capabilities if isinstance(c, BookingCapability) and c.preset != "events"]


def _requests(spec: BotSpec) -> list[AnyCapability]:
    return [c for c in spec.capabilities if isinstance(c, RequestCapability)]


def _infos(spec: BotSpec) -> list[AnyCapability]:
    return [c for c in spec.capabilities if isinstance(c, InfoCapability)]


def _plural(spec: BotSpec, cap: AnyCapability | None) -> str:
    """The plural business noun of a capability's resource, else its title."""
    resource_key = getattr(cap, "resource", None)
    resource = spec.resource(resource_key) if isinstance(resource_key, str) else None
    if resource is not None and resource.label_plural.strip():
        return resource.label_plural
    return cap.title if cap is not None else ""


def _fill(template: str, **values: str) -> str:
    return fill_text(template, values)


# --- labels --------------------------------------------------------------------------------------


def _fixed(text: str) -> Labeler:
    return lambda spec, cap, named: text


def _shop_label(spec: BotSpec, cap: AnyCapability | None, named: bool) -> str:
    if isinstance(cap, CatalogCapability):
        return _fill(tx.BROWSE, label=_plural(spec, cap))
    return _fill(tx.SHOP_NAMED, title=cap.title) if named and cap is not None else tx.SHOP


def _orders_label(spec: BotSpec, cap: AnyCapability | None, named: bool) -> str:
    return _fill(tx.MY_ORDERS_NAMED, title=cap.title) if named and cap is not None else tx.MY_ORDERS


def _plural_label(template: str) -> Labeler:
    return lambda spec, cap, named: _fill(template, label=_plural(spec, cap))


def _mine_label(plain: str, named_template: str) -> Labeler:
    def label(spec: BotSpec, cap: AnyCapability | None, named: bool) -> str:
        return _fill(named_template, label=_plural(spec, cap)) if named else plain

    return label


def _request_label(spec: BotSpec, cap: AnyCapability | None, named: bool) -> str:
    if cap is None:
        return tx.SUPPORT
    if cap.key == "support" and not named:
        return tx.SUPPORT
    return _fill(tx.REQUEST, title=cap.title)


def _info_label(spec: BotSpec, cap: AnyCapability | None, named: bool) -> str:
    return _fill(tx.INFO, title=cap.title if cap is not None else "")


def _named(plain: str) -> Labeler:
    """A fixed label that names its capability when the route has several entries."""

    def label(spec: BotSpec, cap: AnyCapability | None, named: bool) -> str:
        return f"{plain} · {cap.title}" if named and cap is not None else plain

    return label


# --- resolvers -----------------------------------------------------------------------------------


def _engine_for(ctx: Ctx, cap: AnyCapability) -> Engine | None:
    try:
        return get_engine(cap.type)
    except EngineUnavailable:
        ctx.reply(common.NOT_AVAILABLE, home_rows(ctx))
        return None


def _open(view: str) -> Resolver:
    async def resolve(ctx: Ctx, target: Target) -> None:
        assert target.cap is not None
        engine = _engine_for(ctx, target.cap)
        if engine is not None:
            await engine.open(ctx, target.cap, view)

    return resolve


def _action(action: str, *, fallback_view: str | None = "main") -> Resolver:
    """``engine.on_callback(action, <first arg>)``; with no arg, ``engine.open(fallback_view)``."""

    async def resolve(ctx: Ctx, target: Target) -> None:
        assert target.cap is not None
        engine = _engine_for(ctx, target.cap)
        if engine is None:
            return
        if not target.args and fallback_view is not None:
            await engine.open(ctx, target.cap, fallback_view)
            return
        await engine.on_callback(ctx, target.cap, action, target.arg)

    return resolve


async def _home(ctx: Ctx, target: Target) -> None:
    await show_home(ctx)


async def _cust(ctx: Ctx, target: Target) -> None:
    show_user_home(ctx)


async def _mgr(ctx: Ctx, target: Target) -> None:
    await show_manager_home(ctx)


async def _reports(ctx: Ctx, target: Target) -> None:
    from app.runtime import manager  # manager imports nav

    if not target.args:
        manager.show_panel(ctx)
        return
    if not await manager.show_report(ctx, target.arg):
        await stale_home(ctx)


async def _coming_soon(ctx: Ctx, target: Target) -> None:
    await show_manager_home(ctx, notice=tx.COMING_SOON)


# --- registry ------------------------------------------------------------------------------------

ROUTES: dict[str, Route] = {}


def register_route(route: Route) -> Route:
    """Add or replace a route (later units extend the table this way)."""
    ROUTES[route.id] = route
    return route


for _route in (
    Route(HOME, None, _home, _fixed(tx.HOME)),
    Route(CUST, None, _cust, _fixed(tx.CUSTOMER_VIEW)),
    Route("shop", HOME, _open("main"), _shop_label, candidates=_shop),
    Route("shop.i", "shop", _action(ACT_ITEM), _fixed(""), candidates=_shop, max_args=1),
    Route("cart", "shop", _action(ACT_CART, fallback_view=None), _fixed(tx.CART), candidates=_orders),
    Route("ord", HOME, _open("mine"), _orders_label, candidates=_orders, view="mine"),
    Route("evt", HOME, _open("main"), _plural_label(tx.EVENTS), candidates=_events),
    Route(
        "evt.mine",
        HOME,
        _open("mine"),
        _mine_label(tx.MY_EVENTS, tx.MY_EVENTS_NAMED),
        candidates=_events,
        view="mine",
    ),
    Route("bkg", HOME, _open("main"), _plural_label(tx.BOOKING), candidates=_bookings),
    Route(
        "bkg.mine",
        HOME,
        _open("mine"),
        _mine_label(tx.MY_BOOKINGS, tx.MY_BOOKINGS_NAMED),
        candidates=_bookings,
        view="mine",
    ),
    Route("sup", HOME, _open("main"), _request_label, candidates=_requests),
    Route("sup.mine", "sup", _open("mine"), _fixed(tx.MY_REQUESTS), candidates=_requests, view="mine"),
    Route("info", HOME, _action(ACT_SHOW), _info_label, candidates=_infos, max_args=1),
    Route("staff.q", HOME, _open("main"), _named(tx.STAFF_QUEUE), role="staff", candidates=_requests),
    Route(MGR, None, _mgr, _fixed(tx.MANAGER_SHORT), role="manager"),
    Route(
        "mgr.ord",
        MGR,
        _coming_soon,
        _named(tx.MANAGE_ORDERS),
        role="manager",
        candidates=_orders,
        ready=False,
    ),
    Route(
        "mgr.evt",
        MGR,
        _action(ACT_ITEM),
        _named(tx.MANAGE_EVENTS),
        role="manager",
        candidates=_events,
        max_args=1,
    ),
    Route(
        "mgr.evt.new",
        "mgr.evt",
        _coming_soon,
        _fixed(tx.NEW_EVENT),
        role="manager",
        candidates=_events,
        ready=False,
    ),
    Route("mgr.req", MGR, _open("main"), _named(tx.MANAGE_REQUESTS), role="manager", candidates=_requests),
    Route("mgr.rep", MGR, _reports, _fixed(tx.REPORTS), role="manager", max_args=1),
    Route("mgr.team", MGR, _coming_soon, _fixed(tx.TEAM), role="manager", ready=False),
):
    register_route(_route)


# --- compiler ------------------------------------------------------------------------------------

USER_ROUTES: tuple[str, ...] = ("shop", "ord", "evt", "evt.mine", "bkg", "bkg.mine", "sup", "info")
MANAGER_ROUTES: tuple[str, ...] = ("mgr.ord", "mgr.evt", "mgr.req")


def _cap_entries(spec: BotSpec, route_id: str, keep: Callable[[AnyCapability], bool]) -> list[Entry]:
    """One entry per kept candidate of a capability-bound route, ordinals from the full list."""
    route = ROUTES.get(route_id)
    if route is None or route.candidates is None or not route.ready:
        return []
    kept = [(n, cap) for n, cap in enumerate(route.candidates(spec), 1) if keep(cap)]
    named = len(kept) > 1
    return [
        Entry(
            key=route_payload(route_id, n),
            label=route.label(spec, cap, named),
            capability=cap.key,
            view=route.view,
        )
        for n, cap in kept
    ]


def compile_user_home(spec: BotSpec, role: Role) -> list[Entry]:
    """The user home for ``role`` (customers, staff, and a manager's customer view)."""
    actor = _role_actor(role)
    sold = {c.resource for c in _orders(spec) if isinstance(c, OrdersCapability) and usable(c, actor)}

    def keep(cap: AnyCapability) -> bool:
        if not usable(cap, actor):
            return False
        return not (isinstance(cap, CatalogCapability) and cap.resource in sold)  # one shop

    entries: list[Entry] = []
    for route_id in USER_ROUTES:
        entries += _cap_entries(spec, route_id, keep)
    if role == "staff":
        entries += _cap_entries(
            spec, "staff.q", lambda c: usable(c, actor) and can_run_owner_actions(c, actor)
        )
    return entries


def compile_manager_home(spec: BotSpec) -> list[Entry]:
    """The manager home entries (without attention items): manage sections, reports, team, and
    the customer view."""
    load_extensions()
    actor = _role_actor("manager")
    entries: list[Entry] = []
    for route_id in MANAGER_ROUTES:
        entries += _cap_entries(spec, route_id, lambda c: usable(c, actor))
    if any(c.enabled and metrics_for(c) for c in spec.capabilities):
        entries.append(Entry(key="mgr.rep", label=tx.REPORTS))
    if ROUTES["mgr.team"].ready:
        entries.append(Entry(key="mgr.team", label=tx.TEAM))
    entries.append(Entry(key=CUST, label=tx.CUSTOMER_VIEW))
    return entries


def compile_home(spec: BotSpec, role: Role) -> list[Entry]:
    """The home ``role`` lands on: the manager home for managers, else the user home."""
    return compile_manager_home(spec) if role == "manager" else compile_user_home(spec, role)


def virtual_menu(spec: BotSpec) -> list[Entry]:
    """Every (capability, view) entry point a user can reach from a user home, for any role (the
    union of the customer, staff and manager user homes, first appearance wins), plus the nested
    ``sup.mine`` entries (``on_home=False``). Testing (``derive``, drivers) uses it where it used
    ``spec.menu``; ``key`` is the route."""
    seen: dict[str, Entry] = {}
    roles: tuple[Role, ...] = ("customer", "staff", "manager")
    for role in roles:
        for e in compile_user_home(spec, role):
            if e.capability is not None and not e.key.startswith("staff.q"):
                seen.setdefault(e.key, e)
    out = list(seen.values())
    for e in [e for e in out if e.key.split("~")[0] == "sup"]:
        mine = e.key.replace("sup", "sup.mine", 1)
        out.append(Entry(key=mine, label=tx.MY_REQUESTS, capability=e.capability, view="mine", on_home=False))
    return out


def route_for(spec: BotSpec, cap: AnyCapability | str, view: str = "main") -> str | None:
    """The user route that opens ``cap``'s ``view`` (with its ordinal), or None."""
    key = cap if isinstance(cap, str) else cap.key
    for route_id in (*USER_ROUTES, "sup.mine"):
        route = ROUTES.get(route_id)
        if route is None or route.candidates is None or route.view != view:
            continue
        for n, candidate in enumerate(route.candidates(spec), 1):
            if candidate.key == key:
                return route_payload(route_id, n)
    return None


# --- breadcrumbs, back ---------------------------------------------------------------------------


def _resolve_cap(spec: BotSpec, route: Route, ordinal: int) -> AnyCapability | None:
    if route.candidates is None:
        return None
    candidates = route.candidates(spec)
    return candidates[ordinal - 1] if 0 < ordinal <= len(candidates) else None


def heading(spec: BotSpec, route: str, *extra: str, cap: AnyCapability | None = None) -> str:
    """The breadcrumb line of a screen: the titles of the route's ancestors (roots left out) and
    the route itself, then ``extra``, joined by « › ». ``route`` may carry an ordinal (``evt~2``);
    ``cap`` overrides the capability the titles are named after."""
    parsed = parse_route(route)
    if parsed is None:
        return tx.CRUMB_SEPARATOR.join(e for e in extra if e)
    current, ordinal, _ = parsed
    cap = cap or _resolve_cap(spec, current, ordinal)
    titles: list[str] = []
    node: Route | None = current
    while node is not None and node.parent is not None:
        node_cap = None
        if cap is not None and node.candidates is not None:
            node_cap = cap if any(c.key == cap.key for c in node.candidates(spec)) else None
        title = node.label(spec, node_cap, False)
        if title:
            titles.append(title)
        node = ROUTES.get(node.parent)
    titles.reverse()
    return tx.CRUMB_SEPARATOR.join([*titles, *(e for e in extra if e)])


def back_route(ctx: Ctx, route: str) -> str:
    """The parent of ``route`` for this actor, keeping the capability's ordinal when the parent is
    bound to the same capability; a manager's ``home`` parent is the customer view."""
    parsed = parse_route(route)
    if parsed is None:
        return HOME
    current, ordinal, _ = parsed
    parent_id = current.parent or HOME
    if parent_id == HOME and ctx.actor.effective_role == "manager" and current.role != "manager":
        return CUST
    parent = ROUTES.get(parent_id)
    cap = _resolve_cap(ctx.spec, current, ordinal)
    if parent is not None and parent.candidates is not None and cap is not None:
        for n, candidate in enumerate(parent.candidates(ctx.spec), 1):
            if candidate.key == cap.key:
                return route_payload(parent_id, n)
    return parent_id


def back_button(ctx: Ctx, route: str) -> Button:
    return nav_button(tx.BACK, back_route(ctx, route))


# --- homes ---------------------------------------------------------------------------------------


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _user_home_view(ctx: Ctx, text: str | None = None) -> tuple[str, Rows]:
    role = ctx.actor.effective_role
    entries = compile_user_home(ctx.spec, role)
    rows: Rows = [[e.button()] for e in entries]
    if text is None:
        lines = [_fill(tx.HOME_HEADING, business=ctx.spec.bot.name)]
        welcome = _first_line(ctx.spec.bot.welcome_text)
        if welcome:
            lines.append(welcome)
        lines.append(tx.HOME_HINT if entries else tx.HOME_EMPTY)
        text = "\n".join(lines)
    if role == "manager":
        text = f"{tx.CUSTOMER_VIEW_NOTE}\n\n{text}"
        rows.append([nav_button(tx.BACK, MGR)])
    return text, rows


def _manager_home_view(
    ctx: Ctx, attention: list[AttentionItem], summary: list[str] | None = None
) -> tuple[str, Rows]:
    lines = [_fill(tx.MANAGER_HEADING, business=ctx.spec.bot.name), *(summary or [])]
    rows: Rows = []
    if attention:
        lines.append(tx.ATTENTION_HEADING)
        lines += [f"• {item.text}" for item in attention]
        rows += [[item.button] for item in attention if item.button is not None]
    lines.append(tx.MANAGER_HINT)
    rows += [[e.button()] for e in compile_manager_home(ctx.spec)]
    return "\n".join(lines), rows


def home_rows(ctx: Ctx) -> Rows:
    """The buttons of the actor's role home (no attention items; synchronous)."""
    if ctx.actor.effective_role == "manager":
        return _manager_home_view(ctx, [])[1]
    return _user_home_view(ctx)[1]


def _with_notice(notice: str | None, text: str) -> str:
    return f"{notice}\n\n{text}" if notice else text


def show_home_now(ctx: Ctx, text: str | None = None, edit: bool | None = None) -> None:
    """Synchronous role home (no attention items): ``ctx.show_menu``."""
    if ctx.actor.effective_role == "manager":
        home_text, rows = _manager_home_view(ctx, [])
        ctx.reply(text if text is not None else home_text, rows, edit=edit)
        return
    home_text, rows = _user_home_view(ctx, text)
    ctx.reply(home_text, rows, edit=edit)


def show_user_home(
    ctx: Ctx, text: str | None = None, *, notice: str | None = None, edit: bool | None = None
) -> None:
    """The user home for the actor's role (``cust``; for a manager with the customer-view note
    and a Back to the manager home). ``text`` replaces the heading (the welcome text on /start)."""
    home_text, rows = _user_home_view(ctx, text)
    ctx.reply(_with_notice(notice, home_text), rows, edit=edit)


async def _attention(ctx: Ctx) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for provider in ATTENTION:
        items += await provider(ctx)
    return items


async def _summary(ctx: Ctx, attention: list[AttentionItem]) -> list[str]:
    lines: list[str] = []
    for provider in SUMMARY:
        lines += await provider(ctx, attention)
    return lines


async def show_manager_home(ctx: Ctx, *, notice: str | None = None, edit: bool | None = None) -> None:
    load_extensions()
    attention = await _attention(ctx)
    text, rows = _manager_home_view(ctx, attention, await _summary(ctx, attention))
    ctx.reply(_with_notice(notice, text), rows, edit=edit)


async def show_home(
    ctx: Ctx, text: str | None = None, *, notice: str | None = None, edit: bool | None = None
) -> None:
    """The actor's role home: the manager home for managers (``text`` is ignored there), else the
    user home with ``text`` (default: the heading) in place of the heading."""
    if ctx.actor.effective_role == "manager":
        await show_manager_home(ctx, notice=notice, edit=edit)
    else:
        show_user_home(ctx, text, notice=notice, edit=edit)


async def stale_home(ctx: Ctx) -> None:
    """A navigation target that no longer exists: the role home as a NEW message headed by the
    stale notice; the pressed message is left as it is."""
    await show_home(ctx, notice=tx.STALE, edit=False)


# --- resolution ----------------------------------------------------------------------------------


async def go(ctx: Ctx, route: str) -> None:
    """Resolve ``nav:go:<route>`` (module docstring). Never raises for bad input."""
    load_extensions()
    parsed = parse_route(route)
    if parsed is None:
        await stale_home(ctx)
        return
    current, ordinal, args = parsed
    if not _role_allows(current.role, ctx.actor):
        await stale_home(ctx)
        return
    cap: AnyCapability | None = None
    if current.candidates is not None:
        cap = _resolve_cap(ctx.spec, current, ordinal)
        if cap is None or not usable(cap, ctx.actor):
            await stale_home(ctx)
            return
    target = Target(route=current, payload=route, ordinal=ordinal, args=args, cap=cap)
    if not current.ready:
        await _coming_soon(ctx, target)
        return
    await current.resolve(ctx, target)


__all__ = [
    "ATTENTION",
    "CUST",
    "HOME",
    "MGR",
    "ROUTES",
    "SUMMARY",
    "AttentionItem",
    "Entry",
    "Route",
    "Target",
    "back_button",
    "back_route",
    "compile_home",
    "compile_manager_home",
    "compile_user_home",
    "go",
    "heading",
    "home_button",
    "home_rows",
    "load_extensions",
    "nav_button",
    "nav_data",
    "parse_route",
    "register_attention",
    "register_route",
    "register_summary",
    "route_for",
    "route_payload",
    "show_home",
    "show_home_now",
    "show_manager_home",
    "show_user_home",
    "stale_home",
    "usable",
    "virtual_menu",
]
