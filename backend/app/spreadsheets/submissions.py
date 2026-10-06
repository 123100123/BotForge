"""Who sent today's report, and the Overview KPIs of analysis runs.

``who_submitted`` compares the bot's team (staff and managers, minus the owner, who is the one asking)
with the runs of a profile on one Tehran day: a member counts as having submitted when a run of the
profile with their actor id as ``submitted_by`` exists that day (a failed read does not count).
"""

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.service import module_enabled, require_capability
from app.db.models import AnalysisProfileRow, AnalysisRunRow, Bot, BotModuleRow
from app.reporting.periods import period_bounds
from app.roles.service import LIVE, list_members
from app.runtime.formatting import get_tz
from app.schemas.business import MetricValue

log = logging.getLogger(__name__)

MODULE_ID = "spreadsheet_intelligence"
OVERVIEW_PERIOD = "7d"  # overview sources are not told the period the page asks for
TEHRAN = "Asia/Tehran"


def day_bounds(day: date, tz: str = TEHRAN) -> tuple[datetime, datetime]:
    """[start, end) of the local ``day`` as UTC instants."""
    zone = get_tz(tz)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def today_tehran(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(get_tz(TEHRAN)).date()


async def who_submitted(
    session: AsyncSession, bot: Bot, profile_row: AnalysisProfileRow, day: date
) -> dict[str, Any]:
    """``{date, submitted: [{actor_id, display_name, run_id, at}], missing: [{actor_id, display_name}]}``
    for ``profile_row`` on the Tehran day ``day``; one entry per member (their latest run that day)."""
    since, until = day_bounds(day)
    members = [
        m
        for m in await list_members(session, bot.id, LIVE, bot.owner_actor_id)
        if m.actor_id != bot.owner_actor_id
    ]
    stmt = (
        select(AnalysisRunRow.id, AnalysisRunRow.submitted_by, AnalysisRunRow.created_at)
        .where(
            AnalysisRunRow.bot_id == bot.id,
            AnalysisRunRow.profile_id == profile_row.id,
            AnalysisRunRow.submitted_by.is_not(None),
            AnalysisRunRow.status != "failed",
            AnalysisRunRow.created_at >= since,
            AnalysisRunRow.created_at < until,
        )
        .order_by(AnalysisRunRow.created_at, AnalysisRunRow.id)
    )
    latest: dict[str, tuple[uuid.UUID, datetime]] = {}
    for run_id, actor_id, at in (await session.execute(stmt)).all():
        latest[actor_id] = (run_id, at)  # ascending order: the last one wins
    submitted: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for member in members:
        found = latest.get(member.actor_id)
        if found is None:
            missing.append({"actor_id": member.actor_id, "display_name": member.display_name})
        else:
            submitted.append(
                {
                    "actor_id": member.actor_id,
                    "display_name": member.display_name,
                    "run_id": found[0],
                    "at": found[1],
                }
            )
    return {"date": day.isoformat(), "submitted": submitted, "missing": missing}


async def overview_kpis(bot_id: uuid.UUID, session: AsyncSession) -> list[MetricValue]:
    """KPIs ``reports_uploaded`` and ``anomaly_count`` over the last seven days; none unless the
    spreadsheet intelligence module is enabled for the bot. An optional KPI never breaks the Overview:
    any failure is logged and gives no KPIs."""
    try:
        return await _overview_kpis(bot_id, session)
    except Exception:
        log.exception("bot %s: analysis KPIs for the overview failed", bot_id)
        return []


async def _overview_kpis(bot_id: uuid.UUID, session: AsyncSession) -> list[MetricValue]:
    row = await session.get(BotModuleRow, (bot_id, MODULE_ID))
    if not module_enabled(require_capability(MODULE_ID), {} if row is None else {MODULE_ID: row}):
        return []
    since = period_bounds(OVERVIEW_PERIOD, datetime.now(UTC))[0]
    stmt = select(AnalysisRunRow.result).where(
        AnalysisRunRow.bot_id == bot_id, AnalysisRunRow.created_at >= since
    )
    results = list((await session.execute(stmt)).scalars())
    anomalies = sum(len((r or {}).get("anomalies", [])) for r in results)
    return [
        MetricValue(
            id="reports_uploaded", label="گزارش‌های بارگذاری‌شده", kind="scalar", value=float(len(results))
        ),
        MetricValue(id="anomaly_count", label="موارد غیرعادی", kind="scalar", value=float(anomalies)),
    ]
