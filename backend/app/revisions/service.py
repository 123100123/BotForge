"""Revisions: create drafts, activate (and roll back), load sample data into the sandbox.

``activate`` is the only place a revision becomes live. It runs inside the caller's transaction
under the bot's advisory lock; the caller commits.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BotSpec, FieldType
from app.botspec.records import validate_record
from app.db.models import Bot, RecordRow, Revision, SessionRow
from app.runtime.pg_store import PgStore, advisory_lock
from app.runtime.store import Record
from app.testing.scenario import SeedRecord, resolve_relative


class RevisionError(Exception):
    """Domain error. ``code`` is stable and machine-readable; ``message`` is Persian."""

    code = "revision_error"
    message = "خطایی در نسخه رخ داد."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or type(self).message
        super().__init__(self.message)


class BotNotFound(RevisionError):
    code = "bot_not_found"
    message = "ربات پیدا نشد."


class RevisionNotFound(RevisionError):
    code = "revision_not_found"
    message = "نسخه پیدا نشد."


class StaleBase(RevisionError):
    code = "stale_base"
    message = "این تغییر بر پایهٔ نسخه‌ای قدیمی ساخته شده است. لطفاً درخواست تغییر را دوباره شروع کنید."


class TestsFailing(RevisionError):
    __test__ = False  # not a pytest test class
    code = "tests_failing"
    message = "آزمون‌های این نسخه ناموفق بوده‌اند و نسخه قابل فعال‌سازی نیست."


class InvalidRevisionState(RevisionError):
    code = "invalid_revision_state"
    message = "وضعیت این نسخه اجازهٔ این کار را نمی‌دهد."


class InvalidSampleData(RevisionError):
    code = "invalid_sample_data"
    message = "داده‌های نمونه نامعتبر است."


def _dump(value: Any) -> Any:
    """JSON-safe form of a pydantic model (or a list of them); other values pass through."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value


async def create_draft(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    spec: BotSpec | dict[str, Any],
    requirements: BaseModel | dict[str, Any] | None = None,
    patch: list[Any] | None = None,
    change_request: str | None = None,
    scenarios: list[Any] | None = None,
    superseded: list[Any] | None = None,
    test_report: BaseModel | dict[str, Any] | None = None,
    sample_data: list[Any] | None = None,
    parent_id: uuid.UUID | None = None,
) -> Revision:
    """Insert a draft revision numbered ``previous max + 1`` for the bot."""
    await advisory_lock(session, bot_id)  # serializes numbering per bot
    if await session.get(Bot, bot_id) is None:
        raise BotNotFound()
    last = (
        await session.execute(select(func.max(Revision.number)).where(Revision.bot_id == bot_id))
    ).scalar_one()
    revision = Revision(
        bot_id=bot_id,
        number=(last or 0) + 1,
        parent_id=parent_id,
        status="draft",
        spec=_dump(spec),
        requirements=_dump(requirements),
        patch=_dump(patch),
        change_request=change_request,
        scenarios=_dump(scenarios),
        superseded=_dump(superseded),
        test_report=_dump(test_report),
        sample_data=_dump(sample_data),
    )
    session.add(revision)
    await session.flush()
    return revision


def report_has_failures(report: dict[str, Any] | None) -> bool:
    if not report:
        return False
    if (report.get("failed") or 0) > 0:
        return True
    return any(not r.get("passed", True) for r in report.get("results") or [])


def _status_after_activation(bot: Bot) -> str:
    if bot.status == "paused":
        return "paused"
    return "live" if bot.tg_token_enc else "draft"


async def activate(session: AsyncSession, revision_id: uuid.UUID, *, rollback: bool = False) -> Revision:
    """Make ``revision_id`` the bot's active revision (roadmap, Modification Workflow item 9).

    Normal activation takes a draft whose ``parent_id`` equals the bot's current
    ``active_revision_id`` (``None`` for the first revision). ``rollback=True`` re-activates a
    previously superseded revision without the parent check.
    """
    probe = await session.get(Revision, revision_id)
    if probe is None:
        raise RevisionNotFound()
    bot_id = probe.bot_id
    await advisory_lock(session, bot_id)

    revision = (
        await session.execute(
            select(Revision).where(Revision.id == revision_id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    bot = (
        await session.execute(select(Bot).where(Bot.id == bot_id).execution_options(populate_existing=True))
    ).scalar_one()

    if rollback:
        if revision.status != "superseded":
            raise InvalidRevisionState("فقط نسخهٔ قدیمی‌تر را می‌توان بازگرداند.")
    else:
        if revision.status != "draft":
            raise InvalidRevisionState("فقط پیش‌نویس را می‌توان فعال کرد.")
        if revision.parent_id != bot.active_revision_id:
            raise StaleBase()
    if report_has_failures(revision.test_report):
        raise TestsFailing()

    if bot.active_revision_id is not None and bot.active_revision_id != revision.id:
        previous = await session.get(Revision, bot.active_revision_id)
        if previous is not None:
            previous.status = "superseded"

    revision.status = "active"
    revision.activated_at = datetime.now(UTC)
    bot.active_revision_id = revision.id
    bot.status = _status_after_activation(bot)
    await session.execute(delete(SessionRow).where(SessionRow.bot_id == bot_id, SessionRow.env == "live"))
    await session.flush()
    return revision


async def load_sample_data(
    session: AsyncSession, bot_id: uuid.UUID, revision: Revision, now: datetime
) -> list[Record]:
    """Replace the bot's sandbox records and sessions with ``revision.sample_data``.

    Relative datetimes ("+48h") resolve against ``now``. Values go through ``validate_record``
    with the resource's fields, so the sandbox holds the same canonical forms as live data.
    """
    spec = BotSpec.model_validate(revision.spec)
    resources = {r.key: r for r in spec.resources}
    prepared: list[tuple[str, dict[str, Any]]] = []
    for raw in revision.sample_data or []:
        seed = SeedRecord.model_validate(raw)
        resource = resources.get(seed.collection)
        if resource is None:
            raise InvalidSampleData(f"منبع «{seed.collection}» در مشخصات ربات وجود ندارد.")
        datetime_keys = {f.key for f in resource.fields if f.type == FieldType.datetime}
        values = {
            kv.key: resolve_relative(kv.value, now) if kv.key in datetime_keys else kv.value
            for kv in seed.values
        }
        cleaned, errors = validate_record(resource.fields, values)
        if errors:
            raise InvalidSampleData("داده‌های نمونه نامعتبر است: " + " ".join(errors))
        prepared.append((seed.collection, cleaned))

    await session.execute(delete(RecordRow).where(RecordRow.bot_id == bot_id, RecordRow.env == "sandbox"))
    await session.execute(delete(SessionRow).where(SessionRow.bot_id == bot_id, SessionRow.env == "sandbox"))
    store = PgStore(session, bot_id, "sandbox", "owner")
    return [await store.create_record(collection, data, now=now) for collection, data in prepared]
