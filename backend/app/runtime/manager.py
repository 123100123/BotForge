"""The Telegram manager panel: reports on demand for managers, deterministic, no LLM.

Reached through two pseudo menu items of the ``menu:open:<item>`` callback (spec menu keys cannot
start with ``_``, so these cannot collide with a real item and the callback contract is unchanged):

  menu:open:_mgr           the panel: "خلاصه کسب‌وکار" plus one button per enabled capability that has
                           metrics, and "بازگشت" to the main menu
  menu:open:_rep.all       the Overview (``reporting.service.overview``) of the last 7 days
  menu:open:_rep.<cap_key> that capability's report (``capability_report``), same period

Only managers (``actor.effective_role``; the owner is a manager) get the panel; the runtime answers
anyone else with the stale reply. Everything goes through ``Ctx``, so the simulator shows it too.
The reporting engine depends only on ``Store``, ``botspec`` and the REST schemas, so this module
keeps the runtime free of database and API imports. Records are only read.
"""

from typing import TYPE_CHECKING

from app.reporting import service as reporting
from app.reporting.metrics import metrics_for
from app.reporting.telegram import render_overview_text, render_report_text
from app.runtime.callbacks import ACT_HOME, ACT_OPEN, MENU, make_callback
from app.runtime.contracts import Button
from app.runtime.texts import common

if TYPE_CHECKING:
    from app.runtime.ctx import Ctx

PANEL_ITEM = "_mgr"
REPORT_PREFIX = "_rep."
ALL_REPORT = "all"
PERIOD = "7d"

PANEL_LABEL = "پنل مدیریت"
OVERVIEW_LABEL = "خلاصه کسب‌وکار"
PANEL_TEXT = "پنل مدیریت\nیک گزارش را انتخاب کنید."


def is_manager_item(item_key: str) -> bool:
    return item_key == PANEL_ITEM or item_key.startswith(REPORT_PREFIX)


def panel_button() -> Button:
    return Button(label=PANEL_LABEL, data=make_callback(MENU, ACT_OPEN, PANEL_ITEM))


def _report_button(label: str, key: str) -> Button:
    return Button(label=label, data=make_callback(MENU, ACT_OPEN, REPORT_PREFIX + key))


async def open_item(ctx: "Ctx", item_key: str) -> None:
    """Handle ``menu:open:<item_key>`` for a manager pseudo item; anyone else gets the stale reply."""
    if ctx.actor.effective_role != "manager":
        ctx.stale()
        return
    if item_key == PANEL_ITEM:
        _panel(ctx)
        return
    key = item_key.removeprefix(REPORT_PREFIX)
    back = [
        [Button(label=common.BACK, data=make_callback(MENU, ACT_OPEN, PANEL_ITEM))],
        ctx.home_row(),
    ]
    if key == ALL_REPORT:
        overview = await reporting.overview(ctx.store, ctx.spec, PERIOD, ctx.now)
        ctx.reply(render_overview_text(overview), back)
        return
    cap = ctx.spec.capability(key)
    if cap is None or not cap.enabled or not metrics_for(cap):
        ctx.stale()
        return
    report = await reporting.capability_report(ctx.store, ctx.spec, cap, PERIOD, ctx.now)
    ctx.reply(render_report_text(report), back)


def _panel(ctx: "Ctx") -> None:
    rows = [[_report_button(OVERVIEW_LABEL, ALL_REPORT)]]
    rows += [
        [_report_button(cap.title, cap.key)]
        for cap in ctx.spec.capabilities
        if cap.enabled and cap.key != ALL_REPORT and metrics_for(cap)
    ]
    rows.append([Button(label=common.BACK, data=make_callback(MENU, ACT_HOME))])
    ctx.reply(PANEL_TEXT, rows)
