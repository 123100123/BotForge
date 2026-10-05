"""Capability Center API (W1-REG): list capabilities, enable/disable with dependency plans, configure.

  GET   /bots/{bot_id}/capabilities                       -> CapabilityListOut
  POST  /bots/{bot_id}/capabilities/{cap_id}/enable       CapabilityToggleIn -> CapabilityToggleOut
  POST  /bots/{bot_id}/capabilities/{cap_id}/disable      CapabilityToggleIn -> CapabilityToggleOut
  PATCH /bots/{bot_id}/capabilities/{cap_id}/config       CapabilityConfigIn -> CapabilityToggleOut

``dry_run`` (body field or ``?dry_run=true``) returns the plan (``applied=False``) and writes
nothing. Spec changes become a new active revision; module changes write ``bot_modules``.

Errors use the standard envelope: unknown capability 404 ``capability_not_found``;
``capability_unavailable``, ``capability_conflict``, ``capability_not_configured`` and every
revision-pipeline error (``no_active_revision``, ``invalid_spec``, ``compat_error``,
``tests_failing``, ``stale_base``...) 409; bad config 422 ``invalid_config``.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.capabilities import service
from app.db.models import Bot
from app.db.session import get_session
from app.revisions.service import BotNotFound, RevisionError
from app.schemas.business import (
    CapabilityConfigIn,
    CapabilityListOut,
    CapabilityToggleIn,
    CapabilityToggleOut,
)

router = APIRouter(tags=["capabilities"])


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.CapabilityError):
        detail = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        return HTTPException(exc.status, detail=detail)
    assert isinstance(exc, RevisionError)
    detail = {"code": exc.code, "message": exc.message}
    details = getattr(exc, "details", None)
    if details is not None:
        detail["details"] = details
    return HTTPException(404 if isinstance(exc, BotNotFound) else 409, detail=detail)


def _body(body: CapabilityToggleIn | None, dry_run: bool) -> CapabilityToggleIn:
    """``dry_run`` may come in the body or as ``?dry_run=true``; either turns it on."""
    return CapabilityToggleIn(dry_run=dry_run or (body is not None and body.dry_run))


@router.get("/bots/{bot_id}/capabilities", response_model=CapabilityListOut)
async def list_capabilities(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> CapabilityListOut:
    return await service.list_for_bot(session, bot)


async def _toggle(
    session: AsyncSession, bot: Bot, cap_id: str, action: service.Action, body: CapabilityToggleIn
) -> CapabilityToggleOut:
    try:
        out = await service.toggle(session, bot, cap_id, action, dry_run=body.dry_run)
    except (service.CapabilityError, RevisionError) as exc:
        await session.rollback()
        raise _http(exc) from None
    if body.dry_run or not out.applied:
        await session.rollback()  # nothing to keep; releases the advisory lock
    else:
        await session.commit()
    return out


@router.post("/bots/{bot_id}/capabilities/{cap_id}/enable", response_model=CapabilityToggleOut)
async def enable_capability(
    cap_id: str,
    body: CapabilityToggleIn | None = None,
    dry_run: bool = Query(False),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> CapabilityToggleOut:
    return await _toggle(session, bot, cap_id, "enable", _body(body, dry_run))


@router.post("/bots/{bot_id}/capabilities/{cap_id}/disable", response_model=CapabilityToggleOut)
async def disable_capability(
    cap_id: str,
    body: CapabilityToggleIn | None = None,
    dry_run: bool = Query(False),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> CapabilityToggleOut:
    return await _toggle(session, bot, cap_id, "disable", _body(body, dry_run))


@router.patch("/bots/{bot_id}/capabilities/{cap_id}/config", response_model=CapabilityToggleOut)
async def configure_capability(
    cap_id: str,
    body: CapabilityConfigIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> CapabilityToggleOut:
    try:
        out = await service.update_config(session, bot, cap_id, body.config)
    except (service.CapabilityError, RevisionError) as exc:
        await session.rollback()
        raise _http(exc) from None
    await session.commit()
    return out
