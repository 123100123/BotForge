"""SQLAlchemy models for the Postgres schema ``app`` (see roadmap, "Database Schema")."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, MetaData, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "app"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Bot(Base):
    __tablename__ = "bots"
    __table_args__ = (Index("ix_bots_owner_id", "owner_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String, nullable=False)  # Supabase user id
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
    tg_bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    tg_username: Mapped[str | None] = mapped_column(String, nullable=True)
    tg_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    tg_webhook_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_link_code: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)  # owner's Telegram user id
    # Most recent Telegram delivery failure ("<method>: <description>"); never contains the token.
    tg_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.bots.id", ondelete="CASCADE"), primary_key=True
    )
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
