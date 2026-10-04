"""Bots: list, create, read, rename, delete. Never exposes token or webhook-secret columns."""

import secrets
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_owned_bot
from app.db.models import Bot, Revision
from app.db.session import get_session
from app.integrations.telegram.client import TelegramProvider, get_telegram_provider
from app.integrations.telegram.onboarding import drop_webhook

router = APIRouter(tags=["bots"])

BotName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class MeOut(BaseModel):
    id: str
    email: str | None = None


class BotCreate(BaseModel):
    name: BotName


class BotUpdate(BaseModel):
    name: BotName


class BotOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    tg_username: str | None
    active_revision_id: uuid.UUID | None
    active_revision_number: int | None
    owner_link_code: str | None
    owner_linked: bool
    created_at: datetime


def _bot_out(bot: Bot, active_number: int | None) -> BotOut:
    return BotOut(
        id=bot.id,
        name=bot.name,
        status=bot.status,
        tg_username=bot.tg_username,
        active_revision_id=bot.active_revision_id,
        active_revision_number=active_number,
        owner_link_code=bot.owner_link_code,
        owner_linked=bot.owner_actor_id is not None,
        created_at=bot.created_at,
    )


async def _active_number(session: AsyncSession, bot: Bot) -> int | None:
    if bot.active_revision_id is None:
        return None
    stmt = select(Revision.number).where(Revision.id == bot.active_revision_id, Revision.bot_id == bot.id)
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("/me", response_model=MeOut)
async def read_me(user: CurrentUser = Depends(get_current_user)) -> MeOut:
    return MeOut(id=user.id, email=user.email)


@router.get("/bots", response_model=list[BotOut])
async def list_bots(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[BotOut]:
    stmt = (
        select(Bot, Revision.number)
        .outerjoin(Revision, and_(Revision.id == Bot.active_revision_id, Revision.bot_id == Bot.id))
        .where(Bot.owner_id == user.id)
        .order_by(Bot.created_at.desc(), Bot.id)
    )
    rows = (await session.execute(stmt)).all()
    return [_bot_out(bot, number) for bot, number in rows]


@router.post("/bots", response_model=BotOut, status_code=201)
async def create_bot(
    body: BotCreate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BotOut:
    bot = Bot(
        owner_id=user.id,
        name=body.name,
        status="draft",
        owner_link_code=secrets.token_urlsafe(12),
    )
    session.add(bot)
    await session.flush()
    await session.refresh(bot)  # server-side created_at
    await session.commit()  # before responding; get_session's own commit runs after the response
    return _bot_out(bot, None)


@router.get("/bots/{bot_id}", response_model=BotOut)
async def read_bot(bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)) -> BotOut:
    return _bot_out(bot, await _active_number(session, bot))


@router.patch("/bots/{bot_id}", response_model=BotOut)
async def rename_bot(
    body: BotUpdate,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> BotOut:
    bot.name = body.name
    number = await _active_number(session, bot)
    await session.commit()
    return _bot_out(bot, number)


@router.delete("/bots/{bot_id}", status_code=204)
async def delete_bot(
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    telegram: TelegramProvider = Depends(get_telegram_provider),
) -> Response:
    if bot.tg_token_enc:  # best effort: Telegram stops calling a webhook that no longer exists
        await drop_webhook(bot.tg_token_enc, telegram)
    # Rows in every child table go with the bot through ON DELETE CASCADE.
    await session.execute(delete(Bot).where(Bot.id == bot.id).execution_options(synchronize_session=False))
    session.expunge(bot)
    await session.commit()
    return Response(status_code=204)
