"""In-memory ``Store`` for tests, the scenario runner and local runs (WP1).

Implements ``runtime.store.Store`` exactly (see that module's docstring for the rules). Extra
fidelity choices, so behavior matches a JSON-backed database store:
- record ``data`` and session state are round-tripped through JSON on write (a non-JSON value such
  as a ``datetime`` raises ``TypeError`` here just as it would in PgStore), and every read returns
  a copy, so callers can never mutate stored state by accident;
- ids are increasing integers starting at 1, shared across all collections;
- ``delete_record`` on a missing record is a no-op.
"""

import json
from collections.abc import Collection
from datetime import datetime
from typing import Any

from app.runtime.contracts import Actor
from app.runtime.store import Record

_ORDERS = ("id", "-id")


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


class MemoryStore:
    def __init__(self, owner_actor_id: str | None = "owner") -> None:
        self._owner_actor_id = owner_actor_id
        self._records: dict[int, Record] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._users: dict[str, Actor] = {}
        self._next_id = 1

    # --- inspection helpers (not part of the Store protocol) ---------------------------------

    @property
    def users(self) -> dict[str, Actor]:
        return {k: v.model_copy() for k, v in self._users.items()}

    def all_records(self) -> list[Record]:
        return [r.model_copy(deep=True) for r in sorted(self._records.values(), key=lambda r: r.id)]

    # --- records -----------------------------------------------------------------------------

    def _select(
        self,
        collection: str,
        status_in: list[str] | None,
        actor_id: str | None,
        item_id: int | None,
    ) -> list[Record]:
        out = []
        for rec in self._records.values():
            if rec.collection != collection:
                continue
            if status_in is not None and rec.status not in status_in:
                continue
            if actor_id is not None and rec.actor_id != actor_id:
                continue
            if item_id is not None and rec.item_id != item_id:
                continue
            out.append(rec)
        return out

    async def list_records(
        self,
        collection: str,
        *,
        status_in: list[str] | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
        order_by: str = "id",
        limit: int | None = None,
    ) -> list[Record]:
        if order_by not in _ORDERS:
            raise ValueError(f"order_by must be one of {_ORDERS}, got {order_by!r}")
        rows = sorted(
            self._select(collection, status_in, actor_id, item_id),
            key=lambda r: r.id,
            reverse=order_by == "-id",
        )
        if limit is not None:
            rows = rows[: max(limit, 0)]
        return [r.model_copy(deep=True) for r in rows]

    async def count_records(
        self,
        collection: str,
        *,
        status_in: list[str] | None = None,
        actor_id: str | None = None,
        item_id: int | None = None,
    ) -> int:
        return len(self._select(collection, status_in, actor_id, item_id))

    async def get_record(self, collection: str, record_id: int) -> Record | None:
        rec = self._records.get(record_id)
        if rec is None or rec.collection != collection:
            return None
        return rec.model_copy(deep=True)

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
        rec = Record(
            id=self._next_id,
            collection=collection,
            data=_json_copy(data),
            status=status,
            actor_id=actor_id,
            item_id=item_id,
            created_at=now,
            updated_at=now,
        )
        self._next_id += 1
        self._records[rec.id] = rec
        return rec.model_copy(deep=True)

    async def update_record(
        self,
        collection: str,
        record_id: int,
        *,
        data: dict[str, Any] | None = None,
        status: str | None = None,
        now: datetime,
    ) -> Record:
        rec = self._records.get(record_id)
        if rec is None or rec.collection != collection:
            raise KeyError(f"record {collection}/{record_id} not found")
        merged = {**rec.data, **_json_copy(data)} if data else dict(rec.data)
        updated = rec.model_copy(
            update={
                "data": merged,
                "status": status if status is not None else rec.status,
                "updated_at": now,
            }
        )
        self._records[record_id] = updated
        return updated.model_copy(deep=True)

    async def delete_record(self, collection: str, record_id: int) -> None:
        rec = self._records.get(record_id)
        if rec is not None and rec.collection == collection:
            del self._records[record_id]

    # --- sessions, users, owner --------------------------------------------------------------

    async def get_session(self, actor_id: str) -> dict[str, Any] | None:
        state = self._sessions.get(actor_id)
        return _json_copy(state) if state is not None else None

    async def set_session(self, actor_id: str, state: dict[str, Any] | None) -> None:
        if state is None:
            self._sessions.pop(actor_id, None)
        else:
            self._sessions[actor_id] = _json_copy(state)

    async def upsert_user(self, actor: Actor) -> None:
        self._users[actor.id] = actor.model_copy()

    async def owner_actor_id(self) -> str | None:
        return self._owner_actor_id

    # --- optional runtime services (not part of the Store protocol; see PgStore) ---------------

    async def display_names(self, actor_ids: Collection[str]) -> dict[str, str]:
        return {a: self._users[a].display_name for a in set(actor_ids) if a in self._users}
