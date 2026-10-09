"""SQLAlchemy models for the Postgres schema ``app`` (see roadmap, "Database Schema")."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy import text as sql_text  # aliased: several tables have a column named "text"
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "app"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class User(Base):
    """An owner account. ``email`` is stored normalized (stripped, lowercased; see
    ``app.security.accounts.normalize_email``), so the unique constraint is case-insensitive in effect."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # argon2id (argon2-cffi)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuthSession(Base):
    """A login session. The cookie carries a random token; only its SHA-256 hex digest is stored.

    Not to be confused with ``sessions`` (``SessionRow``), the bots' conversation state."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Bot(Base):
    __tablename__ = "bots"
    __table_args__ = (
        Index("ix_bots_owner_id", "owner_id"),
        Index("ux_bots_staff_link_code", "staff_link_code", unique=True),
        # A messenger bot id belongs to one BotForge bot per platform (Telegram and Bale ids may clash).
        UniqueConstraint("platform", "tg_bot_id", name="uq_bots_platform_tg_bot_id"),
        CheckConstraint("platform IN ('telegram', 'bale')", name="ck_bots_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The owning account; deleting the user deletes their bots (and, through the bots, everything else).
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE", name="fk_bots_owner_user"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")  # draft/live/paused
    # bots and revisions reference each other, hence use_alter
    active_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA}.revisions.id", ondelete="SET NULL", use_alter=True, name="fk_bots_active_revision"
        ),
        nullable=True,
    )
    # The messenger the bot runs on (app.integrations.telegram.platforms). The tg_* columns, the owner
    # link and the webhook secret hold that platform's values (Bale's API mirrors Telegram's).
    platform: Mapped[str] = mapped_column(
        String(16), nullable=False, default="telegram", server_default="telegram"
    )
    tg_bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tg_username: Mapped[str | None] = mapped_column(String, nullable=True)
    tg_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    tg_webhook_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_link_code: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)  # owner's Telegram user id
    # Most recent Telegram delivery failure ("<method>: <description>"); never contains the token.
    tg_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Polling mode only: the next getUpdates offset (last handled update_id + 1) for the stored token.
    # Cleared by connect and disconnect; unused in webhook mode.
    tg_poll_offset: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The code in the staff deep link (t.me/<bot>?start=staff_<code>): multi-use, rotatable, null when
    # revoked. Unique, so a code identifies exactly one bot.
    staff_link_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("bot_id", "number", name="uq_revisions_bot_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.revisions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requirements: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    patch: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    change_request: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenarios: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    superseded: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    test_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    sample_data: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecordRow(Base):
    __tablename__ = "records"
    __table_args__ = (
        Index("ix_records_collection", "bot_id", "env", "collection"),
        Index("ix_records_item_status", "bot_id", "env", "collection", "item_id", "status"),
        Index("ix_records_actor", "bot_id", "env", "collection", "actor_id"),
        Index("ix_records_created", "bot_id", "env", "collection", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    env: Mapped[str] = mapped_column(String, nullable=False)  # live / sandbox
    collection: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), primary_key=True
    )
    env: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BotUser(Base):
    __tablename__ = "bot_users"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), primary_key=True
    )
    env: Mapped[str] = mapped_column(String, primary_key=True)
    actor_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    # customer / staff / manager. The bot owner counts as a manager whatever this says.
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="customer", server_default="customer"
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_bot_created", "bot_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)  # create / modify
    phase: Mapped[str] = mapped_column(String, nullable=False)
    # running / waiting_user / waiting_approval / done / failed / rejected / interrupted
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.revisions.id", ondelete="SET NULL"), nullable=True
    )
    result_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.revisions.id", ondelete="SET NULL"), nullable=True
    )
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_run_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TgUpdate(Base):
    __tablename__ = "tg_updates"
    __table_args__ = (Index("ix_tg_updates_received_at", "received_at"),)  # the poller prunes by age

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), primary_key=True
    )
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- Business OS (migration 0005) -------------------------------------------------------------------

_EMPTY_OBJECT = sql_text("'{}'::jsonb")
_EMPTY_LIST = sql_text("'[]'::jsonb")


class OutboundMessageRow(Base):
    """One message in the notification outbox. Generators only insert; the ticker claims due rows
    (``status='queued' AND not_before <= now()``, ``FOR UPDATE SKIP LOCKED``) and sends them.
    ``dedupe_key`` is unique per bot (NULL never collides), so re-inserting a reminder is a no-op
    with ``ON CONFLICT DO NOTHING``."""

    __tablename__ = "outbound_messages"
    __table_args__ = (
        UniqueConstraint("bot_id", "dedupe_key", name="uq_outbound_messages_bot_dedupe"),
        Index("ix_outbound_messages_due", "status", "not_before"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    env: Mapped[str] = mapped_column(String(8), nullable=False)  # live / sandbox
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    buttons: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(  # queued / sent / failed
        String(12), nullable=False, default="queued", server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BotChatRow(Base):
    """A group, supergroup or channel the bot was added to (from ``my_chat_member``)."""

    __tablename__ = "bot_chats"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), primary_key=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # group / supergroup / channel
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BotModuleRow(Base):
    """Toggle and config of a capability that lives outside the BotSpec (``kind="module"`` in the
    capability registry). No row means the module's registry default."""

    __tablename__ = "bot_modules"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), primary_key=True
    )
    module: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_EMPTY_OBJECT
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AnnouncementRow(Base):
    """A broadcast the owner sent; its messages are queued in ``outbound_messages``."""

    __tablename__ = "announcements"
    __table_args__ = (Index("ix_announcements_bot_created", "bot_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # everyone / customers / staff / managers / subscribers
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    group_chat_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_EMPTY_LIST
    )
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued", server_default="queued")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UploadedFileRow(Base):
    """An uploaded spreadsheet. The bytes live in file storage under ``storage_key``;
    ``inspection`` is the deterministic workbook profile (``schemas.business.WorkbookInspection``)."""

    __tablename__ = "uploaded_files"
    __table_args__ = (Index("ix_uploaded_files_bot_created", "bot_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)  # web / telegram
    uploaded_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspection: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalysisProfileRow(Base):
    """A spreadsheet analysis profile: one per bot and column signature. ``metrics`` and ``checks``
    hold ``schemas.business.AnalysisMetricSpec`` / ``AnalysisCheckSpec`` dicts."""

    __tablename__ = "analysis_profiles"
    __table_args__ = (UniqueConstraint("bot_id", "signature", name="uq_analysis_profiles_bot_signature"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    sheet: Mapped[str] = mapped_column(Text, nullable=False)
    expected_columns: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_EMPTY_LIST
    )
    metrics: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=_EMPTY_LIST
    )
    checks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=_EMPTY_LIST)
    daily_report: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AnalysisRunRow(Base):
    """One deterministic run of a profile over an upload. Deleting the upload keeps the run
    (``upload_id`` becomes NULL); deleting the profile deletes its runs."""

    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_bot_profile_created", "bot_id", "profile_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.analysis_profiles.id", ondelete="CASCADE"), nullable=False
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.uploaded_files.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok / schema_changed / failed
    submitted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    schema_diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
