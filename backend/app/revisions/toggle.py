"""Capability toggles as revisions (W1-REG): ops -> validated, tested, ACTIVE revision.

``apply_capability_ops`` is the only way the Capability Center changes a bot's spec. It never
mutates an existing revision; it runs the ordinary revision pipeline:

  advisory lock -> active spec -> ``apply_patch`` -> ``check_compat`` against live record counts
  -> scenarios (carried minus superseded, plus freshly derived) -> ``run_scenarios``
  -> ``create_draft(parent=active)`` -> ``activate``

Scenario rules: derived scenarios are regenerated from the new spec (as the agent does);
carried acceptance scenarios are kept. Any carried scenario that touches a capability key being
disabled, removed or restricted to a narrower audience moves to ``superseded`` with a Persian
reason, otherwise stale scenarios would block every toggle. Failing tests never activate.

The caller owns the transaction (commit on success, rollback on error).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.compat import check_compat
from app.botspec.models import BotSpec
from app.botspec.patch import PatchError, PatchOp, apply_patch
from app.botspec.validate import SpecIssue
from app.db.models import Bot, RecordRow, Revision
from app.revisions.service import RevisionError, TestsFailing, activate, create_draft, report_has_failures
from app.runtime.pg_store import advisory_lock
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario, TestReport

AUDIENCE_RANK = {"everyone": 0, "staff": 1, "managers": 2}


class CapabilityRevisionError(RevisionError):
    """A RevisionError that may carry structured ``details`` for the API error envelope."""

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        super().__init__(message)
        self.details = details


class NoActiveRevision(CapabilityRevisionError):
    code = "no_active_revision"
    message = "ابتدا ربات را با دستیار بسازید"


class CompatError(CapabilityRevisionError):
    code = "compat_error"
    message = "این تغییر با داده‌های فعلی ربات سازگار نیست."


class InvalidCapabilitySpec(CapabilityRevisionError):
    code = "invalid_spec"
    message = "این تغییر ربات را نامعتبر می‌کند و اعمال نشد."


class CapabilityTestsFailing(TestsFailing, CapabilityRevisionError):
    """``tests_failing`` with the failing scenarios in ``details``."""

    __test__ = False


def _issues(issues: list[SpecIssue]) -> list[dict[str, Any]]:
    return [i.model_dump() for i in issues]


async def live_record_counts(
    session: AsyncSession, bot_id: uuid.UUID
) -> tuple[dict[str, int], dict[str, int]]:
    """(record counts per collection, highest confirmed count on one item per collection), live env.

    A copy of ``agent.repository.SqlRepository.live_stats`` (the agent package is not imported here).
    """
    live = (RecordRow.bot_id == bot_id, RecordRow.env == "live")
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
    return (
        {str(c): int(n) for c, n in counts.all()},
        {str(c): int(n) for c, n in confirmed.all()},
    )


async def lock_and_refresh(session: AsyncSession, bot: Bot) -> None:
    """Take the bot's advisory lock and re-read the bot row, so the active revision is current."""
    await advisory_lock(session, bot.id)
    await session.refresh(bot)


async def active_revision(session: AsyncSession, bot: Bot) -> Revision | None:
    if bot.active_revision_id is None:
        return None
    return await session.get(Revision, bot.active_revision_id)


def patch_spec(old: BotSpec, ops: list[PatchOp]) -> BotSpec:
    """``apply_patch`` with PatchError mapped to the structured ``invalid_spec`` error."""
    try:
        return apply_patch(old, ops)
    except PatchError as exc:
        raise InvalidCapabilitySpec(details=exc.to_dict()) from None


async def preview_ops(
    session: AsyncSession, bot: Bot, old: BotSpec, ops: list[PatchOp]
) -> tuple[BotSpec, list[str]]:
    """The patched spec and the compat warning messages; raises on invalid spec or compat errors.
    Writes nothing."""
    new = patch_spec(old, ops)
    counts, max_confirmed = await live_record_counts(session, bot.id)
    issues = check_compat(old, new, counts, max_confirmed_per_item=max_confirmed)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise CompatError(
            "این تغییر با داده‌های فعلی ربات سازگار نیست: " + " ".join(i.message for i in errors),
            details={"issues": _issues(errors)},
        )
    return new, [i.message for i in issues if i.severity == "warning"]


