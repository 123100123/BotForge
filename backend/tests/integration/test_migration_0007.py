"""Migration 0007 (Bale platform): existing bots become Telegram bots, the messenger bot id is unique
per platform, the platform value is checked, the ORM matches, and downgrade to 0006 restores the
single-column uniqueness. Runs in a scratch database. Needs a database."""

import uuid
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import Base
from tests.integration.test_migration_0005 import alembic, scratch_db  # noqa: F401  (fixture)

INSERT = "INSERT INTO app.bots (id, owner_id, name, tg_bot_id{extra}) VALUES (:id, :owner, 'b', :tg{values})"


def _insert(platform: str | None = None) -> Any:
    """An INSERT of a bot; with ``platform`` (any value) the statement also sets ``:platform``."""
    if platform is None:
        return text(INSERT.format(extra="", values=""))
    return text(INSERT.format(extra=", platform", values=", :platform"))


def _drift(conn: Connection) -> list[object]:
    context = MigrationContext.configure(
        conn, opts={"include_schemas": True, "compare_type": True, "compare_server_default": True}
    )
    found = []
    for diff in compare_metadata(context, Base.metadata):
        for op in diff if isinstance(diff, list) else [diff]:
            if any(t in repr(op) for t in ("platform", "tg_bot_id")):
                found.append(op)
    return found


async def _fails(conn: AsyncConnection, statement: Any, params: dict[str, Any]) -> bool:
    try:
        async with conn.begin_nested():
            await conn.execute(statement, params)
    except IntegrityError:
        return True
    return False


async def test_platform_column_and_per_platform_uniqueness(scratch_db: str) -> None:  # noqa: F811
    alembic(scratch_db, "upgrade", "0006")
    engine = create_async_engine(scratch_db, poolclass=NullPool)
    owner = uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO app.users (id, email, password_hash) VALUES (:id, 'o@example.com', 'x')"),
                {"id": owner},
            )
            await conn.execute(_insert(), {"id": uuid.uuid4(), "owner": owner, "tg": 111})
            await conn.execute(_insert(), {"id": uuid.uuid4(), "owner": owner, "tg": None})

        alembic(scratch_db, "upgrade", "head")
        async with engine.connect() as conn:
            platforms = (await conn.execute(text("SELECT DISTINCT platform FROM app.bots"))).scalars().all()
            assert platforms == ["telegram"]
            assert await conn.run_sync(_drift) == []

        async with engine.begin() as conn:
            bale = {"id": uuid.uuid4(), "owner": owner, "tg": 111, "platform": "bale"}
            await conn.execute(_insert("bale"), bale)  # same id on another platform: allowed
            assert await _fails(conn, _insert("bale"), {**bale, "id": uuid.uuid4()})  # same platform: not
            assert await _fails(conn, _insert(), {"id": uuid.uuid4(), "owner": owner, "tg": 111})
            assert await _fails(conn, _insert("x"), {**bale, "id": uuid.uuid4(), "tg": 5, "platform": "x"})
            await conn.execute(text("DELETE FROM app.bots WHERE platform = 'bale'"))

        alembic(scratch_db, "downgrade", "0006")
        async with engine.begin() as conn:
            columns = (
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'app' AND table_name = 'bots'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "platform" not in columns
            assert await _fails(conn, _insert(), {"id": uuid.uuid4(), "owner": owner, "tg": 111})
        alembic(scratch_db, "upgrade", "head")
    finally:
        await engine.dispose()


@pytest.mark.parametrize("name", ["bots_tg_bot_id_key", "some_other_name"])
async def test_upgrade_finds_the_old_constraint_whatever_its_name(scratch_db: str, name: str) -> None:  # noqa: F811
    alembic(scratch_db, "upgrade", "0006")
    engine = create_async_engine(scratch_db, poolclass=NullPool)
    try:
        if name != "bots_tg_bot_id_key":
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE app.bots DROP CONSTRAINT bots_tg_bot_id_key"))
                await conn.execute(text(f"ALTER TABLE app.bots ADD CONSTRAINT {name} UNIQUE (tg_bot_id)"))
        alembic(scratch_db, "upgrade", "head")
        async with engine.connect() as conn:
            names = (
                (
                    await conn.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conrelid = 'app.bots'::regclass "
                            "AND contype = 'u'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert "uq_bots_platform_tg_bot_id" in names and name not in names
    finally:
        await engine.dispose()
