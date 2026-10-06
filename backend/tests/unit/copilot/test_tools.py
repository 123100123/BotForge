"""Copilot tools over a MemoryStore-backed seeded spec (orders + events + a request capability).

The tools that read analysis runs and the team need a database; they are covered in
``tests/integration/test_copilot_api.py``.
"""

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.llm import ToolOutcome
from app.copilot import tools as copilot_tools
from app.copilot.tools import MAX_DATA_CALLS, MAX_RESULT_BYTES, CopilotTools, fit
from app.reporting import service as reporting
from app.runtime.memory_store import MemoryStore
from tests.unit.reporting.test_reporting import NOW, build_spec, d, seed


@pytest.fixture(autouse=True)
def no_overview_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(bot_id: uuid.UUID, session: Any) -> list[Any]:
        return []

    monkeypatch.setattr(reporting, "collect_overview_sources", none)


async def make_tools(store: MemoryStore | None = None) -> CopilotTools:
    bot = SimpleNamespace(id=uuid.uuid4(), owner_actor_id=None)
    return CopilotTools(None, bot, build_spec(), store or await seed(), NOW)  # type: ignore[arg-type]


def size(outcome: ToolOutcome) -> int:
    return len(json.dumps(outcome.content, ensure_ascii=False, separators=(",", ":")).encode())


async def call(tools: CopilotTools, name: str, **args: Any) -> dict[str, Any]:
    outcome = await tools.handle(name, args)
    assert size(outcome) <= MAX_RESULT_BYTES
    return outcome.content


async def test_definitions_are_strict_and_bounded_to_the_specs_keys() -> None:
    tools = await make_tools()
    defs = {t.name: t for t in tools.definitions()}
    assert set(defs) == {
        "get_business_summary",
        "get_capability_report",
        "compare_periods",
        "list_pending_approvals",
        "get_spreadsheet_report",
        "who_submitted",
        "finish",
    }
    for t in defs.values():
        assert t.input_schema["additionalProperties"] is False
        if t.strict:
            assert set(t.input_schema["required"]) == set(t.input_schema["properties"])
    keys = defs["get_capability_report"].input_schema["properties"]["capability_key"]["enum"]
    assert keys == ["shop", "book", "rsvp", "leave", "list"]  # reportable capabilities; not info
    assert "week" not in defs["get_business_summary"].input_schema["properties"]["period"]["enum"]


async def test_business_summary() -> None:
    tools = await make_tools()
    out = await call(tools, "get_business_summary", period="7d")
    assert out["ok"] is True and out["period"] == "7d"
    kpis = {k["id"]: k for k in out["kpis"]}
    assert (kpis["order_count"]["value"], kpis["order_count"]["previous"]) == (2, 1)
    assert {c["key"] for c in out["capabilities"]} >= {"shop", "leave"}
    assert "orders" in out["enabled_capabilities"]
    assert all("rows" not in k and "points" not in k for k in out["kpis"])  # scalars only


async def test_capability_report_shape_and_truncation() -> None:
    store = await seed()
    tools = await make_tools(store)
    out = await call(tools, "get_capability_report", capability_key="shop", period="7d")
    assert out["ok"] is True and out["capability_key"] == "shop"
    metrics = {m["id"]: m for m in out["metrics"]}
    assert metrics["revenue"]["value"] == 300000 and metrics["revenue"]["previous"] == 300000
    assert metrics["revenue"]["unit"] == "تومان"
    series = metrics["orders_by_day"]
    assert series["kind"] == "series" and series["points_total"] == 7 and len(series["points"]) == 7
    # a 30-day report has 30 daily points: the tool keeps the latest ten
    out30 = await call(tools, "get_capability_report", capability_key="shop", period="30d")
    by_day = {m["id"]: m for m in out30["metrics"]}["orders_by_day"]
    assert by_day["points_total"] == 30 and len(by_day["points"]) == 10
    top = {m["id"]: m for m in out["metrics"]}["top_products"]
    assert top["kind"] == "table" and len(top["rows"]) <= 10 and top["rows_total"] >= 1


async def test_capability_report_is_clipped_to_the_size_bound() -> None:
    payload: dict[str, Any] = {
        "ok": True,
        "metrics": [{"rows": [{"label": "x" * 80, "value": i} for i in range(60)]}],
    }
    fitted = fit(payload)
    assert fitted["truncated"] is True
    assert len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_RESULT_BYTES
    assert 0 < len(fitted["metrics"][0]["rows"]) < 60


async def test_compare_periods() -> None:
    tools = await make_tools()
    out = await call(tools, "compare_periods", capability_key="shop", metric_id="order_count", period="7d")
    assert out["ok"] is True
    assert (out["current"], out["previous"], out["change_pct"]) == (2, 1, 100.0)
    flat = await call(tools, "compare_periods", capability_key="shop", metric_id="revenue", period="7d")
    assert flat["change_pct"] == 0.0
    nothing = await call(
        tools, "compare_periods", capability_key="shop", metric_id="order_count", period="all"
    )
    assert nothing["previous"] is None and nothing["change_pct"] is None  # no previous window for "all"


