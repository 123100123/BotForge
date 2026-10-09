"""Roles storage, the staff invite link and the Team API helpers (roadmap: Roles).

Storage: ``bot_users.role`` per ``(bot_id, env, actor_id)``. The Team API and the staff link work on
the live bot (``env="live"``); the simulator's personas carry their own roles. ``PgStore.upsert_user``
(run for every event) writes only ``display_name`` on conflict, so a stored role survives every
later event. Decisions (unknown values, owner actions, what the staff link grants) are the pure
policy in ``app/roles/__init__.py``.

Serialization: every write here (a role change, rotating, revoking or redeeming the staff code) takes
the bot's advisory lock first: the lock ``dispatch`` holds while it reads the acting user's role and
runs the event. A change therefore lands between two events, never inside one: once the transaction
that made it commits, no event that read the old value is still running. The lock is
transaction-scoped and nothing here commits; the caller does.

Staff link: ``https://t.me/<bot username>?start=staff_<code>``. ``bots.staff_link_code`` is multi-use
(every staff member opens the same link), rotatable (a new code kills the old link) and revocable
(NULL). The code is a secret: 192 random bits, compared in constant time against the code of the bot
that received the update (never looked up across bots), never logged, and shown only to the
authenticated owner (Team API). Redeeming makes the sender staff of the live bot
(``role_after_staff_link``: idempotent, a manager stays a manager). A wrong, revoked or malformed code
changes nothing, and the sender gets one generic reply whatever the reason.

The owner's own role is never stored here (neither by the staff link nor by the Team API): the owner
is a manager by ownership, and a stored role would outlive it (once a reconnect links another
Telegram account, the old account would silently keep it).
"""

import hmac
import secrets
import uuid
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.botspec.models import Role
from app.db.models import Bot, BotUser
from app.integrations.telegram.platforms import bot_link
from app.roles import ROLES, TEAM_ROLES, parse_role, role_after_staff_link
from app.runtime.pg_store import Env, advisory_lock
from app.schemas.business import TeamMemberOut, TeamOut

LIVE: Env = "live"
STAFF_PAYLOAD_PREFIX = "staff_"  # the deep-link payload: /start staff_<code>
# secrets.token_urlsafe(24): 32 characters of A-Za-z0-9_- (192 random bits). Telegram allows up to 64
# characters of exactly that alphabet in a start payload; the column holds 64.
STAFF_CODE_BYTES = 24
MAX_MEMBERS = 500  # members listed by the Team API (counts cover everyone)

# Telegram replies to the staff link (sent by api/webhook.py). One reply for every failure: the sender
# learns nothing about why a code did not work.
STAFF_JOINED = "شما به‌عنوان همکار ثبت شدید."
STAFF_LINK_INVALID = "این لینک معتبر نیست."

MEMBER_NOT_FOUND = ("member_not_found", "عضو پیدا نشد.")
OWNER_ROLE_LOCKED = ("owner_role_locked", "نقش مالک ربات تغییر نمی‌کند؛ مالک همیشه مدیر است.")


class TeamError(Exception):
    """A Team API refusal. ``message`` is Persian."""

    def __init__(self, status: int, error: tuple[str, str]) -> None:
        self.status = status
        self.code, self.message = error
        super().__init__(self.message)


# --- roles ----------------------------------------------------------------------------------------


async def get_role(session: AsyncSession, bot_id: uuid.UUID, env: Env, actor_id: str) -> Role:
    """The stored role of ``actor_id``: ``customer`` when the user has no row or an unknown value.

    This is not the effective role: the owner is a manager whatever is stored
    (``Actor.effective_role``)."""
    stmt = select(BotUser.role).where(
        BotUser.bot_id == bot_id, BotUser.env == env, BotUser.actor_id == actor_id
    )
    return parse_role((await session.execute(stmt)).scalar_one_or_none())


