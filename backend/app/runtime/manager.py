"""Telegram manager reports, on demand for managers, deterministic, no LLM.

Reached through the nav routes (``runtime/nav.py``; the manager home lists «📊 گزارش‌ها»):

  nav:go:mgr.rep             the report list: "خلاصه کسب‌وکار" plus one button per enabled
                             capability that has metrics; Back to the manager home
  nav:go:mgr.rep.all         the Overview (``reporting.service.overview``) of the last 7 days
  nav:go:mgr.rep.<cap_key>   that capability's report (``capability_report``), same period

Legacy buttons sent before nav routes existed keep working through the runtime's ``menu:open``
aliases (``legacy_route``): ``menu:open:_mgr`` -> the manager home, ``menu:open:_rep.<k>`` ->
``mgr.rep.<k>`` (spec menu keys cannot start with ``_``, so they never collide with a real item).

Only managers (``actor.effective_role``; the owner is a manager) reach these screens; nav answers
anyone else with the stale home. Everything goes through ``Ctx``, so the simulator shows it too.
The reporting engine depends only on ``Store``, ``botspec`` and the REST schemas, so this module
keeps the runtime free of database and API imports. Records are only read.
"""

from typing import TYPE_CHECKING

from app.reporting import service as reporting
from app.reporting.metrics import metrics_for
from app.reporting.telegram import render_overview_text, render_report_text
from app.runtime import nav
from app.runtime.contracts import Button
from app.runtime.texts import nav as nav_texts

if TYPE_CHECKING:
    from app.runtime.ctx import Ctx

PANEL_ITEM = "_mgr"  # legacy menu:open item
REPORT_PREFIX = "_rep."  # legacy menu:open item prefix
ALL_REPORT = "all"
PERIOD = "7d"
REPORTS_ROUTE = "mgr.rep"

OVERVIEW_LABEL = "خلاصه کسب‌وکار"
PANEL_HINT = "یک گزارش را انتخاب کنید."


def is_manager_item(item_key: str) -> bool:
    """A legacy ``menu:open`` pseudo item of the old manager panel."""
    return item_key == PANEL_ITEM or item_key.startswith(REPORT_PREFIX)


def legacy_route(item_key: str) -> str:
    """The nav route a legacy pseudo item now opens (``""`` -> nav's stale home)."""
    if item_key == PANEL_ITEM:
        return nav.MGR
    key = item_key.removeprefix(REPORT_PREFIX)
    return f"{REPORTS_ROUTE}.{key}" if key else ""


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
    rows.append([nav.nav_button(nav_texts.BACK, nav.MGR), nav.home_button()])
    ctx.reply(f"{ctx.heading(REPORTS_ROUTE)}\n{PANEL_HINT}", rows)


async def show_report(ctx: "Ctx", key: str) -> bool:
    """The overview (``all``) or one capability's report; False when there is no such report (a
    missing or disabled capability, or one without metrics)."""
    back = [[nav.nav_button(nav_texts.BACK, REPORTS_ROUTE), nav.home_button()]]
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
