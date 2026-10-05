"""Migration 0003 on a database that already holds bots: their owners become placeholder accounts, the
foreign key holds, nothing is deleted, and downgrade restores the text owner ids. Runs in a scratch
database on the test server (the shared test schema is never touched). Needs a database."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.security.accounts import authenticate, reset_password
from tests.integration.helpers import BACKEND

UUID_OWNER = "8d1d0d5e-8c33-4a39-9a3e-1f0c2b7c9a11"
TEXT_OWNER = "local-dev-owner"


@pytest.fixture
def scratch_db(test_db_url: str) -> Iterator[str]:
    name = f"migration_{uuid.uuid4().hex[:12]}"

    async def admin(statement: str) -> None:
        engine = create_async_engine(test_db_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.exec_driver_sql(statement)
        await engine.dispose()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(test_db_url).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


async def test_existing_bots_are_adopted_by_placeholder_accounts(scratch_db: str) -> None:
    alembic(scratch_db, "upgrade", "0002")
    engine = create_async_engine(scratch_db, poolclass=NullPool)
    try:
        bots = {uuid.uuid4(): UUID_OWNER, uuid.uuid4(): UUID_OWNER, uuid.uuid4(): TEXT_OWNER}
        async with engine.begin() as conn:
            for bot_id, owner in bots.items():
                await conn.execute(
                    text("INSERT INTO app.bots (id, owner_id, name) VALUES (:id, :owner, 'b')"),
                    {"id": bot_id, "owner": owner},
                )

        alembic(scratch_db, "upgrade", "head")
        async with engine.connect() as conn:
            users = {
                row.id: row
                for row in await conn.execute(text("SELECT id, email, password_hash FROM app.users"))
            }
            rows = await conn.execute(text("SELECT id, owner_id FROM app.bots"))
            owners = {row.id: row.owner_id for row in rows}
            text_owner_id = (await conn.execute(text("SELECT md5(:o)::uuid"), {"o": TEXT_OWNER})).scalar_one()
        assert set(users) == {uuid.UUID(UUID_OWNER), text_owner_id}
        for user_id, row in users.items():
            assert row.email == f"legacy-{user_id}@botforge.invalid"
            assert row.password_hash == "!legacy-owner-without-password"
        expected = {b: uuid.UUID(o) if o == UUID_OWNER else text_owner_id for b, o in bots.items()}
        assert owners == expected  # every bot kept, owned by its adopted account

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        legacy_email = f"legacy-{UUID_OWNER}@botforge.invalid"
        async with sessions() as session:  # unusable until an operator sets a password
            assert await authenticate(session, legacy_email, "!legacy-owner-without-password") is None
            await reset_password(session, legacy_email, "claimed password 1")
            await session.commit()
        async with sessions() as session:
            assert await authenticate(session, legacy_email, "claimed password 1") is not None

        with pytest.raises(IntegrityError, match="fk_bots_owner_user"):
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO app.bots (id, owner_id, name) VALUES (:id, :owner, 'x')"),
                    {"id": uuid.uuid4(), "owner": uuid.uuid4()},
                )
        async with engine.begin() as conn:  # ON DELETE CASCADE: an account's bots go with it
            await conn.execute(text("DELETE FROM app.users WHERE id = :id"), {"id": text_owner_id})
            left = (await conn.execute(text("SELECT count(*) FROM app.bots"))).scalar_one()
        assert left == 2

        alembic(scratch_db, "downgrade", "0002")
        async with engine.connect() as conn:
            restored = set((await conn.execute(text("SELECT owner_id FROM app.bots"))).scalars())
            tables = set(
                (
                    await conn.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'app'")
                    )
                ).scalars()
            )
        assert restored == {UUID_OWNER}
        assert "users" not in tables and "auth_sessions" not in tables and "sessions" in tables
        alembic(scratch_db, "upgrade", "head")  # and forward again
    finally:
        await engine.dispose()
