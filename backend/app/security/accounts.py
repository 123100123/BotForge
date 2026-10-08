"""Owner accounts: email rules, creation, password checks and resets (table ``users``).

Used by the auth routes (``app.api.auth``) and by ``scripts/create_user.py``, so both apply the same
rules. Emails are normalized (surrounding whitespace stripped, ASCII letters lowercased) before they
are validated, stored or looked up; the stored form is unique. A valid email is what a browser's
``<input type="email">`` accepts (the WHATWG definition: ASCII only), at most 254 characters with a
local part of at most 64. Non-ASCII input is never case-mapped, so no Unicode case rule can turn one
address into another; it simply fails validation.

No database connection is held while a password is hashed or verified: hashing is slow and limited
to a few at a time (``app.security.passwords``), and unauthenticated callers can queue many of them,
so a connection held meanwhile would let them drain the pool that every other request (and every
bot's webhook) needs. ``create_user`` and ``reset_password`` hash before touching the database;
``authenticate`` ends its lookup transaction before verifying.

With ``AUTH_PROVIDER=supabase`` owners are authenticated by Supabase instead, and
``ensure_external_user`` keeps a ``users`` row for each of them (see its docstring).
"""

import re
import secrets
import uuid
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import User
from app.security.passwords import acceptable_password, hash_password, needs_rehash, verify_password
from app.security.sessions import delete_user_sessions

MAX_EMAIL_LENGTH = 254
MAX_LOCAL_PART_LENGTH = 64

# Accounts without a usable password: the owners migration 0003 adopted, and owners authenticated by
# an external provider (``ensure_external_user``). Both values are migration 0003's (a test keeps them
# equal). The hash is not an argon2 hash, so no password ever verifies against it
# (``app.security.passwords``); the domain is reserved (RFC 2606), so the address reaches nobody.
LEGACY_PASSWORD_HASH = "!legacy-owner-without-password"
PLACEHOLDER_DOMAIN = "botforge.invalid"
_PLACEHOLDER_PREFIX = "legacy-"
_EMAIL = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
)


class CurrentUser(BaseModel):
    """The authenticated caller."""

    id: uuid.UUID
    email: str


class AccountError(Exception):
    code = "account_error"


class InvalidEmail(AccountError):
    code = "invalid_email"


class WeakPassword(AccountError):
    code = "weak_password"


class EmailTaken(AccountError):
    code = "email_taken"


class UnknownAccount(AccountError):
    code = "unknown_account"


def normalize_email(raw: str) -> str:
    stripped = raw.strip()
    return stripped.lower() if stripped.isascii() else stripped


def valid_email(email: str) -> bool:
    """Whether a normalized email is acceptable for an account."""
    local, _, _ = email.partition("@")
    return (
        len(email) <= MAX_EMAIL_LENGTH
        and len(local) <= MAX_LOCAL_PART_LENGTH
        and _EMAIL.fullmatch(email) is not None
    )


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """The account for an email as typed (normalized here); None for an invalid email."""
    email = normalize_email(email)
    if not valid_email(email):
        return None
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def create_user(db: AsyncSession, email: str, password: str) -> User:
    """A new account (flushed; the caller commits).

    Raises ``InvalidEmail``, ``WeakPassword`` or ``EmailTaken``, checked in that order."""
    email = normalize_email(email)
    if not valid_email(email):
        raise InvalidEmail(email)
    if not acceptable_password(password):
        raise WeakPassword()
    password_hash = await hash_password(password)  # before any database work (module docstring)
    if await get_user_by_email(db, email) is not None:
        raise EmailTaken(email)
    user = User(email=email, password_hash=password_hash)
    try:
        async with db.begin_nested():  # a concurrent signup for the same email loses here
            db.add(user)
            await db.flush()
    except IntegrityError:
        raise EmailTaken(email) from None
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """The account whose email and password these are, or None. An unknown email costs the same
    password verification as a wrong password. Rehashes the password when the hashing parameters
    changed (the caller commits).

    Ends the session's current transaction (a commit) after the lookup, so that no connection is
    held while the password is verified: call it before writing anything in ``db``."""
    found = await get_user_by_email(db, email)
    user_id, stored_hash = (found.id, found.password_hash) if found is not None else (None, None)
    await db.commit()
    if not await verify_password(stored_hash, password) or user_id is None or stored_hash is None:
        return None
    new_hash = await hash_password(password) if needs_rehash(stored_hash) else None
    # Read again (a new transaction): None if the account was deleted while the password was checked.
    user = await db.get(User, user_id, populate_existing=True)
    if user is not None and new_hash is not None:
        user.password_hash = new_hash
    return user


async def reset_password(db: AsyncSession, email: str, password: str) -> tuple[User, int]:
    """Set a new password and end every session of the account; returns the user and the number of
    sessions ended (the caller commits). Raises ``WeakPassword`` or ``UnknownAccount``."""
    if not acceptable_password(password):
        raise WeakPassword()
    password_hash = await hash_password(password)  # before any database work (module docstring)
    user = await get_user_by_email(db, email)
    if user is None:
        raise UnknownAccount(normalize_email(email))
    user.password_hash = password_hash
    await db.flush()
    return user, await delete_user_sessions(db, user.id)


