"""Add tg_updates.received_at so old dedupe records can be pruned.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08

``tg_updates`` records every handled Telegram update id (webhook and poller dedupe). It only grew;
the poller's supervisor now deletes rows older than three days. Existing rows get the migration time
(now() is a stable default, so PostgreSQL fills it without rewriting the table) and are pruned three
days later.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tg_updates",
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="app",
    )
    op.create_index("ix_tg_updates_received_at", "tg_updates", ["received_at"], schema="app")


def downgrade() -> None:
    op.drop_index("ix_tg_updates_received_at", table_name="tg_updates", schema="app")
    op.drop_column("tg_updates", "received_at", schema="app")
