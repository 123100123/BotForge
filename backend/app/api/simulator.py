"""Simulator endpoints: send a persona's event to the sandbox; reset the sandbox."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.db.models import Bot
from app.db.session import get_session
from app.revisions.service import RevisionError
from app.runtime.callbacks import MAX_CALLBACK_BYTES
from app.runtime.contracts import RuntimeResponse
from app.simulator.service import EventKind, Persona, SimulatorError, reset_sandbox, simulate_event

router = APIRouter(tags=["simulator"])

# Telegram's own bounds, so the sandbox never receives input the live channel could not deliver.
MAX_TEXT_CHARS = 4096  # a Telegram text message


class SimulatorEventBody(BaseModel):
    revision_id: uuid.UUID | None = None  # null = the active revision
    persona: Persona
    kind: EventKind
    text: str | None = Field(None, max_length=MAX_TEXT_CHARS)
    data: str | None = Field(None, max_length=MAX_CALLBACK_BYTES)  # bytes are checked by the runtime


class ResetBody(BaseModel):
    revision_id: uuid.UUID | None = None


class ResetOut(BaseModel):
    ok: bool
    loaded: int


def _http(exc: SimulatorError | RevisionError) -> HTTPException:
    if isinstance(exc, SimulatorError):
        return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})
    return HTTPException(400, detail={"code": exc.code, "message": exc.message})


@router.post("/bots/{bot_id}/simulator/events", response_model=RuntimeResponse)
async def simulator_event(
    body: SimulatorEventBody,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> RuntimeResponse:
    try:
        return await simulate_event(
            session, bot, body.revision_id, body.persona, body.kind, text=body.text, data=body.data
        )
    except SimulatorError as exc:
        raise _http(exc) from None


@router.post("/bots/{bot_id}/simulator/reset", response_model=ResetOut)
async def simulator_reset(
    body: ResetBody | None = None,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> ResetOut:
    try:
        loaded = await reset_sandbox(session, bot, body.revision_id if body else None)
    except (SimulatorError, RevisionError) as exc:
        raise _http(exc) from None
    return ResetOut(ok=True, loaded=loaded)
