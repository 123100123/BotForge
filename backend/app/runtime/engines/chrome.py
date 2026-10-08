"""Screen chrome shared by the customer engines (U5): breadcrumb headings and Back buttons.

Engines name a capability's screens by their navigation route (``runtime/nav.py``): the route that
opens a capability's view carries the capability's ordinal (``shop~2``), so a heading or a Back
button built from it stays right when a bot has several capabilities of one kind.
"""

from app.botspec.models import AnyCapability
from app.runtime import nav
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx
from app.runtime.texts.nav import BACK


def route_of(ctx: Ctx, cap: AnyCapability, view: str = "main") -> str:
    """The user route that opens ``cap``'s ``view`` (``shop~2``, ``evt.mine``), else ``home``."""
    return nav.route_for(ctx.spec, cap, view) or nav.HOME


def sub_route(route: str, sub_id: str, *args: str | int) -> str:
    """``("shop~2", "shop.i", 15) -> "shop.i~2.15"``: a child route bound to the same capability."""
    _, _, ordinal = route.partition("~")
    return nav.route_payload(sub_id, int(ordinal) if ordinal.isascii() and ordinal.isdigit() else 1, *args)


def heading(ctx: Ctx, cap: AnyCapability, view: str = "main", *extra: str) -> str:
    """Breadcrumb line of ``cap``'s ``view`` screen, then ``extra`` crumbs."""
    return ctx.heading(route_of(ctx, cap, view), *extra, cap=cap)


def to_route(route: str, label: str | None = None) -> Button:
    """A button to ``route`` itself (default label «‹ بازگشت»): Back to a screen that is not the
    route's parent, e.g. from a sub-screen to the capability's main screen."""
    return nav.nav_button(label or BACK, route)


def back_to(ctx: Ctx, route: str, label: str | None = None) -> Button:
    """Back to the parent of ``route``; ``label`` replaces the default «‹ بازگشت»."""
    if label is None:
        return nav.back_button(ctx, route)
    return nav.nav_button(label, nav.back_route(ctx, route))
