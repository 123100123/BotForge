"""Shared test helpers: stand-in auth dependencies and an ASGI client factory.

Authentication is not implemented in this work package, so tests replace ``get_current_user`` with
a header-driven stand-in (``X-Test-User``) and ``get_owned_bot`` with a stand-in that applies the
ownership rule (404 for another user's bot).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import CurrentUser, get_current_user, get_owned_bot
from app.db.models import Bot
from app.db.session import get_session

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

SessionFactory = async_sessionmaker[AsyncSession]


def install_test_auth(app: FastAPI, session_factory: SessionFactory | None) -> None:
    async def fake_user(x_test_user: str = Header("alice")) -> CurrentUser:
        return CurrentUser(id=x_test_user, email=f"{x_test_user}@example.com")

    async def fake_owned_bot(
        bot_id: uuid.UUID,
        user: CurrentUser = Depends(fake_user),
        session: AsyncSession = Depends(get_session),
    ) -> Bot:
        bot = await session.get(Bot, bot_id)
        if bot is None or bot.owner_id != user.id:
            raise HTTPException(404, detail={"code": "bot_not_found", "message": "ربات پیدا نشد."})
        return bot

    async def fake_session() -> AsyncIterator[AsyncSession | None]:
        if session_factory is None:
            yield None
            return
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_owned_bot] = fake_owned_bot
    app.dependency_overrides[get_session] = fake_session


def make_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")
