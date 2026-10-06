"""Spreadsheet analysis: profiles, runs and who submitted today's report (roadmap: Spreadsheet
Intelligence; models in ``schemas/business.py``).

  GET   /bots/{bot_id}/analysis/profiles                      list[AnalysisProfileOut]
  POST  /bots/{bot_id}/analysis/profiles                      AnalysisProfileCreateIn -> AnalysisProfileOut
                                                              (201; one strong LLM call; 404 unknown
                                                              upload; 503 ``llm_unavailable``; 429
                                                              ``analysis_daily_cap`` once the owner's
                                                              daily model budget is used up)
  PATCH /bots/{bot_id}/analysis/profiles/{profile_id}         AnalysisProfileUpdateIn -> AnalysisProfileOut
  POST  /bots/{bot_id}/analysis/profiles/{profile_id}/run     AnalysisRunIn -> AnalysisRunOut (200 even
                                                              when the layout changed: that is a result;
                                                              ``narrative`` is skipped once the daily
                                                              model budget is used up)
  GET   /bots/{bot_id}/analysis/runs?profile_id=              the latest 50 runs
  GET   /bots/{bot_id}/analysis/profiles/{profile_id}/submissions?date=YYYY-MM-DD   who submitted

Owner only (``get_owned_bot``). Creating a profile from the web works whether or not the
``spreadsheet_intelligence`` module is enabled: the Capability Center toggle only governs Telegram
ingestion and the Overview KPIs registered at the bottom of this module.
"""

import logging
import uuid
from datetime import date as Date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import LLMClient, make_llm
from app.api.deps import get_owned_bot
from app.config import get_settings
from app.db.models import AnalysisProfileRow, AnalysisRunRow, Bot
from app.db.session import get_session
from app.reporting.service import register_overview_source
from app.schemas.business import (
    AnalysisProfileCreateIn,
    AnalysisProfileOut,
    AnalysisProfileUpdateIn,
    AnalysisRunIn,
    AnalysisRunOut,
)
from app.spreadsheets import profile as profiles
from app.spreadsheets import run as runs
from app.spreadsheets import service
from app.spreadsheets.submissions import overview_kpis, today_tehran, who_submitted

log = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])

PROFILE_NOT_FOUND = {"code": "profile_not_found", "message": "پروفایل تحلیل پیدا نشد."}
UPLOAD_NOT_FOUND = {"code": "upload_not_found", "message": "فایل پیدا نشد."}


class SubmittedOut(BaseModel):
    actor_id: str
    display_name: str | None
    run_id: uuid.UUID
    at: AwareDatetime


class MissingOut(BaseModel):
    actor_id: str
    display_name: str | None


class SubmissionsOut(BaseModel):
    date: str
    submitted: list[SubmittedOut]
    missing: list[MissingOut]


def get_llm_optional() -> LLMClient | None:
    """The configured LLM client, or None when no model is reachable (no API key for the Anthropic
    provider). Tests override this dependency with a ``FakeLLM``."""
    settings = get_settings()
    if settings.LLM_PROVIDER == "anthropic" and not settings.ANTHROPIC_API_KEY:
        return None
    return make_llm()


def get_llm(llm: LLMClient | None = Depends(get_llm_optional)) -> LLMClient:
    if llm is None:
        raise HTTPException(
            503, detail={"code": "llm_unavailable", "message": profiles.LLM_UNAVAILABLE_MESSAGE}
        )
    return llm


def _profile_error(exc: profiles.ProfileError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message_fa})


async def _owned_profile(session: AsyncSession, bot: Bot, profile_id: uuid.UUID) -> AnalysisProfileRow:
    stmt = select(AnalysisProfileRow).where(
        AnalysisProfileRow.id == profile_id, AnalysisProfileRow.bot_id == bot.id
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail=PROFILE_NOT_FOUND)
    return row


@router.get("/bots/{bot_id}/analysis/profiles", response_model=list[AnalysisProfileOut])
async def list_profiles(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> list[AnalysisProfileOut]:
    counts = (
        select(AnalysisRunRow.profile_id, func.count().label("n"))
        .where(AnalysisRunRow.bot_id == bot.id)
        .group_by(AnalysisRunRow.profile_id)
        .subquery()
    )
    stmt = (
        select(AnalysisProfileRow, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.profile_id == AnalysisProfileRow.id)
        .where(AnalysisProfileRow.bot_id == bot.id)
        .order_by(AnalysisProfileRow.created_at.desc(), AnalysisProfileRow.id)
    )
    return [profiles.profile_out(row, n) for row, n in (await session.execute(stmt)).all()]


@router.post("/bots/{bot_id}/analysis/profiles", response_model=AnalysisProfileOut, status_code=201)
async def create_profile(
    body: AnalysisProfileCreateIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> AnalysisProfileOut:
    upload = await service.get_upload(session, bot.id, body.upload_id)
    if upload is None:
        raise HTTPException(404, detail=UPLOAD_NOT_FOUND)
    try:
        out = await profiles.create_profile(
            session, bot, llm, upload, name=body.name, daily_report=body.daily_report
        )
    except profiles.ProfileError as exc:
        raise _profile_error(exc) from None
    await session.commit()
    return out


@router.patch("/bots/{bot_id}/analysis/profiles/{profile_id}", response_model=AnalysisProfileOut)
async def update_profile(
    profile_id: uuid.UUID,
    body: AnalysisProfileUpdateIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> AnalysisProfileOut:
    row = await _owned_profile(session, bot, profile_id)
    out = await profiles.update_profile(session, bot, row, body)
    await session.commit()
    return out


@router.post("/bots/{bot_id}/analysis/profiles/{profile_id}/run", response_model=AnalysisRunOut)
async def run_profile(
    profile_id: uuid.UUID,
    body: AnalysisRunIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    llm: LLMClient | None = Depends(get_llm_optional),
) -> AnalysisRunOut:
    row = await _owned_profile(session, bot, profile_id)
    upload = await service.get_upload(session, bot.id, body.upload_id)
    if upload is None:
        raise HTTPException(404, detail=UPLOAD_NOT_FOUND)
    out = await runs.run_profile(
        session, bot, row, upload, submitted_by=None, narrative=body.narrative, llm=llm
    )
    await session.commit()
    return out


@router.get("/bots/{bot_id}/analysis/runs", response_model=list[AnalysisRunOut])
async def list_runs(
    profile_id: uuid.UUID | None = Query(None),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> list[AnalysisRunOut]:
    return await runs.list_runs(session, bot.id, profile_id)


@router.get("/bots/{bot_id}/analysis/profiles/{profile_id}/submissions", response_model=SubmissionsOut)
async def read_submissions(
    profile_id: uuid.UUID,
    day: Date | None = Query(None, alias="date"),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await _owned_profile(session, bot, profile_id)
    return await who_submitted(session, bot, row, day or today_tehran())


# Registered at import time: the Overview shows these KPIs while the module is enabled.
register_overview_source(overview_kpis)
