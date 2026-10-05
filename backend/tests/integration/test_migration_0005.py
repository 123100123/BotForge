"""Migration 0005 (Business OS): upgrade on a database that already holds data keeps every row and adds
the new tables, columns and indexes; the ORM models match what the migration creates; the new
constraints hold; downgrade to 0004 removes exactly the new objects; upgrading again works. Runs in a
scratch database on the test server (the shared test schema is never touched). Needs a database."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import (
    AnalysisProfileRow,
    AnalysisRunRow,
    AnnouncementRow,
    Base,
    BotChatRow,
    BotModuleRow,
    BotUser,
    OutboundMessageRow,
    UploadedFileRow,
)
from tests.integration.helpers import BACKEND

NEW_TABLES = {
    "outbound_messages",
    "bot_chats",
    "bot_modules",
    "announcements",
    "uploaded_files",
    "analysis_profiles",
    "analysis_runs",
}
NEW_INDEXES = {
    "ux_bots_staff_link_code",
    "ix_outbound_messages_due",
    "uq_outbound_messages_bot_dedupe",
    "ix_announcements_bot_created",
    "ix_uploaded_files_bot_created",
    "uq_analysis_profiles_bot_signature",
    "ix_analysis_runs_bot_profile_created",
    "ix_records_created",
}
NEW_COLUMNS = {("bot_users", "role"), ("bots", "staff_link_code")}


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


async def _catalog(engine: AsyncEngine) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """(tables, (table, column) pairs, index names) of schema ``app``."""
    async with engine.connect() as conn:
        tables = set(
            (
                await conn.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'app'")
                )
            ).scalars()
        )
        columns = {
            (row.table_name, row.column_name)
            for row in await conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'app'"
                )
            )
        }
        indexes = set(
            (await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'app'"))).scalars()
        )
    return tables, columns, indexes


def _orm_drift(conn: Connection) -> list[object]:
    """Differences between the ORM metadata and the database, limited to what 0005 added."""
    context = MigrationContext.configure(
        conn,
        opts={"include_schemas": True, "compare_type": True, "compare_server_default": True},
    )
    drift = []
    for diff in compare_metadata(context, Base.metadata):
        ops = diff if isinstance(diff, list) else [diff]
        for op in ops:
            text_form = repr(op)
            if any(t in text_form for t in NEW_TABLES | NEW_INDEXES | {"staff_link_code", "'role'"}):
                drift.append(op)
    return drift


async def test_upgrade_keeps_data_matches_orm_and_downgrades_cleanly(scratch_db: str) -> None:
    alembic(scratch_db, "upgrade", "0004")
    engine = create_async_engine(scratch_db, poolclass=NullPool)
    user_id, bot_id, other_bot_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    try:
        async with engine.begin() as conn:  # data that exists before the migration
            await conn.execute(
                text("INSERT INTO app.users (id, email, password_hash) VALUES (:id, 'o@example.com', 'x')"),
                {"id": user_id},
            )
            for b in (bot_id, other_bot_id):
                await conn.execute(
                    text("INSERT INTO app.bots (id, owner_id, name) VALUES (:id, :owner, 'b')"),
                    {"id": b, "owner": user_id},
                )
            await conn.execute(
                text(
                    "INSERT INTO app.bot_users (bot_id, env, actor_id, display_name) "
                    "VALUES (:bot, 'live', '42', 'Sara')"
                ),
                {"bot": bot_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO app.records (bot_id, env, collection, data, created_at, updated_at) "
                    "VALUES (:bot, 'live', 'items', '{\"name\": \"x\"}', :now, :now)"
                ),
                {"bot": bot_id, "now": now},
            )

        alembic(scratch_db, "upgrade", "head")
        tables, columns, indexes = await _catalog(engine)
        assert tables >= NEW_TABLES
        assert columns >= NEW_COLUMNS
        assert indexes >= NEW_INDEXES
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT role FROM app.bot_users"))).scalar_one() == "customer"
            assert (await conn.execute(text("SELECT count(*) FROM app.records"))).scalar_one() == 1
            assert (await conn.execute(text("SELECT count(*) FROM app.bots"))).scalar_one() == 2
            assert await conn.run_sync(_orm_drift) == []

        # Every new ORM class writes and reads back against the migrated schema, defaults included.
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        upload_id, profile_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with sessions() as session:
            session.add_all(
                [
                    OutboundMessageRow(bot_id=bot_id, env="live", chat_id=42, text="hi", not_before=now),
                    OutboundMessageRow(
                        bot_id=bot_id, env="live", chat_id=42, text="r", not_before=now, dedupe_key="rem:1"
                    ),
                    OutboundMessageRow(  # the same key on another bot does not collide
                        bot_id=other_bot_id,
                        env="live",
                        chat_id=7,
                        text="r",
                        not_before=now,
                        dedupe_key="rem:1",
                    ),
                    OutboundMessageRow(bot_id=bot_id, env="live", chat_id=43, text="no key", not_before=now),
                    BotChatRow(bot_id=bot_id, chat_id=-100123, title="Group", kind="supergroup"),
                    BotModuleRow(bot_id=bot_id, module="copilot"),
                    AnnouncementRow(bot_id=bot_id, text="news", audience="everyone"),
                    UploadedFileRow(
                        id=upload_id,
                        bot_id=bot_id,
                        filename="sales.xlsx",
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        size=1234,
                        sha256="0" * 64,
                        storage_key="k",
                        source="web",
                    ),
                ]
            )
            await session.flush()
            session.add(AnalysisProfileRow(id=profile_id, bot_id=bot_id, name="p", signature="s", sheet="S1"))
            await session.flush()
            session.add(
                AnalysisRunRow(
                    id=run_id, bot_id=bot_id, profile_id=profile_id, upload_id=upload_id, status="ok"
                )
            )
            await session.commit()
        async with sessions() as session:
            message = await session.get(OutboundMessageRow, 1)
            assert message is not None
            assert (message.status, message.attempts, message.created_at is not None) == ("queued", 0, True)
            module = await session.get(BotModuleRow, (bot_id, "copilot"))
            assert module is not None and (module.enabled, module.config) == (True, {})
            chat = await session.get(BotChatRow, (bot_id, -100123))
            assert chat is not None and chat.active is True
            user = await session.get(BotUser, (bot_id, "live", "42"))
            assert user is not None and user.role == "customer"
            profile = await session.get(AnalysisProfileRow, profile_id)
            assert profile is not None
            assert (profile.expected_columns, profile.metrics, profile.checks, profile.daily_report) == (
                [],
                [],
                [],
                False,
            )

        with pytest.raises(IntegrityError, match="uq_outbound_messages_bot_dedupe"):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO app.outbound_messages "
                        "(bot_id, env, chat_id, text, not_before, dedupe_key) "
                        "VALUES (:bot, 'live', 42, 'dup', now(), 'rem:1')"
                    ),
                    {"bot": bot_id},
                )
        with pytest.raises(IntegrityError, match="uq_analysis_profiles_bot_signature"):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO app.analysis_profiles (id, bot_id, name, signature, sheet) "
                        "VALUES (:id, :bot, 'p2', 's', 'S1')"
                    ),
                    {"id": uuid.uuid4(), "bot": bot_id},
                )
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE app.bots SET staff_link_code = 'abc' WHERE id = :id"), {"id": bot_id}
            )
        with pytest.raises(IntegrityError, match="ux_bots_staff_link_code"):
            async with engine.begin() as conn:
                await conn.execute(
                    text("UPDATE app.bots SET staff_link_code = 'abc' WHERE id = :id"), {"id": other_bot_id}
                )

        async with engine.begin() as conn:  # deleting the upload keeps the run, without its upload
            await conn.execute(text("DELETE FROM app.uploaded_files WHERE id = :id"), {"id": upload_id})
            left = (
                await conn.execute(
                    text("SELECT upload_id FROM app.analysis_runs WHERE id = :id"), {"id": run_id}
                )
            ).scalar_one()
        assert left is None

        async with engine.begin() as conn:  # deleting a bot removes its rows from every new table
            await conn.execute(text("DELETE FROM app.bots WHERE id = :id"), {"id": bot_id})
            for table in sorted(NEW_TABLES):
                count = (
                    await conn.execute(
                        text(f"SELECT count(*) FROM app.{table} WHERE bot_id = :b"), {"b": bot_id}
                    )
                ).scalar_one()
                assert count == 0, table
            await conn.execute(  # restore one pre-existing row for the downgrade check
                text("INSERT INTO app.bots (id, owner_id, name) VALUES (:id, :owner, 'b')"),
                {"id": bot_id, "owner": user_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO app.bot_users (bot_id, env, actor_id, display_name, role) "
                    "VALUES (:bot, 'live', '42', 'Sara', 'staff')"
                ),
                {"bot": bot_id},
            )

        alembic(scratch_db, "downgrade", "0004")
        tables, columns, indexes = await _catalog(engine)
        assert not tables & NEW_TABLES
        assert not columns & NEW_COLUMNS
        assert not indexes & NEW_INDEXES
        assert {"bots", "bot_users", "records", "users", "sessions"} <= tables
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT count(*) FROM app.bots"))).scalar_one() == 2
            assert (await conn.execute(text("SELECT display_name FROM app.bot_users"))).scalar_one() == "Sara"
            version = (await conn.execute(text("SELECT version_num FROM app.alembic_version"))).scalar_one()
        assert version == "0004"

        alembic(scratch_db, "upgrade", "head")  # and forward again
        tables, columns, indexes = await _catalog(engine)
        assert tables >= NEW_TABLES and columns >= NEW_COLUMNS and indexes >= NEW_INDEXES
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT role FROM app.bot_users"))).scalar_one() == "customer"
    finally:
        await engine.dispose()
