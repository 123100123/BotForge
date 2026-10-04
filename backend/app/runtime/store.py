"""Store protocol and Record (frozen contract, WP0). Implementations: MemoryStore, PgStore.

A store instance is bound to one ``(bot_id, env)`` and adds both to every query.

Semantics every implementation must honor (checked by the shared store contract suite):
- Record ids are positive integers, unique per store, increasing in creation order.
- ``order_by`` is ``"id"`` (ascending) or ``"-id"`` (descending); ``id`` order equals creation
  order, so "oldest waitlisted first" is ``order_by="id"``.
- ``create_record``/``update_record`` set ``created_at``/``updated_at`` from the ``now`` argument;
  stores never read the clock.
- ``update_record`` merges ``data`` keys into the existing data (shallow) and replaces ``status``
  when given; it raises ``KeyError`` if the record does not exist.
- Sessions: one per ``actor_id``; ``set_session(actor_id, None)`` deletes it.
- ``owner_actor_id()`` returns a value bound at store construction: ``"owner"`` in MemoryStore and
  in the sandbox; the linked owner's Telegram user id in live, or None if no owner is linked.
- V1 is private chats only, so an actor's Telegram chat id equals ``actor.id``.
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel

from app.runtime.contracts import Actor


class Record(BaseModel):
    id: int
    collection: str  # resource key or capability key
    data: dict[str, Any]
    status: str | None = None
    actor_id: str | None = None
    item_id: int | None = None
    created_at: datetime
    updated_at: datetime


class Store(Protocol):
    async def list_records(
        self,
        collection: str,
        *,
        status_in: list[str] | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
        order_by: str = "id",
        limit: int | None = None,
    ) -> list[Record]: ...

    async def count_records(
        self,
        collection: str,
        *,
        status_in: list[str] | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
    ) -> int: ...

    async def get_record(self, collection: str, record_id: int) -> Record | None: ...

    async def create_record(
        self,
        collection: str,
        data: dict[str, Any],
        *,
        status: str | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
        now: datetime,
    ) -> Record: ...

    async def update_record(
        self,
        collection: str,
        record_id: int,
        *,
        data: dict[str, Any] | None = None,
        status: str | None = None,
        now: datetime,
    ) -> Record: ...

    async def delete_record(self, collection: str, record_id: int) -> None: ...

    async def get_session(self, actor_id: str) -> dict[str, Any] | None: ...

    async def set_session(self, actor_id: str, state: dict[str, Any] | None) -> None: ...

    async def upsert_user(self, actor: Actor) -> None: ...

    async def owner_actor_id(self) -> str | None: ...
