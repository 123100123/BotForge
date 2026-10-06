"""Event cards for Telegram groups (Business OS, Telegram groups & documents).

A card is the group message of one event: built by the pure ``booking.render_group_card`` from the
item record and its confirmed count read from a store, with ONE ``book:<item id>`` button. Two
callers: ``api/groups.py`` renders the card it queues for a group (publish), and
``services/dispatch.py`` renders it again after an RSVP from a group so the posted card shows the new
count (the message is edited in place).

Only booking capabilities with the events preset have cards. Reads only; never commits.
"""

from datetime import datetime
from typing import TypeGuard

from app.botspec.models import AnyCapability, BookingCapability, BotSpec
from app.runtime.contracts import Button
from app.runtime.engines.booking import CONFIRMED, BookingEngine, render_group_card
from app.runtime.store import Store

Card = tuple[str, list[list[Button]]]


def is_events_capability(cap: AnyCapability | None) -> TypeGuard[BookingCapability]:
    """Whether ``cap`` is a booking capability with the events preset (the only kind with cards)."""
    return isinstance(cap, BookingCapability) and cap.preset == "events"


def find_events_capability(spec: BotSpec, collection: str) -> BookingCapability | None:
    """The enabled events capability whose bookable items are records of ``collection``, if any."""
    for cap in spec.capabilities:
        if is_events_capability(cap) and cap.enabled and cap.resource == collection:
            return cap
    return None


async def render_for_item(
    store: Store, spec: BotSpec, cap: BookingCapability, item_id: int, *, now: datetime
) -> Card | None:
    """``(text, buttons)`` of the card of item ``item_id`` of ``cap`` as the store holds it now, or
    ``None`` when the item does not exist. ``store`` is bound to the bot and env the card is for (the
    live ``PgStore`` in production). The text is plain: the sender escapes it."""
    item = await store.get_record(cap.resource, item_id)
    if item is None:
        return None
    going = await store.count_records(cap.key, status_in=[CONFIRMED], item_id=item.id)
    # The engine's own reading of the capacity (fixed, or the item's field; 0 when unknown), so the
    # card and the booking checks never disagree. 0 is shown as "N people going" without a limit.
    capacity = BookingEngine._capacity(cap, item)
    return render_group_card(
        cap,
        item,
        going,
        capacity if capacity > 0 else None,
        now=now,
        resource=spec.resource(cap.resource),
        tz=spec.bot.timezone,
    )
