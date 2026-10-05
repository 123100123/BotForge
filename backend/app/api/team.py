"""Team: the staff invite link and member roles (roadmap: Roles; models in ``schemas/business.py``).

  GET    /bots/{bot_id}/team                      TeamOut: staff link (while connected), its code,
                                                  the staff and managers, counts per role
  POST   /bots/{bot_id}/team/staff-link           StaffLinkOut: a new code; the previous link stops
                                                  working
  DELETE /bots/{bot_id}/team/staff-link           204: no code, the link stops working (staff keep
                                                  their role)
  PATCH  /bots/{bot_id}/team/members/{actor_id}   MemberRoleIn -> TeamMemberOut: set the role of a
                                                  user who has talked to the bot (404 otherwise);
                                                  the owner stays a manager (409 for another role)

Only the bot's owner reaches these: ``get_owned_bot`` (another owner's bot is a 404 identical to a
missing one, and a state-changing method passes the CSRF check before any database work). Roles are
those of the live bot; the simulator's personas carry their own. The staff code is a secret: it is
returned to the owner here and nowhere else, and never logged. Every write commits before the
response (``get_session``'s own commit runs after it).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.db.models import Bot
from app.db.session import get_session
from app.roles import service
from app.schemas.business import MemberRoleIn, StaffLinkOut, TeamMemberOut, TeamOut

router = APIRouter(tags=["team"])

MAX_ACTOR_ID_CHARS = 64  # Telegram user ids are at most 20 digits; anything longer is no member
ActorId = Annotated[str, Path(min_length=1, max_length=MAX_ACTOR_ID_CHARS)]


def _link_out(bot: Bot) -> StaffLinkOut:
    return StaffLinkOut(staff_link=service.staff_link(bot), staff_link_code=bot.staff_link_code)


@router.get("/bots/{bot_id}/team", response_model=TeamOut)
async def read_team(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> TeamOut:
    return await service.team_of(session, bot)


@router.post("/bots/{bot_id}/team/staff-link", response_model=StaffLinkOut)
async def rotate_staff_link(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> StaffLinkOut:
    await service.rotate_staff_code(session, bot)
    await session.commit()
    return _link_out(bot)


@router.delete("/bots/{bot_id}/team/staff-link", status_code=204)
async def revoke_staff_link(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.revoke_staff_code(session, bot)
    await session.commit()
    return Response(status_code=204)


@router.patch("/bots/{bot_id}/team/members/{actor_id}", response_model=TeamMemberOut)
async def set_member_role(
    actor_id: ActorId,
    body: MemberRoleIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> TeamMemberOut:
    try:
        member = await service.change_member_role(session, bot, actor_id, body.role)
    except service.TeamError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from None
    await session.commit()
    return member
