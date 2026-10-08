"""Postgres-backed ``Store`` bound to one ``(bot_id, env)``.

Every query filters by ``bot_id`` AND ``env``. The store never commits: the caller (request
dependency, dispatch service) owns the transaction.
"""

import hashlib
import uuid
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, BotChatRow, BotUser, RecordRow, SessionRow
from app.runtime.contracts import Actor, Button
from app.runtime.store import Record

if TYPE_CHECKING:
    from app.schemas.business import TeamOut

Env = Literal["live", "sandbox"]
MAX_GROUP_CHATS = 20


def advisory_key(bot_id: uuid.UUID | str) -> int:
    """Stable signed 64-bit key for a bot id (the same bot always maps to the same lock)."""
    value = uuid.UUID(str(bot_id))
    digest = hashlib.blake2b(value.bytes, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


async def advisory_lock(session: AsyncSession, bot_id: uuid.UUID | str) -> None:
    """Take the transaction-scoped advisory lock for ``bot_id`` (released at commit/rollback)."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": advisory_key(bot_id)})


def _to_record(row: RecordRow) -> Record:
    return Record(
        id=row.id,
        collection=row.collection,
        data=dict(row.data),
        status=row.status,
        actor_id=row.actor_id,
        item_id=row.item_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgStore:
    def __init__(
        self,
        session: AsyncSession,
        bot_id: uuid.UUID | str,
        env: Env,
        owner_actor_id: str | None = None,
    ) -> None:
        self._session = session
        self._bot_id = uuid.UUID(str(bot_id))
        self._env: str = env
        self._owner_actor_id = owner_actor_id

    # ------------------------------------------------------------------ records

    def _scope(self, collection: str) -> list[Any]:
        return [
            RecordRow.bot_id == self._bot_id,
            RecordRow.env == self._env,
            RecordRow.collection == collection,
        ]

    @staticmethod
    def _filters(status_in: list[str] | None, actor_id: str | None, item_id: int | None) -> list[Any]:
        conds: list[Any] = []
        if status_in is not None:
            conds.append(RecordRow.status.in_(status_in))
        if actor_id is not None:
            conds.append(RecordRow.actor_id == actor_id)
        if item_id is not None:
            conds.append(RecordRow.item_id == item_id)
        return conds

    async def list_records(
        self,
        collection: str,
        *,
        status_in: list[str] | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
        order_by: str = "id",
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Record]:
        if order_by not in ("id", "-id"):
            raise ValueError(f"order_by must be 'id' or '-id', got {order_by!r}")
        stmt = (
            select(RecordRow)
            .where(*self._scope(collection), *self._filters(status_in, actor_id, item_id))
            .order_by(RecordRow.id.desc() if order_by == "-id" else RecordRow.id.asc())
            .execution_options(populate_existing=True)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_record(r) for r in rows]

    async def count_records(
        self,
        collection: str,
        *,
        status_in: list[str] | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(RecordRow)
        stmt = stmt.where(*self._scope(collection), *self._filters(status_in, actor_id, item_id))
        return int((await self._session.execute(stmt)).scalar_one())

    async def _get_row(self, collection: str, record_id: int) -> RecordRow | None:
        stmt = (
            select(RecordRow)
            .where(*self._scope(collection), RecordRow.id == record_id)
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_record(self, collection: str, record_id: int) -> Record | None:
        row = await self._get_row(collection, record_id)
        return _to_record(row) if row is not None else None

    async def create_record(
        self,
        collection: str,
        data: dict[str, Any],
        *,
        status: str | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
        now: datetime,
    ) -> Record:
        row = RecordRow(
            bot_id=self._bot_id,
            env=self._env,
            collection=collection,
            data=dict(data),
            status=status,
            actor_id=actor_id,
            item_id=item_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_record(row)

    async def update_record(
        self,
        collection: str,
        record_id: int,
        *,
        data: dict[str, Any] | None = None,
        status: str | None = None,
        now: datetime,
    ) -> Record:
        row = await self._get_row(collection, record_id)
        if row is None:
            raise KeyError(record_id)
        if data is not None:
            row.data = {**row.data, **data}  # new dict: JSONB mutation is not tracked in place
        if status is not None:
            row.status = status
        row.updated_at = now
        await self._session.flush()
        return _to_record(row)

    async def delete_record(self, collection: str, record_id: int) -> None:
        stmt = delete(RecordRow).where(*self._scope(collection), RecordRow.id == record_id)
        await self._session.execute(stmt.execution_options(synchronize_session="fetch"))

    # ------------------------------------------------------------------ sessions

    async def get_session(self, actor_id: str) -> dict[str, Any] | None:
        stmt = select(SessionRow.state).where(
            SessionRow.bot_id == self._bot_id,
            SessionRow.env == self._env,
            SessionRow.actor_id == actor_id,
        )
        state = (await self._session.execute(stmt)).scalar_one_or_none()
        return dict(state) if state is not None else None

    async def set_session(self, actor_id: str, state: dict[str, Any] | None) -> None:
        if state is None:
            await self._session.execute(
                delete(SessionRow).where(
                    SessionRow.bot_id == self._bot_id,
                    SessionRow.env == self._env,
                    SessionRow.actor_id == actor_id,
                )
            )
            return
        stmt = pg_insert(SessionRow).values(
            bot_id=self._bot_id, env=self._env, actor_id=actor_id, state=state
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SessionRow.bot_id, SessionRow.env, SessionRow.actor_id],
            set_={"state": stmt.excluded.state, "updated_at": func.now()},
        )
        await self._session.execute(stmt)

    # ------------------------------------------------------------------ users / owner

    async def upsert_user(self, actor: Actor) -> None:
        stmt = pg_insert(BotUser).values(
            bot_id=self._bot_id, env=self._env, actor_id=actor.id, display_name=actor.display_name
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[BotUser.bot_id, BotUser.env, BotUser.actor_id],
            set_={"display_name": stmt.excluded.display_name},
        )
        await self._session.execute(stmt)

    async def owner_actor_id(self) -> str | None:
        return self._owner_actor_id

    # ------------------------------------------------------------------ optional runtime services
    # Not part of the frozen ``Store`` protocol: runtime modules detect them with ``getattr`` and
    # fall back when a store lacks them (``runtime/manager_events.py``: Telegram event management).

    async def display_names(self, actor_ids: Collection[str]) -> dict[str, str]:
        """``bot_users.display_name`` of these actors in this store's env (unknown ids left out)."""
        ids = sorted(set(actor_ids))
        if not ids:
            return {}
        stmt = select(BotUser.actor_id, BotUser.display_name).where(
            BotUser.bot_id == self._bot_id, BotUser.env == self._env, BotUser.actor_id.in_(ids)
        )
        return {actor_id: name for actor_id, name in (await self._session.execute(stmt)).all()}

    async def group_chats(self) -> list[tuple[int, str]]:
        """``(chat_id, title)`` of the groups the bot is an active member of, newest first; always
        empty outside ``live`` (the simulator never posts into real groups)."""
        if self._env != "live":
            return []
        stmt = (
            select(BotChatRow.chat_id, BotChatRow.title)
            .where(BotChatRow.bot_id == self._bot_id, BotChatRow.active.is_(True))
            .order_by(BotChatRow.added_at.desc(), BotChatRow.chat_id)
            .limit(MAX_GROUP_CHATS)
        )
        return [(chat_id, title) for chat_id, title in (await self._session.execute(stmt)).all()]

    async def enqueue_outbox(
        self, chat_ids: Sequence[int], text: str, buttons: list[list[Button]] | None = None
    ) -> bool:
        """Queue ``text`` for each chat in the notification outbox (sent by the ticker), in this
        transaction, so it is committed or rolled back with the event. Live only: returns False
        (nothing queued) for any other env, and the caller delivers some other way."""
        if self._env != "live":
            return False
        from app.notifications.outbox import Message, enqueue_many  # outbox imports runtime.contracts

        messages = [Message(chat_id=c, text=text, buttons=buttons) for c in dict.fromkeys(chat_ids)]
        if messages:
            await enqueue_many(self._session, bot_id=self._bot_id, env="live", messages=messages)
        return True

    async def enqueue_card(self, chat_id: int, text: str, buttons: list[list[Button]]) -> bool | None:
        """Queue an event card for one group unless the same card (same ``book:`` button) is still
        waiting in the outbox. True when queued, False when one already was, None outside ``live``
        (nothing queued; the caller delivers some other way)."""
        if self._env != "live":
            return None
        from app.notifications.outbox import enqueue_unless_queued

        return await enqueue_unless_queued(
            self._session, bot_id=self._bot_id, env="live", chat_id=chat_id, text=text, buttons=buttons
        )

    async def team_overview(self) -> "TeamOut | None":
        """The live bot's team as the Team API shows it (``roles.service.team_of``): staff link,
        members, role counts. None when the bot row is gone."""
        from app.roles.service import team_of  # roles.service imports this module

        bot = await self._session.get(Bot, self._bot_id)
        return await team_of(self._session, bot) if bot is not None else None