def affected_keys(old: BotSpec, new: BotSpec) -> dict[str, str]:
    """Capability keys whose users lose access in ``new`` -> Persian reason."""
    out: dict[str, str] = {}
    new_caps = {c.key: c for c in new.capabilities}
    for oc in old.capabilities:
        nc = new_caps.get(oc.key)
        if nc is None:
            out[oc.key] = f"قابلیت «{oc.title}» حذف شد."
        elif oc.enabled and not nc.enabled:
            out[oc.key] = f"قابلیت «{oc.title}» غیرفعال شد."
        elif AUDIENCE_RANK[nc.audience] > AUDIENCE_RANK[oc.audience]:
            out[oc.key] = f"دسترسی به «{oc.title}» محدود شد."
    return out


def _touched_keys(scenario: Scenario) -> set[str]:
    return set(scenario.capability_keys) | {s.capability for s in scenario.steps if s.capability is not None}


def plan_scenarios(
    old_raw: list[Any] | None, old: BotSpec, new: BotSpec
) -> tuple[list[Scenario], list[dict[str, Any]]]:
    """(scenarios for the new revision, superseded entries ``{scenario, reason}``)."""
    affected = affected_keys(old, new)
    carried: list[Scenario] = []
    superseded: list[dict[str, Any]] = []
    for raw in old_raw or []:
        try:
            scenario = Scenario.model_validate(raw)
        except ValidationError:
            superseded.append({"scenario": raw, "reason": "سناریو با قالب فعلی آزمون‌ها خوانا نیست."})
            continue
        hit = sorted(_touched_keys(scenario) & affected.keys())
        if hit:
            superseded.append({"scenario": scenario.model_dump(mode="json"), "reason": affected[hit[0]]})
        elif scenario.source != "derived":
            carried.append(scenario)  # derived ones are regenerated below
    derived = derive_scenarios(new)
    taken = {s.id for s in derived}
    return [*derived, *(s for s in carried if s.id not in taken)], superseded


def failure_summary(report: TestReport) -> str:
    failed = [r for r in report.results if not r.passed]
    head = f"{report.failed} آزمون از {report.total} آزمون نسخهٔ جدید ناموفق شد؛ تغییر اعمال نشد."
    if not failed:
        return head
    first = failed[0]
    step = next((s for s in first.steps if not s.passed), None)
    detail = f" نمونه: {first.scenario_id}"
    if step is not None and step.message:
        detail += f" ({step.message})"
    return head + detail


async def apply_capability_ops(
    session: AsyncSession,
    bot: Bot,
    ops: list[PatchOp],
    *,
    change_request: str,
    enabled_keys_changed: set[str] | None = None,
) -> Revision:
    """Turn ``ops`` into a new ACTIVE revision (see the module docstring). Raises RevisionError
    subclasses: ``no_active_revision``, ``invalid_spec``, ``compat_error``, ``tests_failing``
    (and ``stale_base`` from ``activate`` should the base move, which the lock prevents).

    ``enabled_keys_changed`` is informational (logged into nothing): the affected keys are always
    recomputed from the old and new spec so a caller cannot skip superseding.
    """
    del enabled_keys_changed
    await lock_and_refresh(session, bot)
    base = await active_revision(session, bot)
    if base is None:
        raise NoActiveRevision()
    old = BotSpec.model_validate(base.spec)
    new, _warnings = await preview_ops(session, bot, old, ops)

    scenarios, superseded = plan_scenarios(base.scenarios, old, new)
    report = await run_scenarios(new, scenarios)
    report_dict = report.model_dump(mode="json")
    if report_has_failures(report_dict):
        failing = [r.scenario_id for r in report.results if not r.passed]
        raise CapabilityTestsFailing(failure_summary(report), details={"failed_scenarios": failing})

    draft = await create_draft(
        session,
        bot.id,
        spec=new,
        requirements=base.requirements,
        patch=ops,
        change_request=change_request,
        scenarios=scenarios,
        superseded=superseded,
        test_report=report,
        sample_data=base.sample_data,
        parent_id=base.id,
    )
    return await activate(session, draft.id)
