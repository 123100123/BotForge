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
"""

import re
import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.security.passwords import acceptable_password, hash_password, needs_rehash, verify_password
from app.security.sessions import delete_user_sessions

MAX_EMAIL_LENGTH = 254
MAX_LOCAL_PART_LENGTH = 64
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
