"""The Telegram manager panel (W2-SCHED): button, panel, overview and capability reports, gating."""

import subprocess
import sys

from app.runtime.contracts import Actor
from app.runtime.texts import common
from tests.unit.runtime.harness import Harness, button_data, buttons, find_button, text
from tests.unit.runtime.test_orders import CAP, shop_spec

PANEL = "menu:open:_mgr"
OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)
MANAGER = Actor(id="mina", display_name="مینا", role="manager")
STAFF = Actor(id="sam", display_name="سام", role="staff")


async def seeded() -> Harness:
    h = Harness(shop_spec())
    await h.seed(CAP, {"total": 250000, "name": "علی"}, status="new", actor_id="ali")
    await h.seed(CAP, {"total": 100000}, status="new", actor_id="reza")
    h.advance(hours=1)  # report windows end at ``now`` (exclusive)
    return h


async def test_owner_and_managers_see_the_panel_button_customers_do_not() -> None:
    h = await seeded()
    for actor in (OWNER, MANAGER):
        resp = await h.start(actor)
        assert PANEL in button_data(resp)
        assert find_button(resp, "پنل مدیریت").data == PANEL
        assert len(PANEL.encode()) <= 64
    for actor in ("ali", STAFF):
        assert PANEL not in button_data(await h.start(actor))


async def test_panel_lists_overview_and_capabilities_with_metrics() -> None:
    h = await seeded()
    resp = await h.tap(OWNER, PANEL)
    data = button_data(resp)
    assert data[0] == "menu:open:_rep.all"
    assert f"menu:open:_rep.{CAP}" in data
    assert find_button(resp, "فروشگاه").data == f"menu:open:_rep.{CAP}"
    assert data[-1] == "menu:home:"
    assert resp.messages[0].edit is True
    assert all(len(d.encode()) <= 64 for d in data)


async def test_overview_and_capability_report_are_persian_text() -> None:
    h = await seeded()
    overview = await h.tap(OWNER, "menu:open:_rep.all")
    assert "نمای کلی کسب‌وکار" in text(overview)
    assert "۷ روز گذشته" in text(overview)
    assert "• تعداد سفارش‌ها: ۲" in text(overview)  # Persian digits
    assert [b.data for b in buttons(overview)] == [PANEL, "menu:home:"]

    report = await h.tap(OWNER, f"menu:open:_rep.{CAP}")
    assert text(report).startswith("📊 گزارش فروشگاه")
    assert "تومان" in text(report)  # revenue
    assert "درآمد: ۳۵۰" in text(report)


async def test_customers_and_staff_get_the_stale_reply() -> None:
    h = await seeded()
    for actor in ("ali", STAFF):
        for data in (PANEL, "menu:open:_rep.all", f"menu:open:_rep.{CAP}"):
            resp = await h.tap(actor, data)
            assert text(resp) == common.STALE
            assert PANEL not in button_data(resp)


async def test_unknown_or_disabled_report_is_stale_and_the_panel_is_read_only() -> None:
    h = await seeded()
    before = len(h.store.all_records())
    for data in ("menu:open:_rep.nope", "menu:open:_rep.", "menu:open:_other"):
        assert text(await h.tap(OWNER, data)) == common.STALE
    await h.tap(OWNER, "menu:open:_rep.all")
    assert len(h.store.all_records()) == before


def test_runtime_stays_free_of_database_and_api_imports() -> None:
    """Checked in a fresh interpreter: other tests in this process import the whole app."""
    code = (
        "import sys, app.runtime.runtime\n"
        "bad = [m for m in sys.modules if m.startswith(('app.api', 'app.db', 'app.services'))]\n"
        "sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
