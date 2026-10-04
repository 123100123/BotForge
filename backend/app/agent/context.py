"""Limits, agent settings, and the per-run context passed to every phase."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.agent.events import Event
from app.agent.llm import LLMClient, Usage
from app.agent.state import Phase, RunState, RunStatus

if TYPE_CHECKING:
    from app.agent.repository import AgentRepository


class AgentSettings(BaseSettings):
    """Agent limits from the environment (defaults are the roadmap's initial values)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    AGENT_MAX_TOOL_CALLS: int = 15
    AGENT_MAX_REPAIR_ROUNDS: int = 2
    AGENT_MAX_QUESTIONS: int = 3
    AGENT_MAX_CLARIFY_ROUNDS: int = 2
    # Per-run budgets. Thinking tokens count as output, so the output budget is generous.
    AGENT_INPUT_TOKEN_BUDGET: int = 600_000
    AGENT_OUTPUT_TOKEN_BUDGET: int = 150_000
    AGENT_DAILY_RUN_CAP: int = 30
    AGENT_RUNS_PER_MINUTE: int = 5


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 15
    max_repair_rounds: int = 2
    max_questions: int = 3
    max_clarify_rounds: int = 2
    input_budget: int = 600_000  # uncached input + cache writes (Usage.billable_input)
    output_budget: int = 150_000  # thinking tokens included
    min_acceptance: int = 2
    max_acceptance: int = 6
    max_change_acceptance: int = 4  # modify: new acceptance scenarios for the changed requirements

    @classmethod
    def from_settings(cls, s: AgentSettings | None = None) -> Limits:
        s = s or get_agent_settings()
        return cls(
            max_tool_calls=s.AGENT_MAX_TOOL_CALLS,
            max_repair_rounds=s.AGENT_MAX_REPAIR_ROUNDS,
            max_questions=s.AGENT_MAX_QUESTIONS,
            max_clarify_rounds=s.AGENT_MAX_CLARIFY_ROUNDS,
            input_budget=s.AGENT_INPUT_TOKEN_BUDGET,
            output_budget=s.AGENT_OUTPUT_TOKEN_BUDGET,
        )


@dataclass(frozen=True)
class Next:
    """A phase's outcome: the next phase, and the run status to persist with it."""

    phase: Phase
    status: RunStatus = "running"


Emit = Callable[[Event], Awaitable[None]]


@dataclass
class RunContext:
    run_id: str
    bot_id: str
    state: RunState
    llm: LLMClient
    limits: Limits
    emit: Emit
    repo: AgentRepository
    active_revision_id: str | None = None

    def charge(self, usage: Usage) -> None:
        self.state.usage = self.state.usage + usage

    def over_budget(self) -> bool:
        u = self.state.usage
        return u.billable_input > self.limits.input_budget or u.output_tokens > self.limits.output_budget

    def usage_hook(self, usage: Usage) -> bool:
        """Charge one model response; False (stop the loop) once the run budget is spent."""
        self.charge(usage)
        return not self.over_budget()
