"""Agent runs: start a run, answer, approve, reject, and tail events over SSE.

Runs execute as asyncio background tasks inside this process (``Orchestrator.spawn``); the request
only creates or claims the run. A bot without an active revision gets a CREATE run; a bot with one
gets a MODIFY run (triage first: questions, data requests and unsupported asks end without a
revision). One active run per bot; a per-account daily cap and a per-user rate limit guard run
creation.
"""

import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import Limits, get_agent_settings
from app.agent.events import EventEnvelope
from app.agent.llm import AnthropicLLM
from app.agent.orchestrator import Orchestrator, OrchestratorError
from app.agent.repository import ActiveRunExists, RepositoryError, RunRecord, SqlAgentRepository
from app.agent.state import TERMINAL_STATUSES
from app.api.deps import CurrentUser, get_current_user, get_owned_bot, get_owned_run
from app.db.models import AgentRun, Bot
from app.db.session import get_session, get_sessionmaker

router = APIRouter(tags=["runs"])

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
SSE_HEARTBEAT_SECONDS = 15.0
DAILY_CAP_MESSAGE = "به سقف تعداد گفتگوهای ساخت امروز رسیده‌اید. لطفاً فردا دوباره تلاش کنید."
RATE_LIMIT_MESSAGE = "درخواست‌ها خیلی سریع ارسال شده‌اند. لطفاً کمی صبر کنید و دوباره تلاش کنید."


class MessageIn(BaseModel):
    message: Message


class RunOut(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    kind: str
    phase: str
    status: str
    base_revision_id: uuid.UUID | None
    result_revision_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


def _from_record(r: RunRecord) -> RunOut:
    return RunOut(
        id=uuid.UUID(r.id),
        bot_id=uuid.UUID(r.bot_id),
        kind=r.kind,
        phase=r.phase,
        status=r.status,
        base_revision_id=uuid.UUID(r.base_revision_id) if r.base_revision_id else None,
        result_revision_id=uuid.UUID(r.result_revision_id) if r.result_revision_id else None,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _from_row(r: AgentRun) -> RunOut:
    return RunOut(
        id=r.id,
        bot_id=r.bot_id,
        kind=r.kind,
        phase=r.phase,
        status=r.status,
        base_revision_id=r.base_revision_id,
        result_revision_id=r.result_revision_id,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


# --------------------------------------------------------------------------- dependencies

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """The process-wide orchestrator (SQL repository, Anthropic client). Tests override this."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(
            SqlAgentRepository(get_sessionmaker()), AnthropicLLM(), limits=Limits.from_settings()
        )
    return _orchestrator


class RateLimiter:
    """At most ``limit`` events per ``window`` seconds per key (in process; one backend process)."""

    def __init__(self, window: float = 60.0) -> None:
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


run_creation_limiter = RateLimiter()


def _raise_for(exc: OrchestratorError | RepositoryError) -> HTTPException:
    if isinstance(exc, OrchestratorError):
        return _err(exc.status, exc.code, exc.message)
    status = 404 if exc.code in ("run_not_found", "bot_not_found") else 409
    return _err(status, exc.code, exc.message)


# --------------------------------------------------------------------------- endpoints


@router.post("/bots/{bot_id}/runs", response_model=RunOut, status_code=201)
async def create_run(
    body: MessageIn,
    bot: Bot = Depends(get_owned_bot),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> RunOut:
    modify = bot.active_revision_id is not None
    settings = get_agent_settings()
    since = datetime.now(UTC) - timedelta(days=1)
    today = (
        await session.execute(
            select(func.count())
            .select_from(AgentRun)
            .join(Bot, Bot.id == AgentRun.bot_id)
            .where(Bot.owner_id == user.id, AgentRun.created_at >= since)
        )
    ).scalar_one()
    if today >= settings.AGENT_DAILY_RUN_CAP:
        raise _err(429, "daily_run_cap", DAILY_CAP_MESSAGE)
    if not run_creation_limiter.allow(user.id, settings.AGENT_RUNS_PER_MINUTE):
        raise _err(429, "rate_limited", RATE_LIMIT_MESSAGE)
    await session.commit()  # release the request's connection before the run starts
    try:
        start = orchestrator.start_modify if modify else orchestrator.start_create
        record = await start(str(bot.id), body.message)
    except ActiveRunExists as exc:
        raise _err(409, exc.code, exc.message) from None
    except (OrchestratorError, RepositoryError) as exc:
        raise _raise_for(exc) from None
    orchestrator.spawn(record.id)
    return _from_record(record)


@router.get("/bots/{bot_id}/runs", response_model=list[RunOut])
async def list_runs(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> list[RunOut]:
    rows = (
        await session.execute(
            select(AgentRun)
            .where(AgentRun.bot_id == bot.id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id)
        )
    ).scalars()
    return [_from_row(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
async def read_run(run: AgentRun = Depends(get_owned_run)) -> RunOut:
    return _from_row(run)


async def _act(session: AsyncSession, action: Any) -> RunRecord:
    await session.commit()  # the ownership check is done; the orchestrator uses its own sessions
    try:
        return await action
    except (OrchestratorError, RepositoryError) as exc:
        raise _raise_for(exc) from None


@router.post("/runs/{run_id}/messages", response_model=RunOut)
async def post_message(
    body: MessageIn,
    run: AgentRun = Depends(get_owned_run),
    session: AsyncSession = Depends(get_session),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> RunOut:
    record = await _act(session, orchestrator.post_message(str(run.id), body.message))
    orchestrator.spawn(record.id)
    return _from_record(record)


@router.post("/runs/{run_id}/approve", response_model=RunOut)
async def approve_run(
    run: AgentRun = Depends(get_owned_run),
    session: AsyncSession = Depends(get_session),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> RunOut:
    return _from_record(await _act(session, orchestrator.approve(str(run.id))))


@router.post("/runs/{run_id}/reject", response_model=RunOut)
async def reject_run(
    run: AgentRun = Depends(get_owned_run),
    session: AsyncSession = Depends(get_session),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> RunOut:
    return _from_record(await _act(session, orchestrator.reject(str(run.id))))


def sse_frame(envelope: EventEnvelope) -> str:
    data = json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False)
    return f"id: {envelope.id}\ndata: {data}\n\n"


@router.get("/runs/{run_id}/events")
async def stream_events(
    request: Request,
    run: AgentRun = Depends(get_owned_run),
    session: AsyncSession = Depends(get_session),
    last_event_id: str | None = Header(None),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> StreamingResponse:
    """SSE: replay events after ``Last-Event-ID`` from the table, then live; ends once the run ends."""
    run_id = str(run.id)
    await session.commit()  # do not hold a database connection for the life of the stream
    try:
        after: int | None = int(last_event_id) if last_event_id else None
    except ValueError:
        after = None

    # Runs that ended outside the orchestrator (marked interrupted at startup) get their
    # run_status event before the replay, so clients never wait on a silent status.
    await orchestrator.ensure_status_event(run_id)

    async def frames() -> AsyncIterator[str]:
        last = after
        async with orchestrator.bus.subscribe(run_id) as queue:  # subscribe first: no gap
            while True:
                for envelope in await orchestrator.repo.list_events(run_id, last):
                    yield sse_frame(envelope)
                    last = envelope.id
                if (await orchestrator.repo.load_run(run_id)).status in TERMINAL_STATUSES:
                    for envelope in await orchestrator.repo.list_events(run_id, last):
                        yield sse_frame(envelope)
                    return
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                    continue
                if last is None or envelope.id > last:
                    yield sse_frame(envelope)
                    last = envelope.id

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
