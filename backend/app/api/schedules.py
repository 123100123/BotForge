"""Scheduled-report configuration (roadmap: Scheduled Reports).

  GET /bots/{bot_id}/schedules   list[ScheduleOut]: the saved schedules, or the defaults (daily 18:00,
                                 weekly Friday 17:00) when none were saved
  PUT /bots/{bot_id}/schedules   SchedulesIn -> list[ScheduleOut]: replaces the list

The list is the ``schedules`` key of ``bot_modules.config`` for module ``scheduled_reports`` (the
module's enabled flag is the Capability Center's and is left alone). Delivery is the
``scheduled_reports`` generator's job. ``weekday`` is Python's (Monday = 0 ... Sunday = 6). Only the
bot's owner reaches this (``get_owned_bot``).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.capabilities import get_capability
from app.db.models import Bot, BotModuleRow
from app.db.session import get_session
from app.notifications.generators.scheduled_reports import ID_PATTERN, MODULE, effective_schedules
from app.schemas.business import ScheduleOut, SchedulesIn

router = APIRouter(tags=["schedules"])


def _invalid(message: str) -> HTTPException:
    return HTTPException(422, detail={"code": "invalid_schedules", "message": message})


def _default_enabled() -> bool:
    cap = get_capability(MODULE)
    return cap is not None and cap.default_enabled


def _validate(schedules: list[ScheduleOut]) -> None:
    ids = [s.id for s in schedules]
    if len(set(ids)) != len(ids):
        raise _invalid("شناسهٔ زمان‌بندی‌ها باید یکتا باشد.")
    for schedule in schedules:
        if not ID_PATTERN.fullmatch(schedule.id):
            raise _invalid("شناسهٔ زمان‌بندی نامعتبر است.")
        if schedule.kind == "weekly_summary" and schedule.weekday is None:
            raise _invalid("برای گزارش هفتگی روز هفته را مشخص کنید.")


@router.get("/bots/{bot_id}/schedules", response_model=list[ScheduleOut])
async def list_schedules(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> list[ScheduleOut]:
    row = await session.get(BotModuleRow, (bot.id, MODULE))
    enabled = row.enabled if row is not None else _default_enabled()
    return effective_schedules(row.config if row is not None else None, enabled)


@router.put("/bots/{bot_id}/schedules", response_model=list[ScheduleOut])
async def replace_schedules(
    body: SchedulesIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> list[ScheduleOut]:
    _validate(body.schedules)
    row = await session.get(BotModuleRow, (bot.id, MODULE))
    config = {
        **(row.config if row is not None else {}),
        "schedules": [s.model_dump() for s in body.schedules],
    }
    stmt = pg_insert(BotModuleRow).values(
        bot_id=bot.id, module=MODULE, enabled=_default_enabled(), config=config
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[BotModuleRow.bot_id, BotModuleRow.module], set_={"config": config}
        )
    )
    await session.commit()
    return body.schedules