# --------------------------------------------------------------------------- external accounts


def placeholder_email(user_id: uuid.UUID, suffix: str = "") -> str:
    """``legacy-<id>@botforge.invalid``: the email of an account that has no usable one, in the form
    migration 0003 gives the owners it adopts (``suffix`` keeps it unique if even that is taken)."""
    return f"{_PLACEHOLDER_PREFIX}{user_id}{suffix}@{PLACEHOLDER_DOMAIN}"


def is_placeholder_email(email: str) -> bool:
    return email.startswith(_PLACEHOLDER_PREFIX) and email.endswith(f"@{PLACEHOLDER_DOMAIN}")


def external_email(raw: str | None) -> str | None:
    """An identity provider's email claim as an account email (normalized), or None when there is
    none or it cannot be one: invalid by the rules above, or in the reserved placeholder domain (so a
    claimed address can never pass for one of our placeholders)."""
    if not raw:
        return None
    email = normalize_email(raw)
    if not valid_email(email) or email.endswith(f"@{PLACEHOLDER_DOMAIN}"):
        return None
    return email


@dataclass(frozen=True)
class ExternalAccount:
    id: uuid.UUID
    email: str
    wrote: bool  # an insert or an email update is pending in ``db``; the caller commits it


async def ensure_external_user(db: AsyncSession, user_id: uuid.UUID, email: str | None) -> ExternalAccount:
    """The ``users`` row of an owner authenticated by an external identity provider
    (``AUTH_PROVIDER=supabase``), created on first sight. The caller commits when ``wrote``.

    The row's id is the provider's user id (the verified token's ``sub``), and that id is the whole
    identity: the email is only the account's label, so an account is never found, linked or taken
    over by its email. A new row gets ``LEGACY_PASSWORD_HASH``, which no password verifies, so the
    own login can never sign in to it (should a deployment switch to ``AUTH_PROVIDER=local``, an
    operator sets a password with ``scripts/create_user.py --reset-password``).

    Email: the provider's (``external_email``) when it is usable and no other account has it;
    otherwise a unique placeholder (``placeholder_email``) instead of failing the request. A row that
    still has a placeholder, such as the accounts migration 0003 made for the owners of existing bots
    (their ids are the provider's user ids), takes the provider's email as soon as it is usable and
    free. A real email that differs from the provider's is left as it is.

    Concurrency: the first requests of one owner race on ``INSERT ... ON CONFLICT DO NOTHING``; the
    loser waits for the winner's commit and inserts nothing. An email update runs in a savepoint and
    only where no other row has that email, so losing that race keeps the placeholder.
    """
    wanted = external_email(email)
    current = await _account_email(db, user_id)
    if current is None:
        return await _insert_external(db, user_id, wanted)
    if wanted is not None and wanted != current and is_placeholder_email(current):
        return await _claim_email(db, user_id, current, wanted)
    return ExternalAccount(user_id, current, wrote=False)


async def _account_email(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    return (await db.execute(select(User.email).where(User.id == user_id))).scalar_one_or_none()


async def _insert_external(db: AsyncSession, user_id: uuid.UUID, wanted: str | None) -> ExternalAccount:
    # The plain placeholder is taken only if someone created an account with that very address (it is
    # valid syntax); the random suffix then still gives a free one.
    candidates = [*([wanted] if wanted is not None else []), placeholder_email(user_id)]
    candidates.append(placeholder_email(user_id, f"-{secrets.token_hex(8)}"))
    for candidate in candidates:
        inserted = await db.execute(
            pg_insert(User)
            .values(id=user_id, email=candidate, password_hash=LEGACY_PASSWORD_HASH)
            .on_conflict_do_nothing()
            .returning(User.email)
        )
        stored = inserted.scalar_one_or_none()
        if stored is not None:
            return ExternalAccount(user_id, stored, wrote=True)
        # Nothing inserted: a concurrent first request created this id (and committed, or this
        # statement would still be waiting), or another account already has ``candidate``.
        existing = await _account_email(db, user_id)
        if existing is not None:
            return ExternalAccount(user_id, existing, wrote=False)
    raise RuntimeError("no account row could be created for an externally authenticated owner")


async def _claim_email(db: AsyncSession, user_id: uuid.UUID, current: str, wanted: str) -> ExternalAccount:
    other = aliased(User)
    try:
        async with db.begin_nested():  # a unique violation (lost race) rolls back only this
            updated = (
                await db.execute(
                    update(User)
                    .where(User.id == user_id, User.email == current, ~exists().where(other.email == wanted))
                    .values(email=wanted)
                    .returning(User.email)
                    .execution_options(synchronize_session=False)
                )
            ).scalar_one_or_none()
    except IntegrityError:  # another account took the address in the meantime: keep the placeholder
        updated = None
    if updated is not None:
        return ExternalAccount(user_id, updated, wrote=True)
    # Not updated: the address belongs to another account, or a concurrent request changed this row.
    return ExternalAccount(user_id, await _account_email(db, user_id) or current, wrote=False)
