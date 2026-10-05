"""Password hashing: argon2id through ``argon2-cffi`` with the library's default parameters.

Hashing and verification run in a worker thread (argon2 releases the GIL), so a login never stalls
the event loop that also serves every bot's webhook. At most ``MAX_CONCURRENT_HASHES`` run at once:
each takes ~64 MiB with the default parameters, and unauthenticated callers can trigger them.

``verify_password`` takes the same time whether or not an account exists: without a stored hash (or
with one that is not an argon2 hash, such as a migrated placeholder account's), it verifies against a
dummy hash made with the current parameters and returns False.

Passwords are hashed exactly as received: nothing is stripped or normalized. They are encoded as
UTF-8 with ``surrogatepass`` so that a JSON string holding a lone surrogate (``"\\ud800"``) is just
another password instead of an encoding error.
"""

import asyncio
import contextlib
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256
MAX_CONCURRENT_HASHES = 2

_hasher = PasswordHasher()  # argon2id, RFC 9106 low-memory profile (argon2-cffi defaults)
_slots: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None


def acceptable_password(password: str) -> bool:
    """The password policy: 10 to 256 characters, nothing else."""
    return MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH


def _secret(password: str) -> bytes:
    return password.encode("utf-8", "surrogatepass")


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A hash of a random secret with the current parameters (computed once, on first use)."""
    return _hasher.hash(secrets.token_bytes(32))


def _spend_dummy_verification(password: str) -> None:
    with contextlib.suppress(VerificationError):
        _hasher.verify(_dummy_hash(), _secret(password))


def hash_password_sync(password: str) -> str:
    return _hasher.hash(_secret(password))


def verify_password_sync(stored_hash: str | None, password: str) -> bool:
    if stored_hash is None:  # no such account: same work, always refused
        _spend_dummy_verification(password)
        return False
    try:
        return _hasher.verify(stored_hash, _secret(password))
    except InvalidHashError:  # not an argon2 hash (a placeholder account): same work, refused
        _spend_dummy_verification(password)
        return False
    except VerificationError:  # wrong password (VerifyMismatchError) or a damaged hash
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when ``stored_hash`` was made with other parameters than the current defaults."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


def _hash_slots() -> asyncio.Semaphore:
    """The concurrency limit of the running event loop. One semaphore per loop: an asyncio primitive
    binds to the loop it first waits on, and tests run many loops in one process."""
    global _slots
    loop = asyncio.get_running_loop()
    if _slots is None or _slots[0] is not loop:
        _slots = (loop, asyncio.Semaphore(MAX_CONCURRENT_HASHES))
    return _slots[1]


async def hash_password(password: str) -> str:
    async with _hash_slots():
        return await asyncio.to_thread(hash_password_sync, password)


async def verify_password(stored_hash: str | None, password: str) -> bool:
    """Whether ``password`` matches ``stored_hash``; ``None`` (no such account) is always False."""
    async with _hash_slots():
        return await asyncio.to_thread(verify_password_sync, stored_hash, password)
