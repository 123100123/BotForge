"""Data admin: collections of the ACTIVE revision, live records, resource-record CRUD.

Resource collections (owner-managed items) are writable here. Booking and request collections are
read-only in this module; their action endpoint belongs to a later work package. All record access
goes through ``PgStore`` bound to ``env="live"``.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_bot
from app.botspec.models import BookingCapability, BotSpec, FieldDef, RequestCapability, Resource
from app.botspec.records import validate_record_detailed
from app.db.models import Bot, BotUser, Revision
from app.db.session import get_session
from app.runtime.pg_store import PgStore, advisory_lock
from app.runtime.store import Record

router = APIRouter(tags=["data"])

# Statuses of a booking record that still hold a seat / queue position.
ACTIVE_BOOKING_STATUSES = ["confirmed", "waitlisted"]

# Largest id the database stores (bigint); anything above is rejected at the edge.
MAX_ID = 2**63 - 1
RecordId = Path(ge=1, le=MAX_ID)

BOOKING_STATUSES = [
    ("confirmed", "قطعی"),
    ("waitlisted", "در لیست انتظار"),
    ("cancelled", "لغو شده"),
]
BOOKING_CANCEL_LABEL = "لغو ثبت‌نام"

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


class StatusOut(BaseModel):
    key: str
    label: str


class ActionDefOut(BaseModel):
    key: str
    label: str
    from_statuses: list[str]


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
    timezone: str = "Asia/Tehran"
    statuses: list[StatusOut] = []  # booking / request only
    actions: list[ActionDefOut] = []  # owner actions; booking / request only


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
    actor_name: str | None = None  # booking / request: the customer's display name
    item_title: str | None = None  # booking / request with an item: the item's title-field value


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
    # The FK does not tie the active revision to this bot; never serve another bot's spec.
    if revision is None or revision.bot_id != bot.id:
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
                timezone=spec.bot.timezone,
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
                    timezone=spec.bot.timezone,
                    statuses=[StatusOut(key=k, label=label) for k, label in BOOKING_STATUSES],
                    actions=[
                        ActionDefOut(
                            key="cancel", label=BOOKING_CANCEL_LABEL, from_statuses=ACTIVE_BOOKING_STATUSES
                        )
                    ],
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
                    timezone=spec.bot.timezone,
                    statuses=[StatusOut(key=st.key, label=st.label) for st in cap.statuses],
                    actions=[
                        ActionDefOut(key=a.key, label=a.label, from_statuses=list(a.from_statuses))
                        for a in cap.owner_actions
                    ],
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


def _invalid(errors: list[tuple[str | None, str]]) -> JSONResponse:
    """The 400 body. ``details`` stays the list of Persian messages; ``field_errors`` adds the field key
    (``None`` for a record-level problem). Returned, not raised: the shared error handler only forwards
    ``details``."""
    messages = [message for _, message in errors]
    body = {
        "code": "invalid_record",
        "message": "داده‌های واردشده نامعتبر است: " + " ".join(messages),
        "details": messages,
        "field_errors": [{"field": field, "message": message} for field, message in errors],
    }
    return JSONResponse({"error": body}, status_code=400)


async def _enrich(
    session: AsyncSession, bot: Bot, spec: BotSpec, collection: str, records: list[Record]
) -> list[RecordOut]:
    """Records as API rows. Booking / request rows get ``actor_name`` and ``item_title``, resolved
    with one query each for the whole page (display names from ``bot_users``; item titles from one
    list of the item resource), so there is no per-row lookup."""
    out = [_record_out(r) for r in records]
    cap = spec.capability(collection)
    if not records or not isinstance(cap, BookingCapability | RequestCapability):
        return out
    actor_ids = {r.actor_id for r in records if r.actor_id}
    names: dict[str, str] = {}
    if actor_ids:
        rows = await session.execute(
            select(BotUser.actor_id, BotUser.display_name).where(
                BotUser.bot_id == bot.id, BotUser.env == "live", BotUser.actor_id.in_(actor_ids)
            )
        )
        names = {actor_id: name for actor_id, name in rows.all()}
    titles: dict[int, str | None] = {}
    resource_key = cap.resource if isinstance(cap, BookingCapability) else cap.item_resource
    resource = spec.resource(resource_key) if resource_key else None
    if resource is not None and any(r.item_id is not None for r in records):
        items = await PgStore(session, bot.id, "live", bot.owner_actor_id).list_records(resource.key)
        for item in items:
            value = item.data.get(resource.title_field)
            titles[item.id] = None if value is None else str(value)
    for row in out:
        row.actor_name = names.get(row.actor_id) if row.actor_id else None
        row.item_title = titles.get(row.item_id) if row.item_id is not None else None
    return out


@router.get("/bots/{bot_id}/data", response_model=DataOut)
async def list_collections(
    bot: Bot = Depends(get_owned_bot), session: AsyncSession = Depends(get_session)
) -> DataOut:
    return DataOut(collections=_collections(await _active_spec(session, bot)))


@router.get("/bots/{bot_id}/data/{collection}", response_model=RecordsPage)
async def list_records(
    collection: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=MAX_ID),
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> RecordsPage:
    spec = await _active_spec(session, bot)
    _find(spec, collection)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    total = await store.count_records(collection)
    records = await store.list_records(collection, order_by="-id", limit=limit, offset=offset)
    return RecordsPage(
        collection=collection,
        total=total,
        limit=limit,
        offset=offset,
        items=await _enrich(session, bot, spec, collection, records),
    )


@router.post("/bots/{bot_id}/data/{collection}", response_model=RecordOut, status_code=201)
async def create_record(
    collection: str,
    body: RecordBody,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> RecordOut | JSONResponse:
    resource = _resource(await _active_spec(session, bot), collection)
    cleaned, errors = validate_record_detailed(resource.fields, body.data)
    if errors:
        return _invalid(errors)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    record = await store.create_record(collection, cleaned, now=datetime.now(UTC))
    await session.commit()  # before responding; get_session's own commit runs after the response
    return _record_out(record)


@router.patch("/bots/{bot_id}/data/{collection}/{record_id}", response_model=RecordOut)
async def update_record(
    collection: str,
    body: RecordBody,
    record_id: int = RecordId,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
) -> RecordOut | JSONResponse:
    resource = _resource(await _active_spec(session, bot), collection)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    existing = await store.get_record(collection, record_id)
    if existing is None:
        raise _err(404, "record_not_found", "این رکورد پیدا نشد.")
    # Partial update: fields not mentioned keep their stored value; keys of removed fields survive
    # because update_record merges shallowly.
    cleaned, errors = validate_record_detailed(resource.fields, {**existing.data, **body.data})
    if errors:
        return _invalid(errors)
    record = await store.update_record(collection, record_id, data=cleaned, now=datetime.now(UTC))
    await session.commit()
    return _record_out(record)


@router.delete("/bots/{bot_id}/data/{collection}/{record_id}", status_code=204)
async def delete_record(
    collection: str,
    record_id: int = RecordId,
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
