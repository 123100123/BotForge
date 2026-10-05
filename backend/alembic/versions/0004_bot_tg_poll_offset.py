"""Add bots.tg_poll_offset: the next getUpdates offset of a bot in Telegram polling mode.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05

Nullable and unused in webhook mode. Null means "no update handled yet for the stored token": the
poller then asks Telegram for every update it still holds.
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("tg_poll_offset", sa.BigInteger, nullable=True), schema="app")


def downgrade() -> None:
    op.drop_column("bots", "tg_poll_offset", schema="app")
