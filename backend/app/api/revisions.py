"""Revision history (read side), rollback, and on-demand test runs.

Creating and approving revisions belongs to the agent; here the owner lists and inspects revisions,
rolls back to an older one (``activate(..., rollback=True)``) and re-runs a revision's stored
scenarios against its spec.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot, get_owned_revision
from app.botspec.diff import SpecChange, diff_specs
from app.botspec.models import BotSpec
from app.db.models import Bot, Revision
from app.db.session import get_session
from app.revisions import service
from app.testing.runner import run_scenarios
from app.testing.scenario import Scenario, TestReport

log = logging.getLogger(__name__)

router = APIRouter(tags=["revisions"])

# Domain errors of the revisions service -> HTTP status (the body keeps the service's code/message).
_STATUS: dict[type[service.RevisionError], int] = {
    service.RevisionNotFound: 404,
    service.BotNotFound: 404,
    service.StaleBase: 409,
    service.TestsFailing: 409,
    service.InvalidRevisionState: 409,
    service.InvalidSampleData: 400,
}


class TestCounts(BaseModel):
    __test__ = False  # not a pytest test class

    total: int
    passed: int
    failed: int


class RevisionSummary(BaseModel):
    id: uuid.UUID
    number: int
    status: str
    change_request: str | None
    created_at: datetime
    activated_at: datetime | None
    tests: TestCounts | None


class RevisionDetail(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    number: int
    status: str
    parent_id: uuid.UUID | None
    change_request: str | None
    created_at: datetime
    activated_at: datetime | None
    spec: dict[str, Any]
    requirements: dict[str, Any] | None
    scenarios: list[Any] | None
    superseded: list[Any] | None
    test_report: dict[str, Any] | None
    diff: list[SpecChange]


def _counts(report: dict[str, Any] | None) -> TestCounts | None:
    if not report:
        return None
    try:
        return TestCounts(total=report["total"], passed=report["passed"], failed=report["failed"])
    except (KeyError, ValidationError):
        return None


def _summary(revision: Revision) -> RevisionSummary:
    return RevisionSummary(
        id=revision.id,
        number=revision.number,
        status=revision.status,
        change_request=revision.change_request,
        created_at=revision.created_at,
        activated_at=revision.activated_at,
        tests=_counts(revision.test_report),
    )


def _domain_error(exc: service.RevisionError) -> HTTPException:
    return HTTPException(_STATUS.get(type(exc), 400), detail={"code": exc.code, "message": exc.message})


async def _diff_against_parent(session: AsyncSession, revision: Revision) -> list[SpecChange]:
    if revision.parent_id is None:
        return []
    parent = await session.get(Revision, revision.parent_id)
    if parent is None or parent.bot_id != revision.bot_id:
        return []
    try:
        return diff_specs(BotSpec.model_validate(parent.spec), BotSpec.model_validate(revision.spec))
    except ValidationError:
        log.warning("revision %s: spec could not be diffed against its parent", revision.id)
        return []


@router.get("/bots/{bot_id}/revisions", response_model=list[RevisionSummary])
async def list_revisions(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> list[RevisionSummary]:
    stmt = select(Revision).where(Revision.bot_id == bot.id).order_by(Revision.number.desc())
    return [_summary(r) for r in (await session.execute(stmt)).scalars()]


@router.get("/revisions/{revision_id}", response_model=RevisionDetail)
async def read_revision(
    revision: Revision = Depends(get_owned_revision), session: AsyncSession = Depends(get_session)
) -> RevisionDetail:
    return RevisionDetail(
        id=revision.id,
        bot_id=revision.bot_id,
        number=revision.number,
        status=revision.status,
        parent_id=revision.parent_id,
        change_request=revision.change_request,
        created_at=revision.created_at,
        activated_at=revision.activated_at,
        spec=revision.spec,
        requirements=revision.requirements,
        scenarios=revision.scenarios,
        superseded=revision.superseded,
        test_report=revision.test_report,
        diff=await _diff_against_parent(session, revision),
    )


@router.post("/revisions/{revision_id}/activate", response_model=RevisionSummary)
async def rollback_to_revision(
    revision: Revision = Depends(get_owned_revision), session: AsyncSession = Depends(get_session)
) -> RevisionSummary:
    """Re-activate an older (superseded) revision. New drafts are approved through the agent run."""
    try:
        activated = await service.activate(session, revision.id, rollback=True)
    except service.RevisionError as exc:
        await session.rollback()
        raise _domain_error(exc) from None
    await session.commit()
    return _summary(activated)


@router.post("/revisions/{revision_id}/tests/run", response_model=TestReport)
async def run_tests(
    revision: Revision = Depends(get_owned_revision), session: AsyncSession = Depends(get_session)
) -> TestReport:
    """Re-run the revision's stored scenarios on a fresh in-memory store and store the report."""
    if not revision.scenarios:
        raise HTTPException(
            409, detail={"code": "no_scenarios", "message": "برای این نسخه سناریوی آزمون ذخیره نشده است."}
        )
    spec = BotSpec.model_validate(revision.spec)
    scenarios = [Scenario.model_validate(s) for s in revision.scenarios]
    report = await run_scenarios(spec, scenarios)
    revision.test_report = report.model_dump(mode="json")
    await session.commit()
    return report
