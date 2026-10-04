"""Persisted run state (roadmap: "Agent Architecture" -> Run state). Stored in ``agent_runs.state``."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.llm import Usage
from app.agent.requirements import Question, Requirements, RequirementsDelta
from app.botspec.models import BotSpec
from app.botspec.patch import PatchOp
from app.testing.scenario import Scenario, SeedRecord, TestReport

Phase = Literal[
    "triage",
    "understand",
    "clarify",
    "build",
    "testgen",
    "run",
    "repair",
    "review",
    "await_approval",
    "deploy",
    "failed",
]
RunStatus = Literal[
    "running", "waiting_user", "waiting_approval", "done", "failed", "rejected", "interrupted"
]
RunKind = Literal["create", "modify"]

ACTIVE_STATUSES: tuple[RunStatus, ...] = ("running", "waiting_user", "waiting_approval")
TERMINAL_STATUSES: tuple[RunStatus, ...] = ("done", "failed", "rejected", "interrupted")


def utcnow() -> datetime:
    return datetime.now(UTC)


class ChatTurn(BaseModel):
    role: Literal["owner", "agent"]
    text: str
    ts: datetime = Field(default_factory=utcnow)


class SupersededScenario(BaseModel):
    scenario: Scenario
    reason: str


class ScenarioFix(BaseModel):
    scenario_id: str
    reason: str


class RunState(BaseModel):
    kind: RunKind = "create"
    phase: Phase = "understand"
    conversation: list[ChatTurn] = []
    requirements: Requirements | None = None
    delta: RequirementsDelta | None = None  # modify
    clarify_rounds: int = 0
    pending_questions: list[Question] = []  # asked in the current clarify round
    draft_spec: BotSpec | None = None
    patch_ops: list[PatchOp] = []  # modify: accumulated ops against the base spec
    # Acceptance scenarios (and, in modify, carried-forward ones). Derived scenarios are re-derived
    # from the draft on every test run and kept in ``derived``.
    scenarios: list[Scenario] = []
    derived: list[Scenario] = []
    new_scenario_ids: list[str] = []  # acceptance scenarios written in THIS run (fix_scenario guard)
    scenario_fixes: list[ScenarioFix] = []
    superseded: list[SupersededScenario] = []
    test_report: TestReport | None = None
    repair_rounds: int = 0
    sample_data: list[SeedRecord] = []
    revision_id: str | None = None  # the draft revision written at review
    approval_blocked_reason: str | None = None
    # A build or repair loop that ended at the tool-call cap without ``finish`` ("build"/"repair").
    # Blocks approval until a later loop of this run finishes.
    step_limit_hit: str | None = None
    # --- modify only -------------------------------------------------------------------------
    base_revision_id: str | None = None  # the live revision the draft is a copy of
    base_spec: BotSpec | None = None
    base_requirements: Requirements | None = None
    base_sample_data: list[SeedRecord] = []
    carried_ids: list[str] = []  # carried-forward acceptance scenarios still in the active set
    record_counts: dict[str, int] = {}  # live records per collection (counts only, never records)
    max_confirmed_per_item: dict[str, int] = {}  # booking capability key -> highest confirmed count
    delta_touched: list[str] = []  # requirement ids added/changed/removed in the LATEST round
    triage: str | None = None  # change / question / data_request / unsupported
    diff: dict[str, Any] | None = None  # the review card (the `diff` event payload)
    usage: Usage = Usage()
    error: str | None = None

    def all_scenarios(self) -> list[Scenario]:
        return [*self.derived, *self.scenarios]
