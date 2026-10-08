"""The notification outbox (``outbound_messages``): enqueue, claim, and record delivery results.

Generators and other producers only ``enqueue`` (or ``enqueue_many``). The ticker ``claim_due``s a
batch with ``FOR UPDATE SKIP LOCKED`` and keeps the transaction open while it sends that batch, so a
second ticker (or a future worker process) can never claim the same row; ``mark_sent`` and
``mark_failed`` change the claimed ORM rows and the caller commits once per batch.

Delivery is at least once: a crash after a send but before the batch commits leaves the row queued
and it is sent again. Batches are small (see ``ticker``), which bounds that window.

Idempotency: ``dedupe_key`` is unique per bot (``uq_outbound_messages_bot_dedupe``; NULL never
collides), and inserts use ``ON CONFLICT DO NOTHING``, so a generator may re-enqueue the same
logical message on every tick. Nothing here ever writes ``bots.tg_last_error``: outbox failures are
logged and kept in the row's ``last_error``.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboundMessageRow
from app.runtime.contracts import Button

Env = Literal["live", "sandbox"]

QUEUED = "queued"
SENT = "sent"
FAILED = "failed"
MAX_ATTEMPTS = 5
BACKOFF_BASE = timedelta(seconds=30)  # 30 s, 1 min, 2 min, 4 min between the five attempts
BACKOFF_CAP = timedelta(hours=1)
MAX_ERROR_CHARS = 500
INSERT_CHUNK = 1000  # rows per INSERT (9 parameters each; asyncpg allows 32767 per statement)

ButtonRows = Sequence[Sequence[Button | dict[str, Any]]]


def buttons_json(buttons: ButtonRows | None) -> list[list[dict[str, str]]] | None:
    """Inline buttons in ``OutMessage.buttons`` shape (rows of ``{"label", "data"}``), validated by
    ``Button`` (callback data <= 64 bytes). Empty rows are dropped; no rows is ``None``."""
    if not buttons:
        return None
    rows = [
        [(b if isinstance(b, Button) else Button.model_validate(b)).model_dump() for b in row]
        for row in buttons
        if row
    ]
    return rows or None


@dataclass
class Message:
    """One message for ``enqueue_many``."""

    chat_id: int
    text: str
    buttons: ButtonRows | None = None
    dedupe_key: str | None = None
    not_before: datetime | None = None


def _values(bot_id: uuid.UUID, env: Env, message: Message) -> dict[str, Any]:
    return {
        "bot_id": bot_id,
        "env": env,
        "chat_id": int(message.chat_id),
        "text": message.text,
        "buttons": buttons_json(message.buttons),
        "dedupe_key": message.dedupe_key,
        "not_before": message.not_before or datetime.now(UTC),
        "status": QUEUED,
        "attempts": 0,
    }


async def enqueue_many(
    session: AsyncSession, *, bot_id: uuid.UUID, env: Env, messages: Sequence[Message]
) -> int:
    """Insert ``messages`` for one bot; rows whose ``(bot_id, dedupe_key)`` exists are skipped.
    Returns how many rows were inserted. The caller commits."""
    inserted = 0
    for start in range(0, len(messages), INSERT_CHUNK):  # asyncpg caps one statement's parameters
        stmt = (
            pg_insert(OutboundMessageRow)
            .values([_values(bot_id, env, m) for m in messages[start : start + INSERT_CHUNK]])
            .on_conflict_do_nothing(constraint="uq_outbound_messages_bot_dedupe")
            .returning(OutboundMessageRow.id)
        )
        inserted += len((await session.execute(stmt)).all())
    return inserted


async def enqueue(
    session: AsyncSession,
    *,
    bot_id: uuid.UUID,
    env: Env,
    chat_id: int,
    text: str,
    buttons: ButtonRows | None = None,
    dedupe_key: str | None = None,
    not_before: datetime | None = None,
) -> bool:
    """Queue one message. ``False`` when a row with the same ``dedupe_key`` already exists for the
    bot (whatever its status). The caller commits."""
    message = Message(chat_id, text, buttons, dedupe_key, not_before)
    return await enqueue_many(session, bot_id=bot_id, env=env, messages=[message]) == 1


async def enqueue_unless_queued(
    session: AsyncSession,
    *,
    bot_id: uuid.UUID,
    env: Env,
    chat_id: int,
    text: str,
    buttons: ButtonRows,
) -> bool:
    """Queue a message unless an identical one is still waiting to be sent: same bot, env, chat and
    buttons (an event card is identified by its ``book:<item id>`` button, whatever its count says).
    ``False`` when one is queued. Once it is sent (or failed) the same card can be queued again, which
    a ``dedupe_key`` could not allow. Two requests at once are serialized per bot and chat with a
    transaction-scoped advisory lock. The caller commits."""
    wanted = buttons_json(buttons)
    await session.execute(
        sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"outbox-card:{bot_id}:{chat_id}"},
    )
    waiting = await session.scalar(
        select(OutboundMessageRow.id)
        .where(
            OutboundMessageRow.bot_id == bot_id,
            OutboundMessageRow.env == env,
            OutboundMessageRow.chat_id == int(chat_id),
            OutboundMessageRow.status == QUEUED,
            OutboundMessageRow.buttons == wanted,
        )
        .limit(1)
    )
    if waiting is not None:
        return False
    return await enqueue(session, bot_id=bot_id, env=env, chat_id=chat_id, text=text, buttons=buttons)


async def claim_due(
    session: AsyncSession,
    limit: int,
    *,
    only_bots: Collection[uuid.UUID] | None = None,
    skip_bots: Collection[uuid.UUID] = (),
) -> list[OutboundMessageRow]:
    """Lock and return up to ``limit`` queued rows that are due (``not_before <= now()``), oldest
    first. Rows another transaction holds are skipped, not waited for. The locks last until the
    caller's transaction ends. ``only_bots`` restricts and ``skip_bots`` excludes bots (a bot that
    Telegram is rate limiting is skipped until its wait is over)."""
    stmt = (
        select(OutboundMessageRow)
        .where(OutboundMessageRow.status == QUEUED, OutboundMessageRow.not_before <= func.now())
        .order_by(OutboundMessageRow.not_before, OutboundMessageRow.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if only_bots is not None:
        stmt = stmt.where(OutboundMessageRow.bot_id.in_(list(only_bots)))
    if skip_bots:
        stmt = stmt.where(OutboundMessageRow.bot_id.not_in(list(skip_bots)))
    return list((await session.execute(stmt)).scalars().all())


def mark_sent(row: OutboundMessageRow, *, now: datetime | None = None) -> None:
    row.status = SENT
    row.attempts = (row.attempts or 0) + 1
    row.sent_at = now or datetime.now(UTC)
    row.last_error = None


def backoff(attempts: int) -> timedelta:
    """Wait before the next attempt after ``attempts`` failed ones: 30 s doubling, capped."""
    return min(BACKOFF_CAP, BACKOFF_BASE * 2 ** max(attempts - 1, 0))


def mark_failed(
    row: OutboundMessageRow,
    error: str,
    *,
    now: datetime | None = None,
    retry_after: float | None = None,
    permanent: bool = False,
) -> None:
    """Record a failed attempt. The row is ``failed`` for good after ``MAX_ATTEMPTS`` attempts or when
    ``permanent`` (retrying cannot help: chat not found, bot blocked); otherwise it is requeued after
    the exponential backoff, or after Telegram's ``retry_after`` when that is longer."""
    row.attempts = (row.attempts or 0) + 1
    row.last_error = error[:MAX_ERROR_CHARS]
    if permanent or row.attempts >= MAX_ATTEMPTS:
        row.status = FAILED
        return
    wait = backoff(row.attempts)
    if retry_after is not None and retry_after > wait.total_seconds():
        wait = timedelta(seconds=retry_after)
    row.status = QUEUED
    row.not_before = (now or datetime.now(UTC)) + wait
