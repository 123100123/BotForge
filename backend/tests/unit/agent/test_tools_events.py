"""Tools in isolation, deterministic checks, and the live event bus."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.agent import events as ev
from app.agent.checks import check_sample_record
from app.agent.events import EventBus, EventEnvelope
from app.agent.state import RunState
from app.agent.tools import BUILD_TOOLS, REPAIR_TOOLS, TOOL_DEFS, AgentTools
from app.botspec.models import BotSpec
from tests.unit.agent.helpers import golden_spec


def tools(state: RunState, names: tuple[str, ...] = BUILD_TOOLS) -> tuple[AgentTools, list[Any]]:
    emitted: list[Any] = []

    async def emit(event: Any) -> None:
        emitted.append(event)

    return AgentTools(state, loop="build", emit=emit, names=names), emitted


async def test_tools_without_a_draft_return_errors_not_exceptions() -> None:
    t, emitted = tools(RunState())
    for name, args in [
        ("apply_spec_patch", {"ops": []}),
        ("validate_spec", {}),
        ("get_spec", {"path": []}),
        ("finish", {"summary": "x"}),
    ]:
        outcome = await t.handle(name, args)
        assert outcome.content["ok"] is False and not outcome.stop
    assert [e[0] for e in emitted] == ["tool_call", "tool_result"] * 4
    refused = await t.handle("run_tests", {})  # not a build tool
    assert refused.is_error


async def test_get_spec_paths_and_patch_errors() -> None:
    state = RunState(draft_spec=BotSpec.model_validate(golden_spec()))
    t, _ = tools(state)
    sub = await t.handle("get_spec", {"path": ["capabilities", "book_workshop", "capacity"]})
    assert sub.content["value"] == {"mode": "fixed", "value": 10, "field": None}
    missing = await t.handle("get_spec", {"path": ["capabilities", "nope"]})
    assert missing.content["ok"] is False and "nope" in missing.content["error"]
    bad = await t.handle("apply_spec_patch", {"ops": [{"op": "set", "path": ["menu"], "value": []}]})
    assert bad.content["ok"] is False and bad.content["error"]["code"] == "invalid_target"
    malformed = await t.handle("apply_spec_patch", {"ops": [{"op": "move", "path": []}]})
    assert malformed.content["ok"] is False and malformed.is_error
    assert state.draft_spec.capability("book_workshop").capacity.value == 10  # unchanged


def test_tool_schemas_are_json_objects_and_strict_only_where_compatible() -> None:
    for name in {*BUILD_TOOLS, *REPAIR_TOOLS}:
        d = TOOL_DEFS[name].to_api()
        assert d["input_schema"]["type"] == "object" and d["input_schema"]["additionalProperties"] is False
        if d.get("strict"):
            assert name in {"validate_spec", "get_spec", "run_tests", "get_failure", "finish"}
    assert "$defs" in TOOL_DEFS["set_spec"].input_schema


def test_sample_records_must_validate_and_use_relative_datetimes() -> None:
    spec = BotSpec.model_validate(golden_spec())
    now = datetime(2026, 10, 4, tzinfo=UTC)
    base = [
        {"key": "title", "value": "الف"},
        {"key": "description", "value": "ب"},
        {"key": "teacher", "value": "ج"},
    ]
    ok, problem = check_sample_record(
        {"ref": "s", "collection": "workshop", "values": [*base, {"key": "starts_at", "value": "+2d"}]},
        spec,
        now,
    )
    assert ok is not None and problem is None
    absolute, problem = check_sample_record(
        {
            "ref": "s",
            "collection": "workshop",
            "values": [*base, {"key": "starts_at", "value": "2026-11-01T10:00:00+00:00"}],
        },
        spec,
        now,
    )
    assert absolute is None and "relative" in problem
    missing, problem = check_sample_record({"ref": "s", "collection": "workshop", "values": base}, spec, now)
    assert missing is None and problem
    unknown, _ = check_sample_record({"ref": "s", "collection": "book_workshop", "values": []}, spec, now)
    assert unknown is None


async def test_event_bus_fans_out_per_run() -> None:
    bus = EventBus()
    env = EventEnvelope(id=1, run_id="r1", ts=datetime.now(UTC), type="agent_message", payload={"text": "x"})
    async with bus.subscribe("r1") as q1, bus.subscribe("r2") as q2:
        assert bus.subscriber_count("r1") == 1
        bus.publish(env)
        assert await asyncio.wait_for(q1.get(), 1) == env
        assert q2.empty()
    assert bus.subscriber_count("r1") == 0
    bus.publish(env)  # no subscribers: a no-op


def test_payload_builders_match_the_contract() -> None:
    assert ev.phase_finished("build", True) == ("phase_finished", {"phase": "build", "ok": True})
    assert ev.phase_finished("build", False, "x")[1] == {"phase": "build", "ok": False, "summary": "x"}
    assert ev.approval_requested("rev", False, "چرا")[1] == {
        "revision_id": "rev",
        "can_approve": False,
        "blocked_reason": "چرا",
    }
    assert ev.tests_generated(3, 2)[1] == {"derived": 3, "acceptance": 2}
    assert ev.error("خطا") == ("error", {"message": "خطا"})
    assert set(ev.EVENT_TYPES) >= {"diff", "usage", "deployed"}
