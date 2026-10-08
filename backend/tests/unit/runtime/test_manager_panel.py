"""Telegram manager reports (W2-SCHED, now under the nav routes): manager home entry, report list,
overview and capability reports, legacy ``menu:open:_mgr``/``_rep.*`` aliases, gating."""

import subprocess
import sys

from app.runtime.contracts import Actor
from app.runtime.texts import nav as nav_texts
from tests.unit.runtime.harness import Harness, button_data, buttons, find_button, text
from tests.unit.runtime.test_orders import CAP, shop_spec

REPORTS = "nav:go:mgr.rep"
LEGACY_PANEL = "menu:open:_mgr"
OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)
MANAGER = Actor(id="mina", display_name="مینا", role="manager")
STAFF = Actor(id="sam", display_name="سام", role="staff")


async def seeded() -> Harness:
    h = Harness(shop_spec())
    await h.seed(CAP, {"total": 250000, "name": "علی"}, status="new", actor_id="ali")
    await h.seed(CAP, {"total": 100000}, status="new", actor_id="reza")
    h.advance(hours=1)  # report windows end at ``now`` (exclusive)
    return h


def is_stale_home(resp: object) -> bool:
    msgs = resp.messages  # type: ignore[attr-defined]
    return len(msgs) == 1 and msgs[0].edit is False and msgs[0].text.startswith(nav_texts.STALE)


async def test_owner_and_managers_land_on_the_manager_home_with_reports() -> None:
    h = await seeded()
    for actor in (OWNER, MANAGER):
        resp = await h.start(actor)
        assert text(resp).startswith("🧭 مدیریت ")
        assert REPORTS in button_data(resp)
        assert find_button(resp, "گزارش‌ها").data == REPORTS
        assert button_data(resp)[-1] == "nav:go:cust"
        assert "nav:go:shop" not in button_data(resp)  # customer entries live in the customer view
    for actor in ("ali", STAFF):
        assert REPORTS not in button_data(await h.start(actor))


async def test_report_list_has_overview_capabilities_back_and_home() -> None:
    h = await seeded()
    resp = await h.tap(OWNER, REPORTS)
    data = button_data(resp)
    assert data[0] == "nav:go:mgr.rep.all"
    assert f"nav:go:mgr.rep.{CAP}" in data
    assert find_button(resp, "فروشگاه").data == f"nav:go:mgr.rep.{CAP}"
    assert data[-2:] == ["nav:go:mgr", "nav:go:home"]
    assert text(resp).startswith(nav_texts.REPORTS)
    assert resp.messages[0].edit is True
    assert all(len(d.encode()) <= 64 for d in data)


async def test_overview_and_capability_report_are_persian_text() -> None:
    h = await seeded()
    for data in ("nav:go:mgr.rep.all", "menu:open:_rep.all"):  # nav and the legacy alias
        overview = await h.tap(OWNER, data)
        assert "نمای کلی کسب‌وکار" in text(overview)
        assert "۷ روز گذشته" in text(overview)
        assert "• تعداد سفارش‌ها: ۲" in text(overview)  # Persian digits
        assert [b.data for b in buttons(overview)] == [REPORTS, "nav:go:home"]

    report = await h.tap(OWNER, f"nav:go:mgr.rep.{CAP}")
    assert text(report).startswith("📊 گزارش فروشگاه")
    assert "تومان" in text(report)  # revenue
    assert "درآمد: ۳۵۰" in text(report)


async def test_legacy_panel_button_opens_the_manager_home() -> None:
    h = await seeded()
    resp = await h.tap(OWNER, LEGACY_PANEL)
    assert text(resp).startswith("🧭 مدیریت ") and REPORTS in button_data(resp)


async def test_customers_and_staff_get_the_stale_home() -> None:
    h = await seeded()
    for actor in ("ali", STAFF):
        for data in (LEGACY_PANEL, "menu:open:_rep.all", f"menu:open:_rep.{CAP}", REPORTS, "nav:go:mgr"):
            resp = await h.tap(actor, data)
            assert is_stale_home(resp), (actor, data)
            assert REPORTS not in button_data(resp)


async def test_unknown_or_disabled_report_is_stale_and_the_reports_are_read_only() -> None:
    h = await seeded()
    before = len(h.store.all_records())
    for data in ("menu:open:_rep.nope", "menu:open:_rep.", "menu:open:_other", "nav:go:mgr.rep.nope"):
        assert is_stale_home(await h.tap(OWNER, data)), data
    await h.tap(OWNER, "nav:go:mgr.rep.all")
    assert len(h.store.all_records()) == before


def test_runtime_stays_free_of_database_and_api_imports() -> None:
    """Checked in a fresh interpreter: other tests in this process import the whole app."""
    code = (
        "import sys, app.runtime.runtime\n"
        "bad = [m for m in sys.modules if m.startswith(('app.api', 'app.db', 'app.services'))]\n"
        "sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
