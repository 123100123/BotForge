"""The CREATE workflow as a persisted phase machine (roadmap: "Agent Architecture", "Creation Workflow").

Public API (all async; ids are strings):

    orch = Orchestrator(repo, llm, limits=Limits(), bus=default_bus)
    run   = await orch.start_create(bot_id, message)   # creates a `running` run; then schedule advance
    await orch.advance(run_id)                          # runs phases until a pause or the end; never raises
    run   = await orch.post_message(run_id, message)    # answer questions / ask for changes; then advance
    run   = await orch.approve(run_id)                  # activates the draft (refused while tests fail)
    run   = await orch.reject(run_id)                   # marks the draft rejected; run ends `rejected`
    orch.spawn(run_id)                                  # schedule advance() as a background task

Phases: understand -> [clarify pause] -> build -> testgen -> run -> [repair -> run]* -> review ->
[await_approval pause] -> deploy. State is saved after every phase. Any unexpected exception marks
the run failed with an error event; a run is never left `running` by this code.

A MODIFY flow plugs in later by adding ``start_modify`` (kind="modify", base_revision_id = the active
revision, draft_spec = a copy of its spec) and per-kind phase implementations in ``PHASES_BY_KIND``;
the loop, events, persistence, approval and deploy are shared.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.agent import events as ev
from app.agent.context import Limits, Next, RunContext
from app.agent.events import Event, EventBus, default_bus
from app.agent.llm import LLMClient
from app.agent.phases import build, deploy, repair, review, testgen, understand
from app.agent.phases import run as run_phase
from app.agent.repository import ActivationRefused, AgentRepository, RunRecord
from app.agent.state import ChatTurn, Phase, RunState

log = logging.getLogger(__name__)

PhaseFn = Callable[[RunContext], Awaitable[Next]]

CREATE_PHASES: dict[str, PhaseFn] = {
    "understand": understand.run,
    "build": build.run,
    "testgen": testgen.run,
    "run": run_phase.run,
    "repair": repair.run,
    "review": review.run,
}
PHASES_BY_KIND: dict[str, dict[str, PhaseFn]] = {"create": CREATE_PHASES}
LLM_PHASES = frozenset({"understand", "build", "testgen", "repair", "review"})

UNEXPECTED_ERROR = "خطای غیرمنتظره‌ای در ساخت ربات رخ داد. لطفاً دوباره تلاش کنید."
MODIFY_UNAVAILABLE = "این ربات نسخهٔ فعال دارد و درخواست تغییر هنوز در دسترس نیست."
NOT_WAITING = "این گفتگو الان منتظر پیام شما نیست."
NOT_AWAITING_APPROVAL = "این گفتگو الان منتظر تأیید نیست."
REJECTED_TEXT = "پیش‌نویس کنار گذاشته شد و ربات فعلی تغییری نکرد."


class OrchestratorError(Exception):
    """A refused owner action. ``status`` is the HTTP status the API should use."""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class Orchestrator:
    def __init__(
        self,
        repo: AgentRepository,
        llm: LLMClient,
        *,
        limits: Limits | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.limits = limits or Limits()
        self.bus = bus or default_bus
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ events

    async def _emit(self, run_id: str, event: Event) -> None:
        envelope = await self.repo.append_event(run_id, *event)
        self.bus.publish(envelope)

    def _ctx(self, record: RunRecord, active_revision_id: str | None) -> RunContext:
        async def emit(event: Event) -> None:
            await self._emit(record.id, event)

        return RunContext(
            run_id=record.id,
            bot_id=record.bot_id,
            state=record.state,
            llm=self.llm,
            limits=self.limits,
            emit=emit,
            repo=self.repo,
            active_revision_id=active_revision_id,
        )

    # ------------------------------------------------------------------ entry points

    async def start_create(self, bot_id: str, message: str) -> RunRecord:
        """Create a CREATE run for a bot without an active revision. Caller then schedules advance."""
        bot = await self.repo.load_bot(bot_id)
        if bot.active_revision_id is not None:
            raise OrchestratorError("modify_not_available", MODIFY_UNAVAILABLE)
        state = RunState(
            kind="create", phase="understand", conversation=[ChatTurn(role="owner", text=message)]
        )
        record = await self.repo.create_run(bot_id, kind="create", state=state)
        await self._emit(record.id, ev.owner_message(message))
        return record

    async def post_message(self, run_id: str, message: str) -> RunRecord:
        """An owner message on a paused run: answers (clarify) or a change request (await_approval)."""
        record = await self.repo.load_run(run_id)
        if record.status not in ("waiting_user", "waiting_approval"):
            raise OrchestratorError("run_not_waiting", NOT_WAITING)
        if not await self.repo.claim_run(run_id, (record.status,), "running"):
            raise OrchestratorError("run_not_waiting", NOT_WAITING)
        state = record.state
        state.conversation.append(ChatTurn(role="owner", text=message))
        if record.status == "waiting_approval":
            # Re-enter understand with the conversation and the current draft as the starting point.
            state.repair_rounds = 0
            state.approval_blocked_reason = None
            state.test_report = None
        state.pending_questions = []
        state.phase = "understand"
        await self.repo.save_run(run_id, state=state, status="running")
        await self._emit(run_id, ev.owner_message(message))
        return await self.repo.load_run(run_id)

    async def approve(self, run_id: str) -> RunRecord:
        record = await self.repo.load_run(run_id)
        if record.status != "waiting_approval":
            raise OrchestratorError("run_not_awaiting_approval", NOT_AWAITING_APPROVAL)
        state = record.state
        report = state.test_report
        if report is None or report.failed > 0 or state.approval_blocked_reason:
            reason = state.approval_blocked_reason or "آزمون‌های این نسخه ناموفق است."
            raise OrchestratorError("approval_blocked", f"تأیید ممکن نیست: {reason}")
        if not await self.repo.claim_run(run_id, ("waiting_approval",), "running"):
            raise OrchestratorError("run_not_awaiting_approval", NOT_AWAITING_APPROVAL)
        bot = await self.repo.load_bot(record.bot_id)
        ctx = self._ctx(record, bot.active_revision_id)
        try:
            state.phase = "deploy"
            await self._emit(run_id, ev.phase_started("deploy"))
            try:
                nxt = await deploy.run(ctx)
            except ActivationRefused as exc:
                await self._emit(run_id, ev.phase_finished("deploy", False, exc.message))
                await self._emit(run_id, ev.error(exc.message))
                state.phase = "await_approval"
                await self.repo.save_run(run_id, state=state, status="waiting_approval")
                raise OrchestratorError(exc.code, exc.message) from None
            await self._emit(run_id, ev.phase_finished("deploy", True))
            state.phase = nxt.phase
            await self.repo.save_run(
                run_id, state=state, status=nxt.status, result_revision_id=state.revision_id
            )
        except OrchestratorError:
            raise
        except Exception as exc:
            await self._mark_failed(run_id, state, exc)
            raise OrchestratorError("internal_error", UNEXPECTED_ERROR, 500) from None
        return await self.repo.load_run(run_id)

    async def reject(self, run_id: str) -> RunRecord:
        record = await self.repo.load_run(run_id)
        if record.status not in ("waiting_approval", "waiting_user"):
            raise OrchestratorError("run_not_waiting", NOT_WAITING)
        if not await self.repo.claim_run(run_id, (record.status,), "rejected"):
            raise OrchestratorError("run_not_waiting", NOT_WAITING)
        state = record.state
        if state.revision_id is not None:
            await self.repo.reject_revision(state.revision_id)
        state.conversation.append(ChatTurn(role="agent", text=REJECTED_TEXT))
        await self.repo.save_run(run_id, state=state, status="rejected")
        await self._emit(run_id, ev.agent_message(REJECTED_TEXT))
        return await self.repo.load_run(run_id)

    # ------------------------------------------------------------------ the phase loop

    async def advance(self, run_id: str) -> None:
        """Run phases until the run pauses or ends. Never raises (except cancellation)."""
        state: RunState | None = None
        try:
            record = await self.repo.load_run(run_id)
            if record.status != "running":
                return
            state = record.state
            bot = await self.repo.load_bot(record.bot_id)
            ctx = self._ctx(record, bot.active_revision_id)
            phases = PHASES_BY_KIND[state.kind]
            status = "running"
            while status == "running":
                phase: Phase = state.phase
                fn = phases.get(phase)
                if fn is None:
                    raise RuntimeError(f"no implementation for phase '{phase}' ({state.kind})")
                await ctx.emit(ev.phase_started(phase))
                usage_before = state.usage.model_copy()
                nxt = await fn(ctx)
                await ctx.emit(ev.phase_finished(phase, nxt.phase != "failed"))
                if phase in LLM_PHASES and state.usage != usage_before:
                    await ctx.emit(ev.usage(state.usage))
                state.phase = nxt.phase
                status = nxt.status
                await self.repo.save_run(run_id, state=state, status=status)
        except asyncio.CancelledError:
            if state is not None:
                try:
                    await self.repo.save_run(run_id, state=state, status="interrupted")
                except Exception:
                    log.exception("could not mark run %s interrupted", run_id)
            raise
        except Exception as exc:
            await self._mark_failed(run_id, state, exc)

    async def _mark_failed(self, run_id: str, state: RunState | None, exc: BaseException) -> None:
        log.exception("agent run %s failed", run_id, exc_info=exc)
        try:
            if state is None:
                state = (await self.repo.load_run(run_id)).state
            state.error = f"{type(exc).__name__}: {exc}"[:2000]
            state.phase = "failed"
            await self._emit(run_id, ev.error(UNEXPECTED_ERROR))
            await self.repo.save_run(run_id, state=state, status="failed")
        except Exception:
            log.exception("could not record the failure of run %s", run_id)

    # ------------------------------------------------------------------ background tasks

    def spawn(self, run_id: str) -> asyncio.Task[None]:
        """Schedule ``advance(run_id)`` on the running loop and keep a reference until it ends."""
        task = asyncio.create_task(self.advance(run_id), name=f"agent-run-{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def wait_idle(self) -> None:
        """Wait for every scheduled run task (tests, scripts, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
