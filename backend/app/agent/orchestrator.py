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

MODIFY (a change to a bot with an active revision; roadmap "Modification Workflow"):

    run   = await orch.start_modify(bot_id, message)   # base = the active revision; then advance
    run   = await orch.start(bot_id, message)          # create or modify, by the bot's state

Phases: triage -> [done: question / data_request / unsupported] | understand (understand_change)
-> [clarify pause] -> build (patch-only + compat) -> testgen (derived + carried + new) -> run ->
[repair -> run]* -> review (diff card) -> [await_approval pause] -> deploy. The draft is a copy of
the base revision's spec; the live bot is untouched until ``approve`` activates the draft, which is
refused while any scenario fails and ends the run when the live revision changed meanwhile.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.agent import events as ev
from app.agent.context import Limits, Next, RunContext
from app.agent.events import Event, EventBus, default_bus
from app.agent.llm import LLMClient
from app.agent.modify import empty_requirements, uncovered_requirements, uncovered_text
from app.agent.phases import (
    STEP_LIMIT_TEXT,
    build,
    build_change,
    deploy,
    repair,
    review,
    review_change,
    testgen,
    testgen_change,
    triage,
    understand,
    understand_change,
)
from app.agent.phases import run as run_phase
from app.agent.phases.testgen import NO_ACCEPTANCE
from app.agent.repository import ActivationRefused, AgentRepository, RunRecord
from app.agent.state import TERMINAL_STATUSES, ChatTurn, Phase, RunState
from app.security.redact import redact

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
MODIFY_PHASES: dict[str, PhaseFn] = {
    "triage": triage.run,
    "understand": understand_change.run,
    "build": build_change.run,
    "testgen": testgen_change.run,
    "run": run_phase.run,
    "repair": repair.run,
    "review": review_change.run,
}
PHASES_BY_KIND: dict[str, dict[str, PhaseFn]] = {"create": CREATE_PHASES, "modify": MODIFY_PHASES}
LLM_PHASES = frozenset({"triage", "understand", "build", "testgen", "repair", "review"})
# How often an executing run refreshes its heartbeat. Must stay well below
# app.main.STALE_RUN_AFTER, after which a run without a heartbeat counts as abandoned.
HEARTBEAT_SECONDS = 20.0

UNEXPECTED_ERROR = "خطای غیرمنتظره‌ای در ساخت ربات رخ داد. لطفاً دوباره تلاش کنید."
MODIFY_UNAVAILABLE = "این ربات نسخهٔ فعال دارد؛ برای تغییر آن یک درخواست تغییر بفرستید."
NO_ACTIVE_REVISION = "این ربات هنوز نسخهٔ فعالی ندارد؛ ابتدا ربات را بسازید و تأیید کنید."
STALE_BASE_TEXT = (
    "نسخهٔ فعال ربات از زمان شروع این تغییر عوض شده است، پس این پیش‌نویس قابل فعال‌سازی نیست. "
    "لطفاً درخواست تغییر را دوباره بفرستید."
)
UNPROVEN = "آزمون‌های این نسخه کامل اجرا نشده یا ناموفق است."
TOKEN_NOTICE = (
    "به نظر می‌رسد پیام شما توکن ربات تلگرام داشت؛ آن را حذف کردم و ذخیره یا ارسال نشد. "
    "توکن را فقط در بخش «تنظیمات» وارد کنید."
)
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


def approval_block(state: RunState) -> str | None:
    """Why the draft may not be approved, or None.

    Approval needs a test report in which every scenario of the active set (derived + carried +
    new) has a passing result, and no recorded blocking reason (budget, missing tests, compat).
    """
    report = state.test_report
    if state.approval_blocked_reason:
        return state.approval_blocked_reason
    if state.step_limit_hit:
        return STEP_LIMIT_TEXT
    if report is None or report.failed > 0:
        return "آزمون‌های این نسخه ناموفق است."
    passed = {r.scenario_id for r in report.results if r.passed}
    if any(s.id not in passed for s in state.all_scenarios()):
        return UNPROVEN
    if state.kind == "create" and not any(s.source == "acceptance" for s in state.scenarios):
        return NO_ACCEPTANCE
    if state.kind == "modify":
        uncovered = uncovered_requirements(state.delta, state.scenarios, state.new_scenario_ids, passed)
        if uncovered:
            return uncovered_text(uncovered)
    return None


