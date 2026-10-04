"""Agent event types, payload builders, and an in-process publish/subscribe bus.

Envelope: ``{id, run_id, ts, type, payload}``. Payload shapes are a contract with the frontend
timeline (roadmap: "Agent Architecture" -> Events). Builders return ``(type, payload)``; the
orchestrator persists the pair through the repository (which assigns ``id`` and ``ts``) and then
publishes the envelope on ``EventBus`` so an SSE stream can tail it live.
"""

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.agent.llm import Usage
from app.agent.requirements import Question, Requirements
from app.botspec.outline import SpecOutline
from app.testing.scenario import Scenario, TestReport

OWNER_MESSAGE = "owner_message"
AGENT_MESSAGE = "agent_message"
PHASE_STARTED = "phase_started"
PHASE_FINISHED = "phase_finished"
REQUIREMENTS = "requirements"
QUESTIONS = "questions"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
SPEC_UPDATED = "spec_updated"
TESTS_GENERATED = "tests_generated"
TEST_REPORT = "test_report"
DIFF = "diff"
APPROVAL_REQUESTED = "approval_requested"
DEPLOYED = "deployed"
USAGE = "usage"
ERROR = "error"

EVENT_TYPES = frozenset(
    {
        OWNER_MESSAGE,
        AGENT_MESSAGE,
        PHASE_STARTED,
        PHASE_FINISHED,
        REQUIREMENTS,
        QUESTIONS,
        TOOL_CALL,
        TOOL_RESULT,
        SPEC_UPDATED,
        TESTS_GENERATED,
        TEST_REPORT,
        DIFF,
        APPROVAL_REQUESTED,
        DEPLOYED,
        USAGE,
        ERROR,
    }
)

Event = tuple[str, dict[str, Any]]


class EventEnvelope(BaseModel):
    id: int
    run_id: str
    ts: datetime
    type: str
    payload: dict[str, Any]


# --------------------------------------------------------------------------- payload builders


def owner_message(text: str) -> Event:
    return OWNER_MESSAGE, {"text": text}


def agent_message(text: str) -> Event:
    return AGENT_MESSAGE, {"text": text}


def phase_started(phase: str) -> Event:
    return PHASE_STARTED, {"phase": phase}


def phase_finished(phase: str, ok: bool, summary: str | None = None) -> Event:
    payload: dict[str, Any] = {"phase": phase, "ok": ok}
    if summary is not None:
        payload["summary"] = summary
    return PHASE_FINISHED, payload


def requirements(req: Requirements) -> Event:
    return REQUIREMENTS, {"requirements": req.model_dump(mode="json")}


def questions(items: Iterable[Question]) -> Event:
    return QUESTIONS, {"questions": [q.model_dump(mode="json") for q in items]}


def tool_call(loop: str, name: str, summary: str) -> Event:
    return TOOL_CALL, {"loop": loop, "name": name, "summary": summary}


def tool_result(name: str, ok: bool, summary: str) -> Event:
    return TOOL_RESULT, {"name": name, "ok": ok, "summary": summary}


def spec_updated(outline: SpecOutline) -> Event:
    return SPEC_UPDATED, {"outline": outline.model_dump(mode="json")}


def tests_generated(derived: int, acceptance: int, notes: list[str] | None = None) -> Event:
    payload: dict[str, Any] = {"derived": derived, "acceptance": acceptance}
    if notes:
        payload["notes"] = notes
    return TESTS_GENERATED, payload


def test_report(report: TestReport, scenarios: Iterable[Scenario]) -> Event:
    titles = {s.id: s.title for s in scenarios}
    failures = []
    for r in report.results:
        if r.passed:
            continue
        failed = next((s for s in r.steps if not s.passed), None)
        failures.append(
            {
                "id": r.scenario_id,
                "title": titles.get(r.scenario_id, r.scenario_id),
                "message": (failed.message if failed and failed.message else "ناموفق"),
            }
        )
    return TEST_REPORT, {
        "total": report.total,
        "passed": report.passed,
        "failed": report.failed,
        "failures": failures,
    }


test_report.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


def diff(
    changes: list[dict[str, str]],
    affected_capabilities: list[str],
    tests: dict[str, Any],
    risk: str,
    warnings: list[str],
    requirements: dict[str, list[dict[str, str]]] | None = None,
) -> Event:
    """``{changes: [{label_fa, kind}], affected_capabilities, tests: {carried, new, superseded:
    [{title, reason}]}, risk, warnings, requirements: {added: [{id, statement}], changed: [{id,
    before, after}], removed: [{id, statement}]}}`` (MODIFY review card; cumulative delta)."""
    return DIFF, {
        "changes": changes,
        "affected_capabilities": affected_capabilities,
        "tests": tests,
        "risk": risk,
        "warnings": warnings,
        "requirements": requirements or {"added": [], "changed": [], "removed": []},
    }


def approval_requested(
    revision_id: str | None, can_approve: bool, blocked_reason: str | None = None
) -> Event:
    payload: dict[str, Any] = {"revision_id": revision_id, "can_approve": can_approve}
    if blocked_reason is not None:
        payload["blocked_reason"] = blocked_reason
    return APPROVAL_REQUESTED, payload


def deployed(revision_id: str, number: int) -> Event:
    return DEPLOYED, {"revision_id": revision_id, "number": number}


def usage(u: Usage) -> Event:
    return USAGE, {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cached_tokens": u.cached_tokens,
        "tool_calls": u.tool_calls,
    }


def error(message: str) -> Event:
    return ERROR, {"message": message}


# --------------------------------------------------------------------------- live bus


class EventBus:
    """Per-run fan-out of freshly persisted envelopes to live subscribers (one process)."""

    def __init__(self, max_queue: int = 1000) -> None:
        self._subs: dict[str, set[asyncio.Queue[EventEnvelope]]] = defaultdict(set)
        self._max_queue = max_queue

    def publish(self, envelope: EventEnvelope) -> None:
        for queue in list(self._subs.get(envelope.run_id, ())):
            with contextlib.suppress(asyncio.QueueFull):  # a stalled reader replays from the table
                queue.put_nowait(envelope)

    @contextlib.asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[EventEnvelope]]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(self._max_queue)
        self._subs[run_id].add(queue)
        try:
            yield queue
        finally:
            subs = self._subs.get(run_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subs.pop(run_id, None)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subs.get(run_id, ()))


default_bus = EventBus()
