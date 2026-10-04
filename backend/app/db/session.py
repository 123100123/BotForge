"""Lazy async engine and the per-request session dependency."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


class DatabaseNotConfigured(RuntimeError):
    """DATABASE_URL is not set."""


def database_configured() -> bool:
    return get_settings().async_database_url is not None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = get_settings().async_database_url
        if url is None:
            raise DatabaseNotConfigured("DATABASE_URL is not set")
        # SECURITY: hide_parameters keeps bound values (webhook secrets, encrypted tokens, owner link
        # codes, customer data) out of exception text, which error handlers write to the log.
        _engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
