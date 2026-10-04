"""Initial schema: Postgres schema ``app`` and all tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "app"


def _ts(name: str, *, nullable: bool = False, default: bool = True) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default else None,
    )


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{S}"')

    op.create_table(
        "bots",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column("active_revision_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("tg_bot_id", sa.BigInteger, nullable=True, unique=True),
        sa.Column("tg_username", sa.String, nullable=True),
        sa.Column("tg_token_enc", sa.Text, nullable=True),
        sa.Column("tg_webhook_secret", sa.String, nullable=True),
        sa.Column("owner_link_code", sa.String, nullable=True),
        sa.Column("owner_actor_id", sa.String, nullable=True),
        _ts("created_at"),
        schema=S,
    )
    op.create_index("ix_bots_owner_id", "bots", ["owner_id"], schema=S)

    op.create_table(
        "revisions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bot_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column(
            "parent_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column("spec", pg.JSONB, nullable=False),
        sa.Column("requirements", pg.JSONB, nullable=True),
        sa.Column("patch", pg.JSONB, nullable=True),
        sa.Column("change_request", sa.Text, nullable=True),
        sa.Column("scenarios", pg.JSONB, nullable=True),
        sa.Column("superseded", pg.JSONB, nullable=True),
        sa.Column("test_report", pg.JSONB, nullable=True),
        sa.Column("sample_data", pg.JSONB, nullable=True),
        _ts("created_at"),
        _ts("activated_at", nullable=True, default=False),
        sa.UniqueConstraint("bot_id", "number", name="uq_revisions_bot_number"),
        schema=S,
    )
    # bots <-> revisions reference each other, so this FK is added after both tables exist
    op.create_foreign_key(
        "fk_bots_active_revision",
        "bots",
        "revisions",
        ["active_revision_id"],
        ["id"],
        source_schema=S,
        referent_schema=S,
        ondelete="SET NULL",
    )

    op.create_table(
        "records",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "bot_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("env", sa.String, nullable=False),
        sa.Column("collection", sa.String, nullable=False),
        sa.Column("data", pg.JSONB, nullable=False),
        sa.Column("status", sa.String, nullable=True),
        sa.Column("actor_id", sa.String, nullable=True),
        sa.Column("item_id", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=S,
    )
    op.create_index("ix_records_collection", "records", ["bot_id", "env", "collection"], schema=S)
    op.create_index(
        "ix_records_item_status", "records", ["bot_id", "env", "collection", "item_id", "status"], schema=S
    )
    op.create_index("ix_records_actor", "records", ["bot_id", "env", "collection", "actor_id"], schema=S)

    op.create_table(
        "sessions",
        sa.Column(
            "bot_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("env", sa.String, nullable=False),
        sa.Column("actor_id", sa.String, nullable=False),
        sa.Column("state", pg.JSONB, nullable=False),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("bot_id", "env", "actor_id"),
        schema=S,
    )

    op.create_table(
        "bot_users",
        sa.Column(
            "bot_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("env", sa.String, nullable=False),
        sa.Column("actor_id", sa.String, nullable=False),
        sa.Column("display_name", sa.String, nullable=False),
        _ts("first_seen"),
        sa.PrimaryKeyConstraint("bot_id", "env", "actor_id"),
        schema=S,
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bot_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("phase", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="running"),
        sa.Column("state", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "base_revision_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "result_revision_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("usage", pg.JSONB, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        schema=S,
    )
    op.create_index("ix_agent_runs_bot_created", "agent_runs", ["bot_id", "created_at"], schema=S)

    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _ts("ts"),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema=S,
    )
    op.create_index("ix_agent_events_run_id", "agent_events", ["run_id", "id"], schema=S)

    op.create_table(
        "tg_updates",
        sa.Column(
            "bot_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("update_id", sa.BigInteger, nullable=False, autoincrement=False),
        sa.PrimaryKeyConstraint("bot_id", "update_id"),
        schema=S,
    )


def downgrade() -> None:
    for table in ("tg_updates", "agent_events", "agent_runs", "bot_users", "sessions", "records"):
        op.drop_table(table, schema=S)
    op.drop_constraint("fk_bots_active_revision", "bots", schema=S, type_="foreignkey")
    op.drop_table("revisions", schema=S)
    op.drop_table("bots", schema=S)
