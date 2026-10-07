"""Persistence boundary for the orchestrator.

The orchestrator runs as a background task, outside any request, so every method of
``SqlAgentRepository`` opens and commits its own session. ``InMemoryAgentRepository`` implements the
same protocol for unit tests. Ids cross this boundary as strings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.events import EventEnvelope, run_status
from app.agent.requirements import Requirements
from app.agent.state import ACTIVE_STATUSES, RunState
from app.botspec.models import BotSpec, FieldType
from app.botspec.records import validate_record
from app.db.models import AgentEvent, AgentRun, Bot, RecordRow, Revision
from app.revisions import service as revisions
from app.runtime.pg_store import advisory_lock
from app.testing.scenario import Scenario, SeedRecord, resolve_relative


class RepositoryError(Exception):
    """Domain error with a stable ``code`` and a Persian ``message``."""

    code = "repository_error"
    message = "خطایی در ذخیره‌سازی رخ داد."

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        self.message = message or type(self).message
        if code is not None:
            self.code = code
        super().__init__(self.message)


class RunNotFound(RepositoryError):
    code = "run_not_found"
    message = "اجرای ایجنت پیدا نشد."


class BotMissing(RepositoryError):
    code = "bot_not_found"
    message = "ربات پیدا نشد."


class ActiveRunExists(RepositoryError):
    code = "run_in_progress"
    message = "برای این ربات یک گفتگوی ساخت در جریان است. ابتدا آن را تمام یا رد کنید."


class ActivationRefused(RepositoryError):
    code = "activation_refused"
    message = "این نسخه قابل فعال‌سازی نیست."


class SampleDataInvalid(RepositoryError):
    code = "invalid_sample_data"
    message = "داده‌های نمونه نامعتبر است."


@dataclass
class RunRecord:
    id: str
    bot_id: str
    kind: str
    phase: str
    status: str
    state: RunState
    base_revision_id: str | None = None
    result_revision_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class BotInfo:
    id: str
    name: str
    owner_id: str
    active_revision_id: str | None


@dataclass
class DraftRevision:
    id: str
    number: int


@dataclass
class RevisionSnapshot:
    """What a MODIFY run needs from its base revision."""

    id: str
    number: int
    status: str
    spec: BotSpec
    requirements: Requirements | None
    scenarios: list[Scenario]
    sample_data: list[SeedRecord]


@dataclass
class LiveStats:
    """Live data shape for the compatibility check: counts only, never record contents."""

    record_counts: dict[str, int] = field(default_factory=dict)  # collection -> live records
    max_confirmed_per_item: dict[str, int] = field(default_factory=dict)  # booking key -> max


_UNSET: Any = object()


class AgentRepository(Protocol):
    async def create_run(
        self, bot_id: str, *, kind: str, state: RunState, base_revision_id: str | None = None
    ) -> RunRecord:
        """Insert a ``running`` run. Raises ActiveRunExists if the bot has an active run."""
        ...

    async def load_run(self, run_id: str) -> RunRecord: ...

    async def save_run(
        self, run_id: str, *, state: RunState, status: str, result_revision_id: str | None = _UNSET
    ) -> None: ...

    async def claim_run(self, run_id: str, from_statuses: tuple[str, ...], to_status: str) -> bool:
        """Atomically move a run from one of ``from_statuses`` to ``to_status``; False if not."""
        ...

    async def touch_run(self, run_id: str) -> None:
        """Heartbeat: refresh ``updated_at`` of a ``running`` run, so that no process (this one
        after a restart, or the next container during a deploy) takes it for abandoned."""
        ...

    async def append_event(self, run_id: str, type_: str, payload: dict[str, Any]) -> EventEnvelope: ...

    async def list_events(self, run_id: str, after_id: int | None = None) -> list[EventEnvelope]: ...

    async def load_bot(self, bot_id: str) -> BotInfo: ...

    async def load_revision_spec(self, revision_id: str) -> BotSpec: ...

    async def load_revision(self, revision_id: str) -> RevisionSnapshot:
        """Spec, requirements, scenarios and sample data of one revision (the MODIFY base)."""
        ...

    async def live_stats(self, bot_id: str) -> LiveStats:
        """Live record counts per collection and the highest confirmed count per booking item."""
        ...

    async def create_draft_revision(
        self,
        bot_id: str,
        *,
        spec: BotSpec,
        requirements: BaseModel | None,
        scenarios: list[Any],
        test_report: BaseModel | None,
        sample_data: list[SeedRecord],
        change_request: str | None,
        parent_id: str | None,
        patch: list[Any] | None = None,
        superseded: list[Any] | None = None,
    ) -> DraftRevision: ...

    async def load_sample_data(self, revision_id: str) -> int:
        """Replace the bot's sandbox data with the revision's sample data; returns records loaded."""
        ...

    async def activate(self, revision_id: str) -> int:
        """Activate a draft (revisions service rules); returns its number. Raises ActivationRefused."""
        ...

    async def reject_revision(self, revision_id: str) -> None: ...


def _uuid(value: str | None) -> uuid.UUID | None:
    return None if value is None else uuid.UUID(str(value))


def _str(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value


def _snapshot(
    rid: str, number: int, status: str, spec: Any, requirements: Any, scenarios: Any, sample_data: Any
) -> RevisionSnapshot:
    return RevisionSnapshot(
        id=rid,
        number=number,
        status=status,
        spec=spec.model_copy(deep=True) if isinstance(spec, BotSpec) else BotSpec.model_validate(spec),
        requirements=Requirements.model_validate(_dump(requirements)) if requirements else None,
        scenarios=[Scenario.model_validate(_dump(s)) for s in scenarios or []],
        sample_data=[SeedRecord.model_validate(_dump(r)) for r in sample_data or []],
    )


# --------------------------------------------------------------------------- SQL


class SqlAgentRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    @staticmethod
    def _record(row: AgentRun) -> RunRecord:
        return RunRecord(
            id=str(row.id),
            bot_id=str(row.bot_id),
            kind=row.kind,
            phase=row.phase,
            status=row.status,
            state=RunState.model_validate(row.state or {}),
            base_revision_id=_str(row.base_revision_id),
            result_revision_id=_str(row.result_revision_id),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create_run(
        self, bot_id: str, *, kind: str, state: RunState, base_revision_id: str | None = None
    ) -> RunRecord:
        bid = _uuid(bot_id)
        assert bid is not None
        async with self._sm() as session:
            await advisory_lock(session, bid)  # serializes "one active run per bot"
            if await session.get(Bot, bid) is None:
                raise BotMissing()
            active = (
                await session.execute(
                    select(func.count())
                    .select_from(AgentRun)
                    .where(AgentRun.bot_id == bid, AgentRun.status.in_(ACTIVE_STATUSES))
                )
            ).scalar_one()
            if active:
                raise ActiveRunExists()
            row = AgentRun(
                bot_id=bid,
                kind=kind,
                phase=state.phase,
                status="running",
                state=state.model_dump(mode="json"),
                base_revision_id=_uuid(base_revision_id),
                usage=state.usage.model_dump(mode="json"),
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            record = self._record(row)
            await session.commit()
            return record

    async def load_run(self, run_id: str) -> RunRecord:
        async with self._sm() as session:
            row = await session.get(AgentRun, _uuid(run_id))
            if row is None:
                raise RunNotFound()
            return self._record(row)

    async def save_run(
        self, run_id: str, *, state: RunState, status: str, result_revision_id: str | None = _UNSET
    ) -> None:
        values: dict[str, Any] = {
            "state": state.model_dump(mode="json"),
            "phase": state.phase,
            "status": status,
            "usage": state.usage.model_dump(mode="json"),
            "updated_at": func.now(),
        }
        if result_revision_id is not _UNSET:
            values["result_revision_id"] = _uuid(result_revision_id)
        async with self._sm() as session:
            await session.execute(update(AgentRun).where(AgentRun.id == _uuid(run_id)).values(**values))
            await session.commit()

    async def claim_run(self, run_id: str, from_statuses: tuple[str, ...], to_status: str) -> bool:
        async with self._sm() as session:
            result = await session.execute(
                update(AgentRun)
                .where(AgentRun.id == _uuid(run_id), AgentRun.status.in_(from_statuses))
                .values(status=to_status, updated_at=func.now())
                .returning(AgentRun.id)
            )
            claimed = result.first() is not None
            await session.commit()
            return claimed

    async def touch_run(self, run_id: str) -> None:
        async with self._sm() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == _uuid(run_id), AgentRun.status == "running")
                .values(updated_at=func.now())
            )
            await session.commit()

    async def interrupt_stale_runs(self, stale_after: timedelta) -> list[EventEnvelope]:
        """Mark ``interrupted`` every ``running`` run without a heartbeat for ``stale_after``.

        The executing process refreshes ``updated_at`` (``touch_run``) far more often than that,
        so only runs whose process is gone qualify. The status change and the ``run_status`` event
        commit together, so a reader never sees one without the other. Database time on both
        sides, so clock skew between containers does not matter. Returns the new events.
        """
        async with self._sm() as session:
            ended = (
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.status == "running", AgentRun.updated_at < func.now() - stale_after)
                    .values(status="interrupted", updated_at=func.now())
                    .returning(AgentRun.id, AgentRun.phase)
                )
            ).all()
            rows = []
            for run_id, phase in ended:
                type_, payload = run_status("interrupted", phase)
                rows.append(AgentEvent(run_id=run_id, type=type_, payload=payload))
            session.add_all(rows)
            await session.flush()
            envelopes = [
                EventEnvelope(id=r.id, run_id=str(r.run_id), ts=r.ts, type=r.type, payload=r.payload)
                for r in rows
            ]
            await session.commit()
            return envelopes

    async def append_event(self, run_id: str, type_: str, payload: dict[str, Any]) -> EventEnvelope:
        async with self._sm() as session:
            row = AgentEvent(run_id=_uuid(run_id), type=type_, payload=payload)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            envelope = EventEnvelope(
                id=row.id, run_id=str(row.run_id), ts=row.ts, type=row.type, payload=row.payload
            )
            await session.commit()
            return envelope

    async def list_events(self, run_id: str, after_id: int | None = None) -> list[EventEnvelope]:
        stmt = select(AgentEvent).where(AgentEvent.run_id == _uuid(run_id))
        if after_id is not None:
            stmt = stmt.where(AgentEvent.id > after_id)
        async with self._sm() as session:
            rows = (await session.execute(stmt.order_by(AgentEvent.id))).scalars().all()
            return [
                EventEnvelope(id=r.id, run_id=str(r.run_id), ts=r.ts, type=r.type, payload=r.payload)
                for r in rows
            ]

    async def load_bot(self, bot_id: str) -> BotInfo:
        async with self._sm() as session:
            bot = await session.get(Bot, _uuid(bot_id))
            if bot is None:
                raise BotMissing()
            return BotInfo(str(bot.id), bot.name, bot.owner_id, _str(bot.active_revision_id))

    async def load_revision_spec(self, revision_id: str) -> BotSpec:
        async with self._sm() as session:
            revision = await session.get(Revision, _uuid(revision_id))
            if revision is None:
                raise RepositoryError(code="revision_not_found", message="نسخه پیدا نشد.")
            return BotSpec.model_validate(revision.spec)

    async def load_revision(self, revision_id: str) -> RevisionSnapshot:
        async with self._sm() as session:
            r = await session.get(Revision, _uuid(revision_id))
            if r is None:
                raise RepositoryError(code="revision_not_found", message="نسخه پیدا نشد.")
            return _snapshot(
                str(r.id), r.number, r.status, r.spec, r.requirements, r.scenarios, r.sample_data
            )

    async def live_stats(self, bot_id: str) -> LiveStats:
        bid = _uuid(bot_id)
        live = (RecordRow.bot_id == bid, RecordRow.env == "live")
        async with self._sm() as session:
            counts = await session.execute(
                select(RecordRow.collection, func.count()).where(*live).group_by(RecordRow.collection)
            )
            per_item = (
                select(RecordRow.collection, RecordRow.item_id, func.count().label("n"))
                .where(*live, RecordRow.status == "confirmed", RecordRow.item_id.is_not(None))
                .group_by(RecordRow.collection, RecordRow.item_id)
                .subquery()
            )
            confirmed = await session.execute(
                select(per_item.c.collection, func.max(per_item.c.n)).group_by(per_item.c.collection)
            )
            return LiveStats(
                record_counts={str(c): int(n) for c, n in counts.all()},
                max_confirmed_per_item={str(c): int(n) for c, n in confirmed.all()},
            )

    async def create_draft_revision(
        self,
        bot_id: str,
        *,
        spec: BotSpec,
        requirements: BaseModel | None,
        scenarios: list[Any],
        test_report: BaseModel | None,
        sample_data: list[SeedRecord],
        change_request: str | None,
        parent_id: str | None,
        patch: list[Any] | None = None,
        superseded: list[Any] | None = None,
    ) -> DraftRevision:
        async with self._sm() as session:
            try:
                revision = await revisions.create_draft(
                    session,
                    _uuid(bot_id),  # type: ignore[arg-type]
                    spec=spec,
                    requirements=requirements,
                    patch=patch,
                    change_request=change_request,
                    scenarios=scenarios,
                    superseded=superseded,
                    test_report=test_report,
                    sample_data=sample_data,
                    parent_id=_uuid(parent_id),
                )
            except revisions.BotNotFound:
                raise BotMissing() from None
            draft = DraftRevision(str(revision.id), revision.number)
            await session.commit()
            return draft

    async def load_sample_data(self, revision_id: str) -> int:
        async with self._sm() as session:
            revision = await session.get(Revision, _uuid(revision_id))
            if revision is None:
                raise RepositoryError(code="revision_not_found", message="نسخه پیدا نشد.")
            try:
                loaded = await revisions.load_sample_data(
                    session, revision.bot_id, revision, datetime.now(UTC)
                )
            except revisions.InvalidSampleData as exc:
                raise SampleDataInvalid(exc.message) from None
            await session.commit()
            return len(loaded)

    async def activate(self, revision_id: str) -> int:
        async with self._sm() as session:
            try:
                revision = await revisions.activate(session, _uuid(revision_id))  # type: ignore[arg-type]
            except revisions.RevisionError as exc:
                raise ActivationRefused(exc.message, code=exc.code) from None
            number = revision.number
            await session.commit()
            return number

    async def reject_revision(self, revision_id: str) -> None:
        async with self._sm() as session:
            await session.execute(
                update(Revision)
                .where(Revision.id == _uuid(revision_id), Revision.status == "draft")
                .values(status="rejected")
            )
            await session.commit()


# --------------------------------------------------------------------------- in memory


@dataclass
class MemRevision:
    id: str
    bot_id: str
    number: int
    parent_id: str | None
    status: str
    spec: BotSpec
    requirements: Any
    scenarios: list[Any]
    test_report: Any
    sample_data: list[SeedRecord]
    change_request: str | None
    patch: list[Any] | None = None
    superseded: list[Any] | None = None


class InMemoryAgentRepository:
    """Same contract as the SQL repository, in process memory (unit tests, eval scripts)."""

    def __init__(self) -> None:
        self.bots: dict[str, BotInfo] = {}
        self.runs: dict[str, RunRecord] = {}
        self.events: list[EventEnvelope] = []
        self.revisions: dict[str, MemRevision] = {}
        self.sandbox: dict[str, list[dict[str, Any]]] = {}  # bot_id -> loaded sample records
        self.live: dict[str, LiveStats] = {}  # bot_id -> live data shape (tests set this)
        self.save_count = 0
        self._next_event = 1

    def add_bot(
        self, name: str = "ربات", owner_id: str = "owner-1", active_revision_id: str | None = None
    ) -> str:
        bot_id = str(uuid.uuid4())
        self.bots[bot_id] = BotInfo(bot_id, name, owner_id, active_revision_id)
        return bot_id

    def add_revision(
        self,
        bot_id: str,
        spec: BotSpec,
        *,
        requirements: Any = None,
        scenarios: list[Any] | None = None,
        sample_data: list[SeedRecord] | None = None,
        activate: bool = True,
    ) -> str:
        """Seed a revision (active by default) without going through a run."""
        bot = self.bots[bot_id]
        number = 1 + max((r.number for r in self.revisions.values() if r.bot_id == bot_id), default=0)
        rev = MemRevision(
            id=str(uuid.uuid4()),
            bot_id=bot_id,
            number=number,
            parent_id=bot.active_revision_id,
            status="draft",
            spec=spec.model_copy(deep=True),
            requirements=_dump(requirements),
            scenarios=_dump(list(scenarios or [])),
            test_report=None,
            sample_data=list(sample_data or []),
            change_request=None,
        )
        self.revisions[rev.id] = rev
        if activate:
            if bot.active_revision_id is not None:
                self.revisions[bot.active_revision_id].status = "superseded"
            rev.status = "active"
            bot.active_revision_id = rev.id
        return rev.id

    def events_for(self, run_id: str) -> list[EventEnvelope]:
        return [e for e in self.events if e.run_id == run_id]

    async def create_run(
        self, bot_id: str, *, kind: str, state: RunState, base_revision_id: str | None = None
    ) -> RunRecord:
        if bot_id not in self.bots:
            raise BotMissing()
        if any(r.bot_id == bot_id and r.status in ACTIVE_STATUSES for r in self.runs.values()):
            raise ActiveRunExists()
        record = RunRecord(
            id=str(uuid.uuid4()),
            bot_id=bot_id,
            kind=kind,
            phase=state.phase,
            status="running",
            state=state.model_copy(deep=True),
            base_revision_id=base_revision_id,
        )
        self.runs[record.id] = record
        return replace(record, state=record.state.model_copy(deep=True))

    async def load_run(self, run_id: str) -> RunRecord:
        record = self.runs.get(run_id)
        if record is None:
            raise RunNotFound()
        # Round-trip through JSON like the database does, so tests catch unserializable state.
        return replace(record, state=RunState.model_validate_json(record.state.model_dump_json()))

    async def save_run(
        self, run_id: str, *, state: RunState, status: str, result_revision_id: str | None = _UNSET
    ) -> None:
        record = self.runs[run_id]
        record.state = RunState.model_validate_json(state.model_dump_json())
        record.phase = state.phase
        record.status = status
        record.updated_at = datetime.now(UTC)
        if result_revision_id is not _UNSET:
            record.result_revision_id = result_revision_id
        self.save_count += 1

    async def claim_run(self, run_id: str, from_statuses: tuple[str, ...], to_status: str) -> bool:
        record = self.runs.get(run_id)
        if record is None or record.status not in from_statuses:
            return False
        record.status = to_status
        return True

    async def touch_run(self, run_id: str) -> None:
        record = self.runs.get(run_id)
        if record is not None and record.status == "running":
            record.updated_at = datetime.now(UTC)

    async def append_event(self, run_id: str, type_: str, payload: dict[str, Any]) -> EventEnvelope:
        import json

        envelope = EventEnvelope(
            id=self._next_event,
            run_id=run_id,
            ts=datetime.now(UTC),
            type=type_,
            payload=json.loads(json.dumps(payload, ensure_ascii=False)),  # must be JSON-safe
        )
        self._next_event += 1
        self.events.append(envelope)
        return envelope

    async def list_events(self, run_id: str, after_id: int | None = None) -> list[EventEnvelope]:
        return [e for e in self.events_for(run_id) if after_id is None or e.id > after_id]

    async def load_bot(self, bot_id: str) -> BotInfo:
        bot = self.bots.get(bot_id)
        if bot is None:
            raise BotMissing()
        return replace(bot)

    async def load_revision_spec(self, revision_id: str) -> BotSpec:
        return self.revisions[revision_id].spec.model_copy(deep=True)

    async def load_revision(self, revision_id: str) -> RevisionSnapshot:
        r = self.revisions.get(revision_id)
        if r is None:
            raise RepositoryError(code="revision_not_found", message="نسخه پیدا نشد.")
        return _snapshot(r.id, r.number, r.status, r.spec, r.requirements, r.scenarios, r.sample_data)

    async def live_stats(self, bot_id: str) -> LiveStats:
        stats = self.live.get(bot_id) or LiveStats()
        return LiveStats(dict(stats.record_counts), dict(stats.max_confirmed_per_item))

    async def create_draft_revision(
        self,
        bot_id: str,
        *,
        spec: BotSpec,
        requirements: BaseModel | None,
        scenarios: list[Any],
        test_report: BaseModel | None,
        sample_data: list[SeedRecord],
        change_request: str | None,
        parent_id: str | None,
        patch: list[Any] | None = None,
        superseded: list[Any] | None = None,
    ) -> DraftRevision:
        if bot_id not in self.bots:
            raise BotMissing()
        number = 1 + max((r.number for r in self.revisions.values() if r.bot_id == bot_id), default=0)
        rev = MemRevision(
            id=str(uuid.uuid4()),
            bot_id=bot_id,
            number=number,
            parent_id=parent_id,
            status="draft",
            spec=spec.model_copy(deep=True),
            requirements=_dump(requirements),
            scenarios=_dump(scenarios),
            test_report=_dump(test_report),
            sample_data=list(sample_data),
            change_request=change_request,
            patch=_dump(patch) if patch is not None else None,
            superseded=_dump(superseded) if superseded is not None else None,
        )
        self.revisions[rev.id] = rev
        return DraftRevision(rev.id, number)

    async def load_sample_data(self, revision_id: str) -> int:
        rev = self.revisions[revision_id]
        now = datetime.now(UTC)
        loaded: list[dict[str, Any]] = []
        for seed in rev.sample_data:
            resource = rev.spec.resource(seed.collection)
            if resource is None:
                raise SampleDataInvalid(f"منبع «{seed.collection}» در مشخصات ربات وجود ندارد.")
            dt_keys = {f.key for f in resource.fields if f.type == FieldType.datetime}
            values = {
                kv.key: resolve_relative(kv.value, now) if kv.key in dt_keys else kv.value
                for kv in seed.values
            }
            cleaned, errors = validate_record(resource.fields, values)
            if errors:
                raise SampleDataInvalid("داده‌های نمونه نامعتبر است: " + " ".join(errors))
            loaded.append({"collection": seed.collection, "data": cleaned})
        self.sandbox[rev.bot_id] = loaded
        return len(loaded)

    async def activate(self, revision_id: str) -> int:
        rev = self.revisions.get(revision_id)
        if rev is None:
            raise ActivationRefused("نسخه پیدا نشد.", code="revision_not_found")
        bot = self.bots[rev.bot_id]
        if rev.status != "draft":
            raise ActivationRefused("فقط پیش‌نویس را می‌توان فعال کرد.", code="invalid_revision_state")
        if rev.parent_id != bot.active_revision_id:
            raise ActivationRefused(revisions.StaleBase.message, code="stale_base")
        if revisions.report_has_failures(rev.test_report):
            raise ActivationRefused(revisions.TestsFailing.message, code="tests_failing")
        if bot.active_revision_id is not None:
            self.revisions[bot.active_revision_id].status = "superseded"
        rev.status = "active"
        bot.active_revision_id = rev.id
        return rev.number

    async def reject_revision(self, revision_id: str) -> None:
        rev = self.revisions.get(revision_id)
        if rev is not None and rev.status == "draft":
            rev.status = "rejected"
