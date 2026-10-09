"""Actual feature callers with both compatible providers mocked and in-memory persistence."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.copilot import service as copilot
from app.db.models import Bot, BotModuleRow
from app.schemas.business import ChatTurn
from app.spreadsheets import narrative, profile
from app.spreadsheets.storage import LocalFileStorage
from tests.unit.agent.helpers import (
    capacity_scripts,
    golden_acceptance,
    golden_spec,
    harness,
    modify_harness,
    sample_out,
    understand_out,
)
from tests.unit.agent.test_llm_liara import FAST, SENTINEL, STRONG, call, completion
from tests.unit.agent.test_llm_liara import model as liara_model
from tests.unit.agent.test_llm_top_tools import TOP_FAST, TOP_STRONG, top_model
from tests.unit.reporting.test_reporting import NOW, build_spec, seed
from tests.unit.spreadsheets.test_profile_run import StubSession, good_draft, sales_workbook, upload


def structured_response(value):
    return completion(json.dumps(value, ensure_ascii=False))


def tool_response(name, args, identifier):
    return completion(
        None,
        calls=[call(name, json.dumps(args, ensure_ascii=False), call_id=identifier)],
        finish="tool_calls",
    )


@pytest.fixture(params=["liara", "top_tools"])
def provider(request):
    if request.param == "liara":
        return SimpleNamespace(make=liara_model, strong=STRONG, fast=FAST)
    return SimpleNamespace(make=top_model, strong=TOP_STRONG, fast=TOP_FAST)


async def test_create_bot_reaches_approval_and_keeps_usage(provider):
    llm, wire = provider.make(
        [
            structured_response(understand_out()),
            tool_response("set_spec", {"spec": golden_spec()}, "c1"),
            tool_response("finish", {"summary": "done"}, "c2"),
            structured_response({"scenarios": golden_acceptance()}),
            structured_response(sample_out()),
        ]
    )
    h = harness()
    h.orch.llm = llm
    run = await h.start()
    assert run.status == "waiting_approval", run.state.error
    assert run.state.test_report is not None and run.state.test_report.failed == 0
    assert run.state.usage.llm_calls == 5 and run.state.usage.tool_calls == 2
    assert run.state.usage.input_tokens == 500
    assert [body["model"] for body in wire.bodies] == [provider.strong] * 4 + [provider.fast]
    assert not wire.responses
    assert (await h.orch.approve(run.id)).status == "done"


async def test_modify_bot_preserves_existing_validation_and_approval(provider):
    scripts = capacity_scripts(12)
    responses = [
        structured_response(scripts["structured"]["triage"][0]),
        structured_response(scripts["structured"]["understand"][0]),
    ]
    for i, calls in enumerate(scripts["loops"]["build"][0]):
        for use in calls:
            responses.append(tool_response(use.name, use.input, f"b{i}"))
    responses.append(structured_response(scripts["structured"]["testgen"][0]))
    for i, calls in enumerate(scripts["loops"]["repair"][0]):
        for use in calls:
            responses.append(tool_response(use.name, use.input, f"r{i}"))
    llm, wire = provider.make(responses)
    h = modify_harness()
    h.orch.llm = llm
    run = await h.start_change()
    assert run.status == "waiting_approval", run.state.error
    assert run.state.test_report is not None and run.state.test_report.failed == 0
    assert run.state.draft_spec.capability("book_workshop").capacity.value == 12
    assert [s.scenario.id for s in run.state.superseded] == ["golden_capacity_10_real"]
    assert wire.bodies[0]["model"] == provider.fast and wire.bodies[1]["model"] == provider.strong
    assert not wire.responses
    assert (await h.orch.approve(run.id)).status == "done"


@pytest.mark.parametrize("during_build", [False, True])
async def test_provider_failure_never_persists_upstream_secrets(during_build, caplog, provider):
    responses = [structured_response(understand_out())] if during_build else []
    responses.append(httpx.Response(402, json={"error": {"message": SENTINEL}}))
    llm, _ = provider.make(responses, LOG_LLM_BODIES=True)
    h = harness()
    h.orch.llm = llm
    run = await h.start()
    assert run.status == "failed" and run.state.error
    blob = run.state.model_dump_json() + json.dumps([(e.type, e.payload) for e in h.events(run.id)])
    assert SENTINEL not in blob + caplog.text
    assert "AI provider request failed" in run.state.error


async def test_invalid_structured_output_never_persists_validation_inputs(caplog, provider):
    llm, _ = provider.make([structured_response({"message": SENTINEL, "requirements": {"secret": SENTINEL}})])
    h = harness()
    h.orch.llm = llm
    run = await h.start()
    assert run.status == "failed" and run.state.usage.input_tokens == 100
    assert SENTINEL not in run.state.model_dump_json() + caplog.text


async def test_spreadsheet_profile_and_narrative_use_model_tiers(tmp_path, provider):
    session = StubSession()
    bot = Bot(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="Business")
    storage = LocalFileStorage(str(tmp_path / "uploads"))
    uploaded = await upload(session, bot, storage, sales_workbook())
    llm, wire = provider.make(
        [
            structured_response(good_draft().model_dump(mode="json")),
            structured_response({"summary": "گزارش آماده شد."}),
        ]
    )
    out = await profile.create_profile(session, bot, llm, uploaded, name=None, daily_report=False)
    assert out.sheet == "Sales" and len(out.metrics) == 5
    summary = await narrative.narrate(llm, out.name, [], [])
    assert summary == "گزارش آماده شد."
    assert [body["model"] for body in wire.bodies] == [provider.strong, provider.fast]
    payload = json.loads(wire.bodies[0]["messages"][1]["content"])
    assert len(payload["sheets"][0]["sample_rows"]) == 10


async def test_spreadsheet_failure_logs_are_redacted(caplog, provider):
    llm, _ = provider.make([httpx.ReadTimeout(SENTINEL)])
    assert await narrative.narrate(llm, "report", [], []) is None
    assert SENTINEL not in caplog.text


async def test_copilot_service_and_business_tools_work_with_provider(monkeypatch, provider):
    bot = Bot(id=uuid.uuid4(), name="Business", owner_actor_id=None)
    spec = build_spec()
    rows = {"copilot": BotModuleRow(bot_id=bot.id, module="copilot", enabled=True, config={})}
    monkeypatch.setattr(copilot.capabilities, "load_module_rows", AsyncMock(return_value=rows))
    monkeypatch.setattr(copilot.capabilities, "load_spec", AsyncMock(return_value=spec))
    claim = AsyncMock()
    monkeypatch.setattr(copilot, "_claim_question", claim)
    store = await seed()
    monkeypatch.setattr(copilot, "PgStore", lambda *args: store)
    monkeypatch.setattr("app.reporting.service.collect_overview_sources", AsyncMock(return_value=[]))
    llm, wire = provider.make(
        [
            tool_response("get_business_summary", {"period": "7d"}, "c1"),
            tool_response("finish", {"reply": "گزارش کسب‌وکار آماده شد."}, "c2"),
        ]
    )
    out = await copilot.ask(None, bot, llm, [ChatTurn(role="user", content="گزارش این هفته؟")], now=NOW)
    assert out.reply == "گزارش کسب‌وکار آماده شد." and out.tool_calls[0].name == "get_business_summary"
    assert out.usage["input_tokens"] == 200 and out.usage["tool_calls"] == 2
    assert claim.await_count == 1
    assert [body["model"] for body in wire.bodies] == [provider.fast, provider.fast]
    tool_result = json.loads(wire.bodies[1]["messages"][-1]["content"])
    assert tool_result["ok"] is True and tool_result["kpis"]
