"""Reports API: the Overview and per-capability reports of the ACTIVE revision.

Read-only. Records are read through ``PgStore`` bound to the requested environment (``live`` by
default); the metrics come from ``app.reporting`` (one deterministic engine, no LLM). A bot with no
active revision gets an empty Overview; the frontend shows its empty state.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.botspec.models import BotSpec
from app.db.models import Bot, Revision
from app.db.session import get_session
from app.reporting import service
from app.runtime.pg_store import PgStore
from app.schemas.business import CapabilityReportOut, OverviewOut, Period

router = APIRouter(tags=["reports"])

Env = Literal["live", "sandbox"]


async def _active_spec(session: AsyncSession, bot: Bot) -> BotSpec | None:
    revision = (
        await session.get(Revision, bot.active_revision_id) if bot.active_revision_id is not None else None
    )
    if revision is None or revision.bot_id != bot.id:  # the FK does not tie the revision to this bot
        return None
    return BotSpec.model_validate(revision.spec)


@router.get("/bots/{bot_id}/reports/overview", response_model=OverviewOut)
async def get_overview(
    period: Period = Query("7d"),
    env: Env = Query("live"),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> OverviewOut:
    spec = await _active_spec(session, bot)
    if spec is None:
        return OverviewOut(period=period, kpis=[], activity=[], enabled_capabilities=[])
    store = PgStore(session, bot.id, env, bot.owner_actor_id)
    extra = await service.collect_overview_sources(bot.id, session)
    return await service.overview(store, spec, period, datetime.now(UTC), extra_kpis=extra)


@router.get("/bots/{bot_id}/reports/{capability_key}", response_model=CapabilityReportOut)
async def get_capability_report(
    capability_key: str,
    period: Period = Query("7d"),
    env: Env = Query("live"),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> CapabilityReportOut:
    spec = await _active_spec(session, bot)
    cap = spec.capability(capability_key) if spec is not None else None
    if spec is None or cap is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "capability_not_found", "message": "این قابلیت پیدا نشد."},
        )
    store = PgStore(session, bot.id, env, bot.owner_actor_id)
    return await service.capability_report(store, spec, cap, period, datetime.now(UTC))
