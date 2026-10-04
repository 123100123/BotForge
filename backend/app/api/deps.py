"""Authentication and ownership dependencies: INTERFACE ONLY in this work package.

The bodies are implemented by the security work package (JWT verification and the ownership
check). Endpoints depend on these two functions; tests replace them via
``app.dependency_overrides``.
"""

import uuid

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot
from app.db.session import get_session


class CurrentUser(BaseModel):
    id: str  # Supabase user id (JWT "sub")
    email: str | None = None


async def get_current_user() -> CurrentUser:
    # SECURITY: implemented by the security work package
    raise NotImplementedError


async def get_owned_bot(
    bot_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Bot:
    # SECURITY: implemented by the security work package
    raise NotImplementedError
