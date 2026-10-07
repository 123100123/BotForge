"""An executing run refreshes its heartbeat, and stops once the run pauses or ends."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.agent import orchestrator as orch_module
from app.agent.context import Next, RunContext
from app.agent.orchestrator import Orchestrator
from app.agent.repository import InMemoryAgentRepository
from app.agent.state import RunState

LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


async def test_a_long_phase_keeps_the_heartbeat_fresh_and_it_stops_afterwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryAgentRepository()
    bot_id = repo.add_bot()
    record = await repo.create_run(bot_id, kind="create", state=RunState(kind="create", phase="understand"))
    seen: list[datetime] = []

    async def slow_understand(ctx: RunContext) -> Next:
        repo.runs[record.id].updated_at = LONG_AGO  # as if the run had been quiet for years
        await asyncio.sleep(0.2)  # a long LLM call: no phase boundary, no save_run
        seen.append(repo.runs[record.id].updated_at)
        return Next("clarify", "waiting_user")

    monkeypatch.setitem(orch_module.CREATE_PHASES, "understand", slow_understand)
    orchestrator = Orchestrator(repo, llm=None, heartbeat_seconds=0.02)  # type: ignore[arg-type]
    await orchestrator.advance(record.id)

    assert seen and seen[0] > datetime.now(UTC) - timedelta(seconds=5), "the heartbeat ran mid-phase"
    assert repo.runs[record.id].status == "waiting_user"
    repo.runs[record.id].updated_at = LONG_AGO
    await asyncio.sleep(0.1)
    assert repo.runs[record.id].updated_at == LONG_AGO, "no heartbeat after advance returned"
    assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("agent-heartbeat-")]
