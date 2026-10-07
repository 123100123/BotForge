"""Seed live demo data for the golden workshop bot (roadmap: Demo Preparation Checklist).

Usage (from backend/, with DATABASE_URL set):
    uv run python scripts/seed_demo.py --bot-id <uuid>            # seed (does nothing if already seeded)
    uv run python scripts/seed_demo.py --bot-id <uuid> --reset    # remove everything this script created

The bot must have an active revision with a booking capability over a resource with the fields of
``examples/workshop.botspec.json`` (title, description, teacher, starts_at, price). In the bot's LIVE
environment the script creates five upcoming workshops (Persian titles and teachers):

* one starting in 45 minutes, for the cancellation-deadline shot,
* one that is full (every seat confirmed) with three people on the waitlist,
* one partly booked, one with a single booking, one empty.

The bookings belong to demo customers with ids ``demo-*`` and Persian display names (``bot_users``).
Idempotent: a marker records the ids this script created, so a second run changes nothing and
``--reset`` removes exactly those workshops, their bookings (including any made on them since), the
demo customers and the marker. The marker is a ``sessions`` row for the actor ``__demo_seed__`` in a
bookkeeping environment of its own (``env = "demo_seed"``), not in ``live``: activating a revision
deletes every live session, and the marker must survive that. No runtime code reads that environment.
(A marker left in ``live`` by an older version of this script is still honoured by ``--reset``.)
All record writes go through ``PgStore``; the sandbox environment is never touched.
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.botspec.models import BookingCapability, FieldDef
from app.botspec.records import validate_record_detailed
from app.db.models import Bot, BotUser, SessionRow
from app.db.session import dispose_engine, get_sessionmaker
from app.runtime.contracts import Actor
from app.runtime.pg_store import PgStore, advisory_lock
from app.services.specs import load_active_spec

MARKER_ACTOR = "__demo_seed__"
MARKER_ENV = "demo_seed"  # not "live": activation clears live sessions (revisions.service.activate)
LEGACY_MARKER_ENV = "live"
DEMO_ACTOR_PREFIX = "demo-"
DEFAULT_CAPACITY = 10
STATUS_CONFIRMED = "confirmed"
STATUS_WAITLISTED = "waitlisted"

# Demo customers: (actor id, Persian display name). Enough for one full workshop plus its waitlist.
DEMO_CUSTOMERS: list[tuple[str, str]] = [
    ("demo-01", "علی رضایی"),
    ("demo-02", "سارا محمدی"),
    ("demo-03", "رضا کریمی"),
    ("demo-04", "مریم حسینی"),
    ("demo-05", "محمد احمدی"),
    ("demo-06", "فاطمه صادقی"),
    ("demo-07", "حسین موسوی"),
    ("demo-08", "زهرا نوری"),
    ("demo-09", "امیر جعفری"),
    ("demo-10", "نرگس رحیمی"),
    ("demo-11", "پارسا کاظمی"),
    ("demo-12", "الهام فرهادی"),
    ("demo-13", "کیان بهرامی"),
]


@dataclass(frozen=True)
class WorkshopPlan:
    title: str
    description: str
    teacher: str
    price: int
    days_ahead: int | None  # None: start in ``minutes_ahead`` minutes from now
    minutes_ahead: int | None
    hour: int  # local start hour for days_ahead plans
    confirmed: int  # how many demo customers hold a confirmed seat; -1 = every seat
    waitlisted: int = 0


PLANS: list[WorkshopPlan] = [
    WorkshopPlan(
        title="کارگاه فشردهٔ خوشنویسی نستعلیق",
        description="آشنایی با قلم‌گیری، نشستن حروف و تمرین جمله‌نویسی. مواد و کاغذ در کارگاه آماده است.",
        teacher="زهرا موسوی",
        price=900_000,
        days_ahead=None,
        minutes_ahead=45,
        hour=0,
        confirmed=2,
    ),
    WorkshopPlan(
        title="مبانی طراحی تجربهٔ کاربری",
        description="از پژوهش کاربر تا طراحی نمونهٔ اولیه؛ کارگاهی عملی با تمرین گروهی و بازخورد مستقیم.",
        teacher="مهدی کریمی",
        price=2_400_000,
        days_ahead=3,
        minutes_ahead=None,
        hour=10,
        confirmed=-1,
        waitlisted=3,
    ),
    WorkshopPlan(
        title="عکاسی حرفه‌ای با موبایل",
        description="نورپردازی، ترکیب‌بندی و ویرایش سریع عکس؛ همراه با پروژهٔ پایانی و نقد جمعی.",
        teacher="سارا احمدی",
        price=1_500_000,
        days_ahead=2,
        minutes_ahead=None,
        hour=16,
        confirmed=4,
    ),
    WorkshopPlan(
        title="برنامه‌نویسی پایتون برای مبتدیان",
        description="از نصب تا نوشتن اولین برنامه؛ مناسب کسانی که قبلاً برنامه‌نویسی نکرده‌اند.",
        teacher="امید شفیعی",
        price=3_200_000,
        days_ahead=5,
        minutes_ahead=None,
        hour=9,
        confirmed=0,
    ),
    WorkshopPlan(
        title="سفالگری و ساخت ظروف دست‌ساز",
        description="کار با چرخ سفالگری، شکل‌دهی و لعاب‌کاری؛ آثار شرکت‌کنندگان پس از پخت تحویل داده می‌شود.",
        teacher="لیلا بهرامی",
        price=2_000_000,
        days_ahead=7,
        minutes_ahead=None,
        hour=14,
        confirmed=1,
    ),
]


async def _get_marker(session: AsyncSession, bot_id: uuid.UUID, env: str) -> dict[str, Any] | None:
    stmt = select(SessionRow.state).where(
        SessionRow.bot_id == bot_id, SessionRow.env == env, SessionRow.actor_id == MARKER_ACTOR
    )
    state = (await session.execute(stmt)).scalar_one_or_none()
    return dict(state) if state is not None else None


async def _set_marker(session: AsyncSession, bot_id: uuid.UUID, state: dict[str, Any]) -> None:
    stmt = pg_insert(SessionRow).values(bot_id=bot_id, env=MARKER_ENV, actor_id=MARKER_ACTOR, state=state)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SessionRow.bot_id, SessionRow.env, SessionRow.actor_id],
        set_={"state": stmt.excluded.state},
    )
    await session.execute(stmt)


async def _delete_markers(session: AsyncSession, bot_id: uuid.UUID) -> None:
    await session.execute(
        delete(SessionRow).where(
            SessionRow.bot_id == bot_id,
            SessionRow.env.in_([MARKER_ENV, LEGACY_MARKER_ENV]),
            SessionRow.actor_id == MARKER_ACTOR,
        )
    )


async def _find_marker(session: AsyncSession, bot_id: uuid.UUID) -> dict[str, Any] | None:
    marker = await _get_marker(session, bot_id, MARKER_ENV)
    if marker is None:
        marker = await _get_marker(session, bot_id, LEGACY_MARKER_ENV)
    return marker


class SeedError(Exception):
    """The bot cannot be seeded; the message says why."""


@dataclass
class SeedResult:
    seeded: bool  # False: the marker was already there and nothing changed
    workshop_ids: list[int] = field(default_factory=list)
    booking_ids: list[int] = field(default_factory=list)
    actor_ids: list[str] = field(default_factory=list)


def _start_time(plan: WorkshopPlan, now: datetime, tz: ZoneInfo) -> datetime:
    if plan.minutes_ahead is not None:
        return now + timedelta(minutes=plan.minutes_ahead)
    assert plan.days_ahead is not None
    local = (now.astimezone(tz) + timedelta(days=plan.days_ahead)).replace(
        hour=plan.hour, minute=0, second=0, microsecond=0
    )
    return local.astimezone(UTC)


async def _booking_target(
    session: AsyncSession, bot: Bot
) -> tuple[BookingCapability, list[FieldDef], ZoneInfo]:
    active = await load_active_spec(session, bot)
    if active is None:
        raise SeedError("the bot has no active revision; load one first (scripts/load_spec.py)")
    _, spec = active
    cap = next((c for c in spec.capabilities if isinstance(c, BookingCapability)), None)
    if cap is None:
        raise SeedError("the active revision has no booking capability")
    resource = spec.resource(cap.resource)
    if resource is None:
        raise SeedError("the booking capability's resource is missing from the spec")
    return cap, resource.fields, ZoneInfo(spec.bot.timezone)


async def seed(session: AsyncSession, bot: Bot, now: datetime | None = None) -> SeedResult:
    """Create the demo data (caller commits). Does nothing when the marker already exists."""
    now = now or datetime.now(UTC)
    cap, fields, tz = await _booking_target(session, bot)
    await advisory_lock(session, bot.id)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    if await _find_marker(session, bot.id) is not None:
        return SeedResult(seeded=False)

    capacity = cap.capacity.value if cap.capacity.mode == "fixed" and cap.capacity.value else DEFAULT_CAPACITY
    result = SeedResult(seeded=True)

    for plan in PLANS:
        raw = {
            "title": plan.title,
            "description": plan.description,
            "teacher": plan.teacher,
            "price": plan.price,
            cap.start_field: _start_time(plan, now, tz),
        }
        if cap.capacity.mode == "per_item" and cap.capacity.field:
            raw[cap.capacity.field] = capacity
        data, errors = validate_record_detailed(fields, raw)
        if errors:
            raise SeedError("workshop data does not fit the spec: " + "; ".join(m for _, m in errors))
        workshop = await store.create_record(cap.resource, data, now=now)
        result.workshop_ids.append(workshop.id)

        seats = capacity if plan.confirmed < 0 else plan.confirmed
        customers = iter(DEMO_CUSTOMERS)
        # Every workshop draws from the start of the pool; the same customer may hold seats in
        # several workshops, which is what a real bot looks like too.
        for status, count in ((STATUS_CONFIRMED, seats), (STATUS_WAITLISTED, plan.waitlisted)):
            for _ in range(count):
                actor_id, name = next(customers)
                await store.upsert_user(Actor(id=actor_id, display_name=name))
                booking = await store.create_record(
                    cap.key, {}, status=status, actor_id=actor_id, item_id=workshop.id, now=now
                )
                result.booking_ids.append(booking.id)
                if actor_id not in result.actor_ids:
                    result.actor_ids.append(actor_id)

    await _set_marker(
        session,
        bot.id,
        {
            "workshops": result.workshop_ids,
            "bookings": result.booking_ids,
            "actors": result.actor_ids,
            "resource": cap.resource,
            "booking_collection": cap.key,
            "created_at": now.isoformat(),
        },
    )
    return result


async def reset(session: AsyncSession, bot: Bot) -> int:
    """Remove what ``seed`` created (caller commits). Returns the number of workshops removed."""
    await advisory_lock(session, bot.id)
    store = PgStore(session, bot.id, "live", bot.owner_actor_id)
    marker = await _find_marker(session, bot.id)
    if marker is None:
        return 0
    resource, collection = marker["resource"], marker["booking_collection"]
    for workshop_id in marker["workshops"]:
        # Bookings made on a demo workshop since seeding go with it; they would be orphans otherwise.
        for booking in await store.list_records(collection, item_id=workshop_id):
            await store.delete_record(collection, booking.id)
        await store.delete_record(resource, workshop_id)
    for booking_id in marker["bookings"]:
        await store.delete_record(collection, booking_id)
    if marker["actors"]:
        await session.execute(
            delete(BotUser).where(
                BotUser.bot_id == bot.id, BotUser.env == "live", BotUser.actor_id.in_(marker["actors"])
            )
        )
    await _delete_markers(session, bot.id)
    return len(marker["workshops"])


async def run(bot_id: uuid.UUID, do_reset: bool) -> int:
    try:
        async with get_sessionmaker()() as session:
            bot = await session.get(Bot, bot_id)
            if bot is None:
                print("bot not found", file=sys.stderr)
                return 1
            if do_reset:
                removed = await reset(session, bot)
                await session.commit()
                message = f"removed {removed} demo workshops and their bookings"
                print(message if removed else "nothing to remove")
                return 0
            try:
                result = await seed(session, bot)
            except SeedError as exc:
                await session.rollback()
                print(f"cannot seed: {exc}", file=sys.stderr)
                return 1
            await session.commit()
            if result.seeded:
                print(
                    f"seeded {len(result.workshop_ids)} workshops, {len(result.booking_ids)} bookings, "
                    f"{len(result.actor_ids)} demo customers"
                )
            else:
                print("already seeded; nothing changed (use --reset to remove the demo data)")
            return 0
    finally:
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--bot-id", required=True, type=uuid.UUID)
    parser.add_argument("--reset", action="store_true", help="remove the demo data this script created")
    args = parser.parse_args()
    return asyncio.run(run(args.bot_id, args.reset))


if __name__ == "__main__":
    raise SystemExit(main())
