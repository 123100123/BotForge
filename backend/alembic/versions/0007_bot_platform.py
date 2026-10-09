"""Add bots.platform (Telegram or Bale); the messenger bot id is unique per platform.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09

Every existing bot is a Telegram bot (server default ``telegram``, filled without rewriting the
table). The single-column unique constraint on ``tg_bot_id`` (unnamed in 0001, so its name depends on
how the database was created) is looked up in the catalog and replaced by ``uq_bots_platform_tg_bot_id``
on ``(platform, tg_bot_id)``: a Telegram bot and a Bale bot may carry the same numeric id.

Downgrade restores the single-column constraint under PostgreSQL's default name; it fails while a
Telegram bot and a Bale bot share an id (disconnect one of them first).
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

S = "app"

_DROP_SINGLE_COLUMN_UNIQUE = """
DO $$
DECLARE c text;
BEGIN
    FOR c IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = rel.relnamespace
        JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attname = 'tg_bot_id'
        WHERE ns.nspname = 'app' AND rel.relname = 'bots' AND con.contype = 'u'
          AND con.conkey = ARRAY[att.attnum]::smallint[]
    LOOP
        EXECUTE format('ALTER TABLE app.bots DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("platform", sa.String(16), nullable=False, server_default="telegram"),
        schema=S,
    )
    op.create_check_constraint("ck_bots_platform", "bots", "platform IN ('telegram', 'bale')", schema=S)
    op.execute(_DROP_SINGLE_COLUMN_UNIQUE)
    op.create_unique_constraint("uq_bots_platform_tg_bot_id", "bots", ["platform", "tg_bot_id"], schema=S)


def downgrade() -> None:
    op.drop_constraint("uq_bots_platform_tg_bot_id", "bots", type_="unique", schema=S)
    op.create_unique_constraint("bots_tg_bot_id_key", "bots", ["tg_bot_id"], schema=S)
    op.drop_constraint("ck_bots_platform", "bots", type_="check", schema=S)
    op.drop_column("bots", "platform", schema=S)