async def test_list_pending_approvals_only_open_requests_with_a_title() -> None:
    tools = await make_tools()
    out = await call(tools, "list_pending_approvals")
    assert out["ok"] is True and out["total_pending"] == 1  # approved and rejected are terminal
    (item,) = out["items"]
    assert item["capability_key"] == "leave" and item["title"] == "x"
    assert item["status"] == "در انتظار" and item["created_at"].startswith("2026-10-06")
    capped = await call(tools, "list_pending_approvals", limit=1)
    assert len(capped["items"]) == 1
    assert (await call(tools, "list_pending_approvals", limit=0))["error"] == "invalid_limit"
    assert (await call(tools, "list_pending_approvals", limit="3"))["error"] == "invalid_limit"


async def test_pending_approvals_limit_is_clamped() -> None:
    store = await seed()
    for i in range(15):
        await store.create_record("leave", {"reason": f"r{i}"}, status="pending", actor_id="z", now=d(6, 8))
    tools = await make_tools(store)
    out = await call(tools, "list_pending_approvals", limit=500)
    assert out["total_pending"] == 16 and len(out["items"]) == 10


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("get_business_summary", {"period": "week"}),
        ("get_business_summary", {}),
        ("get_capability_report", {"capability_key": "shop", "period": "yesterday-ish"}),
        ("compare_periods", {"capability_key": "shop", "metric_id": "order_count", "period": 7}),
    ],
)
async def test_invalid_period_is_a_structured_error(name: str, args: dict[str, Any]) -> None:
    tools = await make_tools()
    outcome = await tools.handle(name, args)
    assert outcome.is_error is True
    assert outcome.content["ok"] is False and outcome.content["error"] == "invalid_period"
    assert "7d" in outcome.content["valid"]


@pytest.mark.parametrize("name", ["get_capability_report", "compare_periods"])
@pytest.mark.parametrize("key", ["nope", "about", None, 5])
async def test_invalid_capability_key_is_a_structured_error(name: str, key: Any) -> None:
    tools = await make_tools()
    args = {"capability_key": key, "period": "7d", "metric_id": "order_count"}
    outcome = await tools.handle(name, args)
    assert outcome.is_error is True
    assert outcome.content["error"] == "invalid_capability_key"
    assert outcome.content["valid"] == ["shop", "book", "rsvp", "leave", "list"]


async def test_invalid_metric_and_disabled_capability() -> None:
    tools = await make_tools()
    bad = await tools.handle(
        "compare_periods", {"capability_key": "shop", "metric_id": "nope", "period": "7d"}
    )
    assert bad.content["error"] == "invalid_metric_id" and "revenue" in bad.content["valid"]
    off = CopilotTools(
        None,
        SimpleNamespace(id=uuid.uuid4(), owner_actor_id=None),
        build_spec(events_enabled=False),
        await seed(),
        NOW,
    )  # type: ignore[arg-type]
    out = await off.handle("get_capability_report", {"capability_key": "rsvp", "period": "7d"})
    assert out.content["error"] == "capability_disabled"
    assert "rsvp" not in out.content.get("valid", [])


async def test_no_active_revision() -> None:
    bot = SimpleNamespace(id=uuid.uuid4(), owner_actor_id=None)
    tools = CopilotTools(None, bot, None, MemoryStore(), NOW)  # type: ignore[arg-type]
    for name, args in [
        ("get_business_summary", {"period": "7d"}),
        ("get_capability_report", {"capability_key": "shop", "period": "7d"}),
        ("list_pending_approvals", {}),
    ]:
        out = await tools.handle(name, args)
        assert out.is_error and out.content["error"] == "no_active_revision"
    assert tools.definitions()[1].input_schema["properties"]["capability_key"] == {
        "type": "string",
        "description": "کلید قابلیت (capability_key) از فهرست قابلیت‌های فعال",
    }


async def test_calls_are_logged_with_persian_summaries() -> None:
    tools = await make_tools()
    await tools.handle("get_capability_report", {"capability_key": "shop", "period": "7d"})
    await tools.handle("get_business_summary", {"period": "nonsense"})  # logged even when rejected
    await tools.handle("who_submitted", {"profile_name": "فروش", "date": "today"})
    assert (tools.calls[0].name, tools.calls[0].arguments) == (
        "get_capability_report",
        {"capability_key": "shop", "period": "7d"},
    )
    assert tools.calls[0].summary == "گزارش فروشگاه برای ۷ روز گذشته"
    assert tools.calls[1].summary == "خلاصهٔ کسب‌وکار برای"
    assert tools.calls[2].summary == "بررسی ارسال گزارش «فروش» برای امروز"


async def test_unknown_tool_and_call_limit_and_finish() -> None:
    tools = await make_tools()
    unknown = await tools.handle("drop_tables", {})
    assert unknown.is_error and unknown.content["error"] == "unknown_tool" and tools.calls == []
    for _ in range(MAX_DATA_CALLS):
        assert (await tools.handle("get_business_summary", {"period": "7d"})).is_error is False
    over = await tools.handle("get_business_summary", {"period": "7d"})
    assert over.is_error and over.content["error"] == "tool_limit"
    done = await tools.handle("finish", {"reply": "  سلام  "})
    assert done.stop is True and tools.answer == "سلام"


async def test_handler_bug_becomes_a_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = await make_tools()

    async def boom(*_: Any) -> Any:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(copilot_tools.reporting, "capability_report", boom)
    out = await tools.handle("get_capability_report", {"capability_key": "shop", "period": "7d"})
    assert out.is_error and out.content["error"] == "internal_error"
    assert "secret" not in json.dumps(out.content)
