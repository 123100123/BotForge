"""Business OS persistence: roles, staff link, outbox, groups, modules, announcements, uploads, analysis.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06

One migration for the whole "AI Business OS" expansion (roadmap, Business OS data model), so parallel
work never writes competing migrations. Purely additive: existing rows are kept and get defaults.

- ``bot_users.role``: customer | staff | manager (the owner is a manager through ``bots.owner_actor_id``
  whatever this says). Existing users become ``customer``.
- ``bots.staff_link_code``: the multi-use, rotatable code in the staff deep link (``/start staff_<code>``).
  Null means no staff link. Unique, so a code identifies one bot.
- ``outbound_messages``: the notification outbox. Generators only insert rows; one ticker sends them.
  ``dedupe_key`` is unique per bot (NULL keys never collide), so a generator may insert the same
  reminder twice and only one row exists.
- ``bot_chats``: groups and channels the bot was added to (from ``my_chat_member``).
- ``bot_modules``: per-bot toggles and config of capabilities that are not part of the BotSpec.
- ``announcements``: broadcasts an owner sent (their messages go through the outbox).
- ``uploaded_files``: spreadsheet uploads (the bytes live in file storage under ``storage_key``).
- ``analysis_profiles`` / ``analysis_runs``: spreadsheet analysis profiles (one per bot and column
  signature) and their deterministic runs. A run keeps its result when its upload is deleted.
- ``ix_records_created``: time-ranged reporting over records.

Downgrade drops everything above. The new tables' rows (and the roles and staff link codes) are lost;
every pre-existing table and row is untouched.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

S = "app"


def _bot_fk() -> sa.Column:
    return sa.Column(
        "bot_id", pg.UUID(as_uuid=True), sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"), nullable=False
    )


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.add_column(
        "bot_users",
        sa.Column("role", sa.String(16), nullable=False, server_default="customer"),
        schema=S,
    )
    op.add_column("bots", sa.Column("staff_link_code", sa.String(64), nullable=True), schema=S)
    op.create_index("ux_bots_staff_link_code", "bots", ["staff_link_code"], unique=True, schema=S)

    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        _bot_fk(),
        sa.Column("env", sa.String(8), nullable=False),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("buttons", pg.JSONB, nullable=True),
        sa.Column("dedupe_key", sa.Text, nullable=True),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        _now("created_at"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("bot_id", "dedupe_key", name="uq_outbound_messages_bot_dedupe"),
        schema=S,
    )
    op.create_index("ix_outbound_messages_due", "outbound_messages", ["status", "not_before"], schema=S)

    op.create_table(
        "bot_chats",
        sa.Column(
            "bot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chat_id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        _now("added_at"),
        schema=S,
    )

    op.create_table(
        "bot_modules",
        sa.Column(
            "bot_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.bots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("module", sa.String(40), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("config", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _now("updated_at"),
        schema=S,
    )

    op.create_table(
        "announcements",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        _bot_fk(),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("group_chat_ids", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recipients", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        _now("created_at"),
        schema=S,
    )
    op.create_index("ix_announcements_bot_created", "announcements", ["bot_id", "created_at"], schema=S)

    op.create_table(
        "uploaded_files",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        _bot_fk(),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("uploaded_by", sa.Text, nullable=True),
        sa.Column("inspection", pg.JSONB, nullable=True),
        _now("created_at"),
        schema=S,
    )
    op.create_index("ix_uploaded_files_bot_created", "uploaded_files", ["bot_id", "created_at"], schema=S)

    op.create_table(
        "analysis_profiles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        _bot_fk(),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("signature", sa.Text, nullable=False),
        sa.Column("sheet", sa.Text, nullable=False),
        sa.Column("expected_columns", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metrics", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checks", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("daily_report", sa.Boolean, nullable=False, server_default=sa.false()),
        _now("created_at"),
        _now("updated_at"),
        sa.UniqueConstraint("bot_id", "signature", name="uq_analysis_profiles_bot_signature"),
        schema=S,
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        _bot_fk(),
        sa.Column(
            "profile_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.analysis_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "upload_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.uploaded_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("submitted_by", sa.Text, nullable=True),
        sa.Column("result", pg.JSONB, nullable=True),
        sa.Column("schema_diff", pg.JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        _now("created_at"),
        schema=S,
    )
    op.create_index(
        "ix_analysis_runs_bot_profile_created",
        "analysis_runs",
        ["bot_id", "profile_id", "created_at"],
        schema=S,
    )

    op.create_index("ix_records_created", "records", ["bot_id", "env", "collection", "created_at"], schema=S)


def downgrade() -> None:
    op.drop_index("ix_records_created", "records", schema=S)
    op.drop_index("ix_analysis_runs_bot_profile_created", "analysis_runs", schema=S)
    op.drop_table("analysis_runs", schema=S)
    op.drop_table("analysis_profiles", schema=S)
    op.drop_index("ix_uploaded_files_bot_created", "uploaded_files", schema=S)
    op.drop_table("uploaded_files", schema=S)
    op.drop_index("ix_announcements_bot_created", "announcements", schema=S)
    op.drop_table("announcements", schema=S)
    op.drop_table("bot_modules", schema=S)
    op.drop_table("bot_chats", schema=S)
    op.drop_index("ix_outbound_messages_due", "outbound_messages", schema=S)
    op.drop_table("outbound_messages", schema=S)
    op.drop_index("ux_bots_staff_link_code", "bots", schema=S)
    op.drop_column("bots", "staff_link_code", schema=S)
    op.drop_column("bot_users", "role", schema=S)
