"""Own authentication: ``users`` and ``auth_sessions``; ``bots.owner_id`` becomes a uuid foreign key.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05

``auth_sessions`` holds login sessions (only the SHA-256 digest of each cookie token). It is unrelated
to the existing ``sessions`` table, which holds the bots' conversation state.

Owner ids used to be external (Supabase) user ids stored as text. Bots that exist when this runs are
adopted by placeholder accounts, so the new foreign key holds and nothing is deleted: one user per
distinct owner id, keeping the id when it is a UUID (external ids were) and using ``md5(owner_id)``
as the UUID otherwise. A placeholder's email is ``legacy-<id>@botforge.invalid`` (a reserved,
undeliverable domain) and its password hash never verifies, so nobody can sign in to it until an
operator sets a password with ``scripts/create_user.py --email <that email> --reset-password``.

Downgrade restores ``owner_id`` as text (a UUID's text form; the original string of a non-UUID id is
not recoverable) and drops both tables.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

S = "app"

_UUID_TEXT = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
# The account a pre-existing text owner id maps to (used for the placeholder rows and the type change).
_OWNER_UUID = f"(CASE WHEN owner_id ~ '{_UUID_TEXT}' THEN owner_id::uuid ELSE md5(owner_id)::uuid END)"
# Not an argon2 hash, so verification always fails (see app.security.passwords.verify_password).
LEGACY_PASSWORD_HASH = "!legacy-owner-without-password"
LEGACY_EMAIL_DOMAIN = "botforge.invalid"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema=S,
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(f"{S}.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        schema=S,
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], schema=S)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], schema=S)

    # Adopt the owners of existing bots (none on a fresh database).
    op.execute(
        f"""
        INSERT INTO {S}.users (id, email, password_hash)
        SELECT owner_uuid, 'legacy-' || owner_uuid::text || '@{LEGACY_EMAIL_DOMAIN}', '{LEGACY_PASSWORD_HASH}'
        FROM (SELECT DISTINCT {_OWNER_UUID} AS owner_uuid FROM {S}.bots) AS owners
        """
    )
    op.execute(f"ALTER TABLE {S}.bots ALTER COLUMN owner_id TYPE uuid USING {_OWNER_UUID}")
    op.create_foreign_key(
        "fk_bots_owner_user",
        "bots",
        "users",
        ["owner_id"],
        ["id"],
        source_schema=S,
        referent_schema=S,
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_bots_owner_user", "bots", schema=S, type_="foreignkey")
    op.execute(f"ALTER TABLE {S}.bots ALTER COLUMN owner_id TYPE varchar USING owner_id::text")
    op.drop_index("ix_auth_sessions_expires_at", "auth_sessions", schema=S)
    op.drop_index("ix_auth_sessions_user_id", "auth_sessions", schema=S)
    op.drop_table("auth_sessions", schema=S)
    op.drop_table("users", schema=S)