async def get_member(session: AsyncSession, bot_id: uuid.UUID, env: Env, actor_id: str) -> BotUser | None:
    """The ``bot_users`` row of ``actor_id``, freshly read (never a stale identity-map copy)."""
    stmt = (
        select(BotUser)
        .where(BotUser.bot_id == bot_id, BotUser.env == env, BotUser.actor_id == actor_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_role(
    session: AsyncSession,
    bot_id: uuid.UUID,
    env: Env,
    actor_id: str,
    role: Role,
    *,
    display_name: str | None = None,
) -> None:
    """Store ``role`` for ``actor_id``, creating the user's row when there is none (named
    ``display_name``, else the id); an existing row keeps its name. Takes the bot's lock."""
    if role not in ROLES:
        raise ValueError("unknown role")
    await advisory_lock(session, bot_id)
    stmt = pg_insert(BotUser).values(
        bot_id=bot_id, env=env, actor_id=actor_id, display_name=display_name or actor_id, role=role
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[BotUser.bot_id, BotUser.env, BotUser.actor_id],
        set_={"role": stmt.excluded.role},
    )
    await session.execute(stmt)


def member_out(row: BotUser, owner_actor_id: str | None) -> TeamMemberOut:
    """A user as the Team API shows them, with the effective role (the owner is a manager)."""
    is_owner = owner_actor_id is not None and row.actor_id == owner_actor_id
    return TeamMemberOut(
        actor_id=row.actor_id,
        display_name=row.display_name,
        role="manager" if is_owner else parse_role(row.role),
        first_seen=row.first_seen,
    )


async def list_members(
    session: AsyncSession, bot_id: uuid.UUID, env: Env, owner_actor_id: str | None = None
) -> list[TeamMemberOut]:
    """The bot's staff and managers: the owner (when they have talked to the bot) first, then the
    managers, then the staff, each by first contact. At most ``MAX_MEMBERS``."""
    team: list[Any] = [BotUser.role.in_(sorted(TEAM_ROLES))]
    rank: list[Any] = []
    if owner_actor_id is not None:
        is_owner = BotUser.actor_id == owner_actor_id
        team.append(is_owner)
        rank.append((is_owner, 0))
    rank.append((BotUser.role == "manager", 1))
    stmt = (
        select(BotUser)
        .where(BotUser.bot_id == bot_id, BotUser.env == env, or_(*team))
        .order_by(case(*rank, else_=2), BotUser.first_seen, BotUser.actor_id)
        .limit(MAX_MEMBERS)
        .execution_options(populate_existing=True)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [member_out(row, owner_actor_id) for row in rows]


async def count_roles(
    session: AsyncSession, bot_id: uuid.UUID, env: Env, owner_actor_id: str | None = None
) -> dict[str, int]:
    """How many users of the bot have each effective role; every role is present (zero included)."""
    stmt = (
        select(BotUser.role, func.count())
        .where(BotUser.bot_id == bot_id, BotUser.env == env)
        .group_by(BotUser.role)
    )
    counts: dict[str, int] = dict.fromkeys(ROLES, 0)
    for value, n in (await session.execute(stmt)).all():
        counts[parse_role(value)] += n
    if owner_actor_id is not None:
        owner = await session.execute(
            select(BotUser.role).where(
                BotUser.bot_id == bot_id, BotUser.env == env, BotUser.actor_id == owner_actor_id
            )
        )
        stored = owner.first()
        if stored is not None and parse_role(stored[0]) != "manager":
            counts[parse_role(stored[0])] -= 1
            counts["manager"] += 1
    return counts


async def change_member_role(session: AsyncSession, bot: Bot, actor_id: str, role: Role) -> TeamMemberOut:
    """Set the role of a user of the live bot (``PATCH .../team/members/{actor_id}``).

    Only users who have talked to the bot exist (404 otherwise). The owner is always a manager: for
    them ``manager`` is accepted and stores nothing, any other role is refused (409). The owner link
    is read under the bot's lock. Not committed."""
    await advisory_lock(session, bot.id)
    fresh = await session.get(Bot, bot.id, populate_existing=True) or bot
    if await get_member(session, fresh.id, LIVE, actor_id) is None:
        raise TeamError(404, MEMBER_NOT_FOUND)
    owner = fresh.owner_actor_id
    is_owner = owner is not None and actor_id == owner
    if is_owner and role != "manager":
        raise TeamError(409, OWNER_ROLE_LOCKED)
    if not is_owner:
        await set_role(session, fresh.id, LIVE, actor_id, role)
    row = await get_member(session, fresh.id, LIVE, actor_id)
    if row is None:  # pragma: no cover - the row was read under the same lock
        raise TeamError(404, MEMBER_NOT_FOUND)
    return member_out(row, owner)


# --- staff link -----------------------------------------------------------------------------------


def staff_link(bot: Bot) -> str | None:
    """The staff deep link (``t.me`` or, for a Bale bot, ``ble.ir``), or None while the bot is not
    connected or has no code."""
    if bot.tg_token_enc is None or not bot.tg_username or not bot.staff_link_code:
        return None
    return bot_link(bot.platform, bot.tg_username, f"{STAFF_PAYLOAD_PREFIX}{bot.staff_link_code}")


def staff_code_from_payload(payload: str | None) -> str | None:
    """The code of a ``/start staff_<code>`` payload (possibly empty), or None for any other payload."""
    if payload is None or not payload.startswith(STAFF_PAYLOAD_PREFIX):
        return None
    return payload[len(STAFF_PAYLOAD_PREFIX) :]


def staff_code_matches(given: str | None, expected: str | None) -> bool:
    """Constant-time comparison of a presented code with the bot's code. False when either is
    missing or empty, and for a value that cannot be encoded (a lone surrogate)."""
    if not isinstance(given, str) or not isinstance(expected, str) or not given or not expected:
        return False
    try:
        # Bytes, not str: compare_digest rejects non-ASCII str, and the payload is attacker-controlled.
        return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))
    except UnicodeError:
        return False


async def rotate_staff_code(session: AsyncSession, bot: Bot) -> str:
    """Give ``bot`` a new staff code and return it; the previous link stops working. Not committed."""
    code = secrets.token_urlsafe(STAFF_CODE_BYTES)
    await advisory_lock(session, bot.id)
    bot.staff_link_code = code
    await session.flush()
    return code


async def revoke_staff_code(session: AsyncSession, bot: Bot) -> None:
    """Remove ``bot``'s staff code: the link stops working; staff keep their role. Not committed."""
    await advisory_lock(session, bot.id)
    bot.staff_link_code = None
    # Written even when this request read NULL: a rotate may have committed a code since.
    flag_modified(bot, "staff_link_code")
    await session.flush()


async def redeem_staff_code(
    session: AsyncSession, bot: Bot, actor_id: str, code: str, *, display_name: str | None = None
) -> bool:
    """``/start staff_<code>`` from ``actor_id``.

    True when ``code`` is the bot's current code: the user is then staff of the live bot (a manager
    stays a manager; opening the link again changes nothing; the owner, a manager by ownership, gets
    no stored role). False otherwise, with nothing written. The code is checked under the bot's lock
    against the row read under it, so a code that a rotate or revoke replaced before this took the
    lock never works. Not committed."""
    await advisory_lock(session, bot.id)
    fresh = await session.get(Bot, bot.id, populate_existing=True)
    if fresh is None or not staff_code_matches(code, fresh.staff_link_code):
        return False
    if fresh.owner_actor_id is not None and actor_id == fresh.owner_actor_id:
        return True
    current = await get_role(session, fresh.id, LIVE, actor_id)
    await set_role(
        session, fresh.id, LIVE, actor_id, role_after_staff_link(current), display_name=display_name
    )
    return True


async def team_of(session: AsyncSession, bot: Bot) -> TeamOut:
    """``GET /bots/{bot_id}/team``: the staff link (while connected), the code, members and counts."""
    owner = bot.owner_actor_id
    return TeamOut(
        staff_link=staff_link(bot),
        staff_link_code=bot.staff_link_code,
        members=await list_members(session, bot.id, LIVE, owner),
        counts=await count_roles(session, bot.id, LIVE, owner),
    )
