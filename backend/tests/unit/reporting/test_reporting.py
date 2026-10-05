"""Metrics, service, Telegram text and the reports API, over MemoryStore."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.api import reports as reports_api
from app.api.deps import get_owned_bot
from app.botspec.models import BotSpec
from app.botspec.validate import validate_spec
from app.db.session import get_session
from app.main import create_app
from app.reporting import service
from app.reporting.metrics import METRICS, capability_id, metrics_for
from app.reporting.telegram import render_overview_text, render_report_text
from app.runtime.memory_store import MemoryStore
from app.schemas.business import CapabilityReportOut, MetricValue, OverviewOut

NOW = datetime(2026, 10, 6, 8, 30, tzinfo=UTC)  # Tuesday 14 Mehr 1405, 12:00 in Tehran
EXAMPLES = Path(__file__).resolve().parents[4] / "examples"


def d(day: int, hour: int = 6, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


def _field(key: str, type_: str, **kw: Any) -> dict[str, Any]:
    return {"key": key, "label": key, "type": type_, **kw}


def build_spec(*, events_enabled: bool = True) -> BotSpec:
    statuses = [{"key": "new", "label": "جدید"}, {"key": "done", "label": "تحویل‌شده"}]
    spec = BotSpec.model_validate(
        {
            "bot": {"name": "فروشگاه", "welcome_text": "سلام"},
            "resources": [
                {
                    "key": "product",
                    "label": "محصول",
                    "label_plural": "محصولات",
                    "title_field": "title",
                    "fields": [_field("title", "text"), _field("price", "integer")],
                },
                {
                    "key": "workshop",
                    "label": "کارگاه",
                    "label_plural": "کارگاه‌ها",
                    "title_field": "title",
                    "fields": [
                        _field("title", "text"),
                        _field("starts_at", "datetime"),
                        _field("kind", "choice", choices=["tech", "art"]),
                    ],
                },
            ],
            "capabilities": [
                {
                    "type": "orders",
                    "key": "shop",
                    "title": "فروشگاه",
                    "resource": "product",
                    "price_field": "price",
                    "statuses": [*statuses, {"key": "cancelled", "label": "لغو شده"}],
                    "initial_status": "new",
                    "owner_actions": [
                        {"key": "deliver", "label": "تحویل", "from_statuses": ["new"], "to_status": "done"},
                        {"key": "cancel", "label": "لغو", "from_statuses": ["new"], "to_status": "cancelled"},
                    ],
                    "cancellable_statuses": ["new"],
                },
                {
                    "type": "booking",
                    "key": "book",
                    "title": "رزرو",
                    "resource": "workshop",
                    "capacity": {"mode": "fixed", "value": 2},
                    "start_field": "starts_at",
                    "detail_fields": ["title"],
                    "waitlist": {"enabled": True},
                },
                {
                    "type": "booking",
                    "key": "rsvp",
                    "title": "ثبت‌نام رویداد",
                    "resource": "workshop",
                    "capacity": {"mode": "fixed", "value": 5},
                    "start_field": "starts_at",
                    "detail_fields": ["title"],
                    "preset": "events",
                    "category_field": "kind",
                    "enabled": events_enabled,
                },
                {
                    "type": "request",
                    "key": "leave",
                    "title": "مرخصی",
                    "form_fields": [_field("reason", "text")],
                    "statuses": [
                        {"key": "pending", "label": "در انتظار"},
                        {"key": "approved", "label": "تأیید"},
                        {"key": "rejected", "label": "رد"},
                    ],
                    "initial_status": "pending",
                    "owner_actions": [
                        {
                            "key": "ok",
                            "label": "تأیید",
                            "from_statuses": ["pending"],
                            "to_status": "approved",
                        },
                        {"key": "no", "label": "رد", "from_statuses": ["pending"], "to_status": "rejected"},
                    ],
                },
                {
                    "type": "catalog",
                    "key": "list",
                    "title": "فهرست",
                    "resource": "workshop",
                    "detail_fields": ["kind"],
                },
                {
                    "type": "info",
                    "key": "about",
                    "title": "درباره",
                    "pages": [{"key": "p", "title": "t", "body": "b"}],
                },
            ],
            "menu": [{"key": "m", "label": "فروشگاه", "capability": "shop"}],
        }
    )
    assert not [i for i in validate_spec(spec) if i.severity == "error"]
    return spec


async def seed() -> MemoryStore:
    s = MemoryStore()

    async def order(total: Any, status: str, actor: str, when: datetime, lines: list[tuple[str, int, int]]):
        rec = await s.create_record(
            "shop", {"total": total, "payment_status": "unpaid"}, status=status, actor_id=actor, now=when
        )
        for title, qty, price in lines:
            data = {"order_id": rec.id, "item_id": 1, "title": title, "qty": qty, "unit_price": price}
            await s.create_record("shop.lines", data, actor_id=actor, now=when)

    await order(100000, "new", "a", d(6, 6), [("A", 2, 30000), ("B", 1, 40000)])
    await order("۲۰۰٬۰۰۰", "done", "b", d(6, 7), [("A", 1, 30000)])
    await order(50000, "cancelled", "a", d(5, 6), [("C", 5, 10000)])
    await order(300000, "done", "c", d(25, 6, 9), [("A", 1, 30000)])  # 25 Sep: previous 7d window

    w1 = await s.create_record(
        "workshop", {"title": "الف", "starts_at": d(10).isoformat(), "kind": "tech"}, now=d(1)
    )
    w2 = await s.create_record(
        "workshop", {"title": "ب", "starts_at": d(12).isoformat(), "kind": "art"}, now=d(1)
    )
    await s.create_record(
        "workshop", {"title": "گذشته", "starts_at": d(1, 6, 9).isoformat(), "kind": "tech"}, now=d(1)
    )

    for cap, item, status, actor, day in [
        ("book", w1.id, "confirmed", "a", 5),
        ("book", w1.id, "confirmed", "b", 6),
        ("book", w2.id, "waitlisted", "c", 6),
        ("book", w2.id, "cancelled", "d", 6),
        ("rsvp", w1.id, "confirmed", "a", 6),
        ("rsvp", w2.id, "confirmed", "b", 6),
        ("rsvp", w1.id, "confirmed", "c", 5),
        ("rsvp", w2.id, "waitlisted", "d", 6),
        ("rsvp", w1.id, "cancelled", "e", 6),
    ]:
        await s.create_record(cap, {}, status=status, actor_id=actor, item_id=item, now=d(day))

    await s.create_record("leave", {"reason": "x"}, status="pending", actor_id="a", now=d(6, 7))
    q2 = await s.create_record("leave", {"reason": "y"}, status="pending", actor_id="b", now=d(5, 6))
    await s.update_record("leave", q2.id, status="approved", now=d(5, 18))  # 12 hours
    q3 = await s.create_record("leave", {"reason": "z"}, status="pending", actor_id="c", now=d(6, 0))
    await s.update_record("leave", q3.id, status="rejected", now=d(6, 3))  # 3 hours
    return s


def by_id(report: CapabilityReportOut) -> dict[str, MetricValue]:
    return {m.id: m for m in report.metrics}


async def report(store: MemoryStore, key: str, period: Any = "7d", spec: BotSpec | None = None):
    spec = spec or build_spec()
    cap = spec.capability(key)
    assert cap is not None
    return await service.capability_report(store, spec, cap, period, NOW)


def points(m: MetricValue) -> dict[str, float]:
    return {p.label: p.value for p in m.series or []}


async def test_orders_report() -> None:
    r = by_id(await report(await seed(), "shop"))
    assert (r["order_count"].value, r["order_count"].previous) == (2, 1)  # cancelled excluded
    assert (r["revenue"].value, r["revenue"].previous, r["revenue"].unit) == (300000, 300000, "تومان")
    assert r["average_order_value"].value == 150000
    assert r["cancelled_orders"].value == 1 and r["cancelled_orders"].previous == 0
    assert points(r["orders_by_status"]) == {"جدید": 1, "تحویل‌شده": 1, "لغو شده": 1}
    by_day = r["orders_by_day"]
    assert by_day.kind == "series" and by_day.previous is None
    assert len(by_day.series or []) == 7  # empty days filled
    assert by_day.series[0].label == "۸ مهر" and by_day.series[-1] == by_day.series[-1].model_copy(
        update={"label": "۱۴ مهر", "value": 2}
    )
    assert points(by_day)["۱۳ مهر"] == 0  # the cancelled order's day
    assert r["top_products"].rows == [  # the cancelled order's lines are ignored
        {"label": "A", "value": 3, "revenue": 90000},
        {"label": "B", "value": 1, "revenue": 40000},
    ]


async def test_booking_report() -> None:
    r = by_id(await report(await seed(), "book"))
    assert r["booking_count"].value == 3 and r["booking_count"].previous == 0
    assert r["cancellation_count"].value == 1
    assert r["cancellation_rate"].value == 25 and r["cancellation_rate"].unit == "٪"
    assert sum(points(r["bookings_by_day"]).values()) == 3
    assert r["capacity_utilization"].value == 50  # 2 confirmed of 2 upcoming workshops x 2 seats
    assert r["capacity_utilization"].previous is None


async def test_events_report() -> None:
    report_ = await report(await seed(), "rsvp")
    assert report_.capability_id == "events" and report_.capability_key == "rsvp"
    r = by_id(report_)
    assert r["event_count"].value == 2 and r["event_count"].previous is None  # the past one is excluded
    assert r["rsvp_count"].value == 3
    assert points(r["rsvp_breakdown"]) == {"شرکت می‌کنند": 3, "در لیست انتظار": 1, "لغو شده": 1}
    assert points(r["attendance_by_category"]) == {"tech": 2, "art": 1}
    assert sum(points(r["rsvp_by_day"]).values()) == 3
    assert "capacity_utilization" not in r


async def test_requests_report() -> None:
    r = by_id(await report(await seed(), "leave"))
    assert r["request_count"].value == 3
    assert r["open_requests"].value == 1
    assert r["resolved_requests"].value == 2
    assert points(r["requests_by_status"]) == {"در انتظار": 1, "تأیید": 1, "رد": 1}
    assert (
        r["average_resolution_time_hours"].value == 7.5 and r["average_resolution_time_hours"].unit == "ساعت"
    )
    assert sum(points(r["requests_by_day"]).values()) == 3


async def test_catalog_info_and_all_period() -> None:
    store = await seed()
    assert by_id(await report(store, "list"))["item_count"].value == 3
    info = await report(store, "about")
    assert info.capability_id == "info" and info.metrics == []
    everything = await report(store, "shop", "all")
    assert everything.period == "all" and everything.until == NOW
    m = by_id(everything)
    assert m["order_count"].value == 3 and m["order_count"].previous is None
    assert everything.since == d(25, 6, 9)  # no start: the oldest record


async def test_previous_period_for_today_and_empty_store() -> None:
    store = await seed()
    today = by_id(await report(store, "shop", "today"))
    assert today["order_count"].value == 2 and today["order_count"].previous == 0
    empty = by_id(await report(MemoryStore(), "shop"))
    assert empty["order_count"].value == 0 and empty["average_order_value"].value is None
    assert empty["top_products"].rows == [] and len(empty["orders_by_day"].series or []) == 7


async def test_overview_uses_enabled_capabilities_only() -> None:
    store = await seed()
    ov = await service.overview(store, build_spec(), "7d", NOW)
    ids = {k.id: k for k in ov.kpis}
    assert list(ids) == [
        "order_count", "revenue", "booking_count", "event_count", "rsvp_count", "open_requests", "customers",
    ]  # fmt: skip
    assert ids["revenue"].value == 300000 and ids["rsvp_count"].value == 3
    assert ids["customers"].value == 5  # a, b, c, d, e within 7d
    assert ov.enabled_capabilities == ["orders", "booking", "events", "forms", "catalog", "info"]

    off = await service.overview(store, build_spec(events_enabled=False), "7d", NOW)
    assert "rsvp_count" not in {k.id for k in off.kpis}
    assert "events" not in off.enabled_capabilities
    # disabled capabilities still report
    spec = build_spec(events_enabled=False)
    assert by_id(await service.capability_report(store, spec, spec.capability("rsvp"), "7d", NOW))


async def test_overview_activity_and_extra_kpis() -> None:
    store = await seed()
    extra = MetricValue(id="sheet_runs", label="تحلیل‌ها", kind="scalar", value=4)
    ov = await service.overview(store, build_spec(), "7d", NOW, extra_kpis=[extra])
    assert ov.kpis[-1] == extra
    assert len(ov.activity) == 10
    assert [a.at for a in ov.activity] == sorted((a.at for a in ov.activity), reverse=True)
    texts = [a.text for a in ov.activity]
    assert any(t.startswith("سفارش #") and t.endswith("ثبت شد") for t in texts)
    assert any("برای الف رزرو کرد" in t for t in texts) and any("در ب ثبت‌نام کرد" in t for t in texts)
    assert {a.kind for a in ov.activity} <= {"order", "booking", "request"}


async def test_overview_source_hook() -> None:
    async def source(bot_id: uuid.UUID, session: Any) -> list[MetricValue]:
        return [MetricValue(id="hooked", label="x", kind="scalar", value=1)]

    service.register_overview_source(source)
    try:
        got = await service.collect_overview_sources(uuid.uuid4(), None)  # type: ignore[arg-type]
        assert [m.id for m in got] == ["hooked"]
    finally:
        service._overview_sources.remove(source)


def test_every_spec_metric_exists() -> None:
    expected = {
        "orders": {
            "order_count", "revenue", "average_order_value", "orders_by_status", "orders_by_day",
            "top_products", "cancelled_orders",
        },
        "booking": {
            "booking_count", "cancellation_count", "cancellation_rate", "bookings_by_day",
            "capacity_utilization",
        },
        "events": {"event_count", "rsvp_count", "rsvp_breakdown", "attendance_by_category", "rsvp_by_day"},
        "forms": {
            "request_count", "open_requests", "resolved_requests", "requests_by_status",
            "average_resolution_time_hours", "requests_by_day",
        },
        "catalog": {"item_count"},
        "info": set(),
    }  # fmt: skip
    assert {k: {m.id for m in v} for k, v in METRICS.items()} == expected
    spec = build_spec()
    assert [capability_id(c) for c in spec.capabilities] == [
        "orders",
        "booking",
        "events",
        "forms",
        "catalog",
        "info",
    ]
    no_category = spec.model_copy(deep=True)
    events = no_category.capability("rsvp")
    events.category_field = None  # type: ignore[union-attr]
    assert "attendance_by_category" not in {m.id for m in metrics_for(events)}  # type: ignore[arg-type]


async def test_telegram_text_is_persian_and_bounded() -> None:
    store = await seed()
    text = render_report_text(await report(store, "shop"))
    assert "گزارش فروشگاه" in text and "۷ روز گذشته" in text
    assert "درآمد: ۳۰۰٬۰۰۰ تومان" in text and "(بدون تغییر)" in text
    assert "۱. A: ۳" in text
    assert not any(c in text for c in "0123456789")
    assert "۵۰٪" in render_report_text(await report(store, "book"))
    ov = render_overview_text(await service.overview(store, build_spec(), "today", NOW))
    assert "نمای کلی" in ov and "امروز" in ov and "آخرین رویدادها" in ov
    assert not any(c in ov for c in "0123456789")
    assert "هنوز داده‌ای" in render_overview_text(
        OverviewOut(period="7d", kpis=[], activity=[], enabled_capabilities=[])
    )
    huge = CapabilityReportOut(
        capability_key="k", capability_id="orders", label="ب", period="7d", since=NOW, until=NOW,
        metrics=[
            MetricValue(id=f"m{i}", label="شاخص " * 30, kind="table", rows=[{"label": "x" * 200, "value": 1}] * 5)  # noqa: E501
            for i in range(20)
        ],
    )  # fmt: skip
    capped = render_report_text(huge)
    assert len(capped) <= 3500 and capped.endswith("…")


def test_workshop_example_loads_with_every_capability_reporting() -> None:
    spec = BotSpec.model_validate(
        json.loads((EXAMPLES / "workshop.botspec.json").read_text(encoding="utf-8"))
    )
    assert [capability_id(c) for c in spec.capabilities] == ["info", "booking"]


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[httpx.AsyncClient, uuid.UUID]]:
    """The reports router over a MemoryStore, with the owner dependency and the session stubbed."""
    store = await seed()
    spec = build_spec()
    bot = SimpleNamespace(id=uuid.uuid4(), owner_actor_id=None, active_revision_id=1)
    revision = SimpleNamespace(bot_id=bot.id, spec=spec.model_dump(mode="json"))

    class FakeSession:
        async def get(self, model: Any, ident: Any) -> Any:
            return revision

    app = create_app()
    app.dependency_overrides[get_owned_bot] = lambda: bot
    app.dependency_overrides[get_session] = lambda: FakeSession()
    monkeypatch.setattr(reports_api, "PgStore", lambda *a, **k: store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, bot.id


async def test_reports_api(api: tuple[httpx.AsyncClient, uuid.UUID]) -> None:
    client, bot_id = api
    r = await client.get(f"/bots/{bot_id}/reports/overview", params={"period": "all", "env": "live"})
    assert r.status_code == 200, r.text
    ov = OverviewOut.model_validate(r.json())
    assert ov.period == "all" and ov.kpis and ov.activity
    r = await client.get(f"/bots/{bot_id}/reports/shop", params={"period": "30d"})
    assert r.status_code == 200, r.text
    rep = CapabilityReportOut.model_validate(r.json())
    assert rep.capability_id == "orders" and rep.label == "فروشگاه" and rep.period == "30d"
    missing = await client.get(f"/bots/{bot_id}/reports/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "capability_not_found"
    assert (await client.get(f"/bots/{bot_id}/reports/overview", params={"period": "bad"})).status_code == 422


async def test_reports_api_without_active_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = SimpleNamespace(id=uuid.uuid4(), owner_actor_id=None, active_revision_id=None)
    app = create_app()
    app.dependency_overrides[get_owned_bot] = lambda: bot
    app.dependency_overrides[get_session] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/bots/{bot.id}/reports/overview")
        assert r.status_code == 200
        assert r.json() == {"period": "7d", "kpis": [], "activity": [], "enabled_capabilities": []}
        assert (await c.get(f"/bots/{bot.id}/reports/shop")).status_code == 404
