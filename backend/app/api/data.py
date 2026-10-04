"""Data admin: collections of the ACTIVE revision, live records, resource-record CRUD.

Resource collections (owner-managed items) are writable here. Booking and request collections are
read-only in this module; their action endpoint belongs to a later work package. All record access
goes through ``PgStore`` bound to ``env="live"``.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.botspec.models import BookingCapability, BotSpec, FieldDef, RequestCapability, Resource
from app.botspec.records import validate_record
from app.db.models import Bot, Revision
from app.db.session import get_session
from app.runtime.pg_store import PgStore, advisory_lock
from app.runtime.store import Record

router = APIRouter(tags=["data"])

# Statuses of a booking record that still hold a seat / queue position.
ACTIVE_BOOKING_STATUSES = ["confirmed", "waitlisted"]

SYSTEM_COLUMNS = {
    "actor_id": "کاربر",
    "item_id": "مورد",
    "status": "وضعیت",
    "created_at": "زمان",
}


def _err(status: int, code: str, message: str, details: Any = None) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        detail["details"] = details
    return HTTPException(status_code=status, detail=detail)


class SystemColumn(BaseModel):
    key: str
    label: str


class CollectionOut(BaseModel):
    key: str
    kind: str  # resource | booking | request
    label: str
    label_plural: str
    writable: bool
    fields: list[FieldDef]  # resource: its fields; booking/request: the form fields
    system_columns: list[SystemColumn]
    title_field: str | None = None  # resource only
    resource: str | None = None  # booking: bookable resource; request: item_resource


class DataOut(BaseModel):
    collections: list[CollectionOut]


class RecordOut(BaseModel):
    id: int
    collection: str
    data: dict[str, Any]
    status: str | None
    actor_id: str | None
    item_id: int | None
    created_at: datetime
    updated_at: datetime


class RecordsPage(BaseModel):
    collection: str
    total: int
    limit: int
    offset: int
    items: list[RecordOut]


class RecordBody(BaseModel):
    data: dict[str, Any]


def _record_out(record: Record) -> RecordOut:
    return RecordOut(**record.model_dump())


def _system_columns(has_item: bool) -> list[SystemColumn]:
    return [
        SystemColumn(key=k, label=label) for k, label in SYSTEM_COLUMNS.items() if has_item or k != "item_id"
    ]


async def _active_spec(session: AsyncSession, bot: Bot) -> BotSpec:
    revision = (
        await session.get(Revision, bot.active_revision_id) if bot.active_revision_id is not None else None
    )
    if revision is None:
        raise _err(409, "no_active_revision", "این ربات هنوز نسخهٔ فعالی ندارد.")
    return BotSpec.model_validate(revision.spec)


def _collections(spec: BotSpec) -> list[CollectionOut]:
    out: list[CollectionOut] = []
    for res in spec.resources:
        out.append(
            CollectionOut(
                key=res.key,
                kind="resource",
                label=res.label,
                label_plural=res.label_plural,
                writable=True,
                fields=res.fields,
                system_columns=[],
                title_field=res.title_field,
            )
        )
    for cap in spec.capabilities:
        if isinstance(cap, BookingCapability):
            out.append(
                CollectionOut(
                    key=cap.key,
                    kind="booking",
                    label=cap.title,
                    label_plural=cap.title,
                    writable=False,
                    fields=cap.form_fields,
                    system_columns=_system_columns(True),
                    resource=cap.resource,
                )
            )
        elif isinstance(cap, RequestCapability):
            out.append(
                CollectionOut(
                    key=cap.key,
                    kind="request",
                    label=cap.title,
                    label_plural=cap.title,
                    writable=False,
                    fields=cap.form_fields,
                    system_columns=_system_columns(cap.item_resource is not None),
                    resource=cap.item_resource,
                )
            )
    return out


def _find(spec: BotSpec, collection: str) -> CollectionOut:
    for col in _collections(spec):
        if col.key == collection:
            return col
    raise _err(404, "collection_not_found", "این مجموعه پیدا نشد.")


def _resource(spec: BotSpec, collection: str) -> Resource:
    """The resource behind a writable collection; 404 if unknown, 405 if read-only."""
    col = _find(spec, collection)
    if not col.writable:
        raise _err(405, "read_only_collection", "این مجموعه فقط برای مشاهده است.")
    return next(r for r in spec.resources if r.key == collection)


def _invalid(errors: list[str]) -> HTTPException:
    return _err(400, "invalid_record", "داده‌های واردشده نامعتبر است: " + " ".join(errors), errors)


@router.get("/bots/{bot_id}/data", response_model=DataOut)
async def list_collections(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> DataOut:
    return DataOut(collections=_collections(await _active_spec(session, bot)))


@router.get("/bots/{bot_id}/data/{collection}", response_model=RecordsPage)
async def list_records(
    collection: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> RecordsPage:
    _find(await _active_spec(session, bot), collection)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    total = await store.count_records(collection)
    records = await store.list_records(collection, order_by="-id", limit=limit, offset=offset)
    return RecordsPage(
        collection=collection,
        total=total,
        limit=limit,
        offset=offset,
        items=[_record_out(r) for r in records],
    )


@router.post("/bots/{bot_id}/data/{collection}", response_model=RecordOut, status_code=201)
async def create_record(
    collection: str,
    body: RecordBody,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> RecordOut:
    resource = _resource(await _active_spec(session, bot), collection)
    cleaned, errors = validate_record(resource.fields, body.data)
    if errors:
        raise _invalid(errors)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    record = await store.create_record(collection, cleaned, now=datetime.now(UTC))
    await session.commit()  # before responding; get_session's own commit runs after the response
    return _record_out(record)


@router.patch("/bots/{bot_id}/data/{collection}/{record_id}", response_model=RecordOut)
async def update_record(
    collection: str,
    record_id: int,
    body: RecordBody,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> RecordOut:
    resource = _resource(await _active_spec(session, bot), collection)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    existing = await store.get_record(collection, record_id)
    if existing is None:
        raise _err(404, "record_not_found", "این رکورد پیدا نشد.")
    # Partial update: fields not mentioned keep their stored value; keys of removed fields survive
    # because update_record merges shallowly.
    cleaned, errors = validate_record(resource.fields, {**existing.data, **body.data})
    if errors:
        raise _invalid(errors)
    record = await store.update_record(collection, record_id, data=cleaned, now=datetime.now(UTC))
    await session.commit()
    return _record_out(record)


@router.delete("/bots/{bot_id}/data/{collection}/{record_id}", status_code=204)
async def delete_record(
    collection: str,
    record_id: int,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> None:
    spec = await _active_spec(session, bot)
    _resource(spec, collection)
    await advisory_lock(session, bot.id)  # no booking may slip in between the check and the delete
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    if await store.get_record(collection, record_id) is None:
        raise _err(404, "record_not_found", "این رکورد پیدا نشد.")
    for cap in spec.capabilities:
        if isinstance(cap, BookingCapability) and cap.resource == collection:
            active = await store.count_records(cap.key, item_id=record_id, status_in=ACTIVE_BOOKING_STATUSES)
            if active:
                raise _err(
                    409,
                    "record_has_active_bookings",
                    "این مورد رزرو فعال یا در صف انتظار دارد و حذف نمی‌شود. ابتدا رزروها را لغو کنید.",
                )
    await store.delete_record(collection, record_id)
    await session.commit()