class Orchestrator:
    def __init__(
        self,
        repo: AgentRepository,
        llm: LLMClient,
        *,
        limits: Limits | None = None,
        bus: EventBus | None = None,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.limits = limits or Limits()
        self.bus = bus or default_bus
        self.heartbeat_seconds = heartbeat_seconds
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ events

    async def _emit(self, run_id: str, event: Event) -> None:
        envelope = await self.repo.append_event(run_id, *event)
        self.bus.publish(envelope)

    async def _save(self, run_id: str, state: RunState, status: str, **kwargs: Any) -> None:
        """Persist the run, then announce the status (every transition emits ``run_status``)."""
        await self.repo.save_run(run_id, state=state, status=status, **kwargs)
        await self._emit(run_id, ev.run_status(status, state.phase))

    async def ensure_status_event(self, run_id: str) -> None:
        """A terminal run whose last ``run_status`` disagrees with its stored status (e.g. marked
        ``interrupted`` at startup, outside the orchestrator) gets the missing event."""
        record = await self.repo.load_run(run_id)
        if record.status not in TERMINAL_STATUSES:
            return
        events = await self.repo.list_events(run_id)
        last = next((e for e in reversed(events) if e.type == ev.RUN_STATUS), None)
        if last is None or last.payload.get("status") != record.status:
            await self._emit(run_id, ev.run_status(record.status, record.phase))

    @staticmethod
    def _intake(state: RunState, message: str) -> list[Event]:
        """Owner text enters the run: token-shaped secrets are replaced BEFORE anything is stored,
        emitted, or sent to a model. Returns the events to emit (owner message, maybe a notice)."""
        clean = redact(message)
        state.conversation.append(ChatTurn(role="owner", text=clean))
        events: list[Event] = [ev.owner_message(clean)]
        if clean != message:
            state.conversation.append(ChatTurn(role="agent", text=TOKEN_NOTICE))
            events.append(ev.agent_message(TOKEN_NOTICE))
        return events

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
        state = RunState(kind="create", phase="understand")
        intake = self._intake(state, message)
        record = await self.repo.create_run(bot_id, kind="create", state=state)
        for event in intake:
            await self._emit(record.id, event)
        await self._emit(record.id, ev.run_status("running", state.phase))
        return record

    async def start_modify(self, bot_id: str, message: str) -> RunRecord:
        """Create a MODIFY run on the bot's active revision. Caller then schedules advance.

        The draft starts as a deep copy of the base revision's spec; nothing live is touched.
        """
        bot = await self.repo.load_bot(bot_id)
        if bot.active_revision_id is None:
            raise OrchestratorError("no_active_revision", NO_ACTIVE_REVISION)
        base = await self.repo.load_revision(bot.active_revision_id)
        state = RunState(
            kind="modify",
            phase="triage",
            base_revision_id=base.id,
            base_spec=base.spec,
            base_requirements=base.requirements,
            requirements=base.requirements or empty_requirements(),
            draft_spec=base.spec.model_copy(deep=True),
            base_sample_data=base.sample_data,
        )
        intake = self._intake(state, message)
        record = await self.repo.create_run(bot_id, kind="modify", state=state, base_revision_id=base.id)
        for event in intake:
            await self._emit(record.id, event)
        await self._emit(record.id, ev.run_status("running", state.phase))
        return record

    async def start(self, bot_id: str, message: str) -> RunRecord:
        """CREATE for a bot without an active revision, MODIFY otherwise."""
        bot = await self.repo.load_bot(bot_id)
        if bot.active_revision_id is None:
            return await self.start_create(bot_id, message)
        return await self.start_modify(bot_id, message)

    async def post_message(self, run_id: str, message: str) -> RunRecord:
        """An owner message on a paused run: answers (clarify) or a change request (await_approval)."""
        record = await self.repo.load_run(run_id)
        if record.status not in ("waiting_user", "waiting_approval"):
            raise OrchestratorError("run_not_waiting", NOT_WAITING)
        if not await self.repo.claim_run(run_id, (record.status,), "running"):
            raise OrchestratorError("run_not_waiting", NOT_WAITING)
        state = record.state
        intake = self._intake(state, message)
        if record.status == "waiting_approval":
            # Re-enter understand with the conversation and the current draft as the starting point.
            state.repair_rounds = 0
            state.approval_blocked_reason = None
            state.test_report = None
        state.pending_questions = []
        state.phase = "understand"
        await self.repo.save_run(run_id, state=state, status="running")
        for event in intake:
            await self._emit(run_id, event)
        await self._emit(run_id, ev.run_status("running", state.phase))
        return await self.repo.load_run(run_id)

    async def approve(self, run_id: str) -> RunRecord:
        record = await self.repo.load_run(run_id)
        if record.status != "waiting_approval":
            raise OrchestratorError("run_not_awaiting_approval", NOT_AWAITING_APPROVAL)
        state = record.state
        reason = approval_block(state)
        if reason is not None:
            raise OrchestratorError("approval_blocked", f"تأیید ممکن نیست: {reason}")
        if not await self.repo.claim_run(run_id, ("waiting_approval",), "running"):
            raise OrchestratorError("run_not_awaiting_approval", NOT_AWAITING_APPROVAL)
        bot = await self.repo.load_bot(record.bot_id)
        ctx = self._ctx(record, bot.active_revision_id)
        try:
            state.phase = "deploy"
            await self._emit(run_id, ev.run_status("running", state.phase))
            await self._emit(run_id, ev.phase_started("deploy"))
            if state.kind == "modify" and bot.active_revision_id != state.base_revision_id:
                await self._end_stale(run_id, state)  # raises
            try:
                nxt = await deploy.run(ctx)
            except ActivationRefused as exc:
                if exc.code == "stale_base":
                    await self._end_stale(run_id, state)  # raises
                # The run is not over: it waits for approval again. No `error` event (reserved for
                # runs that end failed); the owner is told why and what to do.
                text = f"فعال‌سازی انجام نشد: {exc.message}"
                await self._emit(run_id, ev.phase_finished("deploy", False, exc.message))
                state.conversation.append(ChatTurn(role="agent", text=text))
                await self._emit(run_id, ev.agent_message(text))
                state.phase = "await_approval"
                await self._save(run_id, state, "waiting_approval")
                raise OrchestratorError(exc.code, exc.message) from None
            await self._emit(run_id, ev.phase_finished("deploy", True))
            state.phase = nxt.phase
            await self._save(run_id, state, nxt.status, result_revision_id=state.revision_id)
        except OrchestratorError:
            raise
        except Exception as exc:
            await self._mark_failed(run_id, state, exc)
            raise OrchestratorError("internal_error", UNEXPECTED_ERROR, 500) from None
        return await self.repo.load_run(run_id)

    async def _end_stale(self, run_id: str, state: RunState) -> None:
        """The live revision changed since the run started: the draft can never go live.

        Ends the run (failed), rejects the draft, tells the owner to send the change again, and
        raises ``OrchestratorError("stale_base")``. The live revision is untouched.
        """
        if state.revision_id is not None:
            await self.repo.reject_revision(state.revision_id)
        state.error = "stale_base"
        state.phase = "failed"
        state.conversation.append(ChatTurn(role="agent", text=STALE_BASE_TEXT))
        await self._emit(run_id, ev.phase_finished("deploy", False, "stale_base"))
        await self._emit(run_id, ev.error(STALE_BASE_TEXT))
        await self._emit(run_id, ev.agent_message(STALE_BASE_TEXT))
        await self._save(run_id, state, "failed")
        raise OrchestratorError("stale_base", STALE_BASE_TEXT)

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
        await self._emit(run_id, ev.run_status("rejected", state.phase))
        return await self.repo.load_run(run_id)

    # ------------------------------------------------------------------ the phase loop

    async def advance(self, run_id: str) -> None:
        """Run phases until the run pauses or ends. Never raises (except cancellation).

        While it runs, a heartbeat keeps the run's ``updated_at`` fresh: a starting process (a
        restart, or the next container during a zero-downtime deploy, while this one still serves)
        interrupts only runs whose heartbeat has stopped (``app.main.mark_interrupted_runs``)."""
        heartbeat = asyncio.create_task(self._heartbeat(run_id), name=f"agent-heartbeat-{run_id}")
        try:
            await self._advance(run_id)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self, run_id: str) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                await self.repo.touch_run(run_id)
            except Exception:
                log.exception("could not refresh the heartbeat of run %s", run_id)

    async def _advance(self, run_id: str) -> None:
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
                if status == "running":
                    await self.repo.save_run(run_id, state=state, status=status)
                else:
                    await self._save(run_id, state, status)
        except asyncio.CancelledError:
            if state is not None:
                try:
                    await self._save(run_id, state, "interrupted")
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
            # Provider failures (LLMError from a tool loop) carry an owner-safe Persian text.
            await self._emit(run_id, ev.error(getattr(exc, "owner_message", None) or UNEXPECTED_ERROR))
            await self._save(run_id, state, "failed")
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
