"""Event reminders: one outbox row per confirmed booking whose item starts within
``reminder_hours_before`` hours (both booking presets; the capability needs ``start_field``).

Window: ``now < start <= now + reminder_hours_before``. Dedupe key ``rem:<booking_id>:<start_iso>``
(``start_iso`` = the item's start in UTC, ISO format), so each booking is reminded once per start
time, and moving the item to a new start inside the window reminds again. Live environment only,
and only bots connected to Telegram (with no token nothing could be delivered; once connected, the
next tick still finds every upcoming start inside its window). Waitlisted and cancelled bookings
get nothing. Records are only read.

Item starts are stored as UTC ISO strings in JSONB with no guaranteed format, so the window is
applied in Python after reading the resource's items (cheap for the item counts a bot has); the SQL
filter only narrows the bots to those whose active spec asks for reminders.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BookingCapability, BotSpec, Resource
from app.db.models import Bot, RecordRow, Revision
from app.notifications.generators import active_spec
from app.notifications.outbox import Message, enqueue_many
from app.notifications.targets import chat_id_of
from app.runtime import formatting

log = logging.getLogger(__name__)

LIVE = "live"
CONFIRMED = "confirmed"
LOCATION_FIELDS = ("location", "place", "venue", "address")
_WANTS_REMINDERS = '$.capabilities[*] ? (@.type == "booking" && @.reminder_hours_before != null)'


def reminder_text(spec: BotSpec, resource: Resource, item: dict[str, object], start: datetime) -> str:
    """``یادآوری: «<title>» <Jalali date and time>`` plus ``، مکان: <location>`` when the resource has
    a location-like field with a value."""
    title = str(item.get(resource.title_field) or resource.label)
    text = f"یادآوری: «{title}» {formatting.format_datetime(start, spec.bot.timezone)}"
    for field in resource.fields:
        if field.key in LOCATION_FIELDS and item.get(field.key) not in (None, ""):
            text += f"، مکان: {formatting.format_field_value(field, item[field.key], spec.bot.timezone)}"
            break
    return text


async def _for_capability(
    session: AsyncSession, bot_id: object, spec: BotSpec, cap: BookingCapability, now: datetime
) -> list[Message]:
    resource = next((r for r in spec.resources if r.key == cap.resource), None)
    if resource is None or cap.start_field is None or not cap.reminder_hours_before:
        return []
    horizon = now + timedelta(hours=cap.reminder_hours_before)
    items = await session.execute(
        select(RecordRow.id, RecordRow.data).where(
            RecordRow.bot_id == bot_id, RecordRow.env == LIVE, RecordRow.collection == resource.key
        )
    )
    due: dict[int, tuple[dict[str, object], datetime]] = {}
    for item_id, data in items:
        start = formatting.parse_datetime(data.get(cap.start_field))
        if start is not None and now < start <= horizon:
            due[item_id] = (data, start)
    if not due:
        return []
    bookings = await session.execute(
        select(RecordRow.id, RecordRow.actor_id, RecordRow.item_id)
        .where(
            RecordRow.bot_id == bot_id,
            RecordRow.env == LIVE,
            RecordRow.collection == cap.key,
            RecordRow.status == CONFIRMED,
            RecordRow.item_id.in_(list(due)),
        )
        .order_by(RecordRow.id)
    )
    messages: list[Message] = []
    for booking_id, actor_id, item_id in bookings:
        chat_id = chat_id_of(actor_id)
        if chat_id is None:
            continue
        data, start = due[item_id]
        key = f"rem:{booking_id}:{start.astimezone(UTC).isoformat()}"
        messages.append(Message(chat_id, reminder_text(spec, resource, data, start), dedupe_key=key))
    return messages


async def generate(session: AsyncSession, now: datetime) -> None:
    bots = await session.execute(
        select(Bot)
        .join(Revision, Revision.id == Bot.active_revision_id)
        .where(
            Revision.bot_id == Bot.id,
            Bot.tg_token_enc.is_not(None),
            func.jsonb_path_exists(Revision.spec, cast(_WANTS_REMINDERS, JSONPATH)),
        )
    )
    for bot in bots.scalars().all():
        spec = await active_spec(session, bot)
        if spec is None:
            continue
        messages: list[Message] = []
        for cap in spec.capabilities:
            if isinstance(cap, BookingCapability) and cap.enabled and cap.reminder_hours_before:
                messages += await _for_capability(session, bot.id, spec, cap, now)
        inserted = await enqueue_many(session, bot_id=bot.id, env=LIVE, messages=messages)
        if inserted:
            log.info("bot %s: queued %d event reminders", bot.id, inserted)
