"""Password hashing (argon2id): policy, verification, the no-account path, rehashing, concurrency."""

import asyncio
import threading
import time

import pytest
from argon2 import PasswordHasher

from app.security import passwords
from app.security.passwords import (
    MAX_CONCURRENT_HASHES,
    acceptable_password,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_policy_is_10_to_256_characters() -> None:
    assert not acceptable_password("")
    assert not acceptable_password("x" * 9)
    assert acceptable_password("x" * 10)
    assert acceptable_password("ر" * 256)
    assert not acceptable_password("x" * 257)


async def test_hash_and_verify() -> None:
    stored = await hash_password("correct horse battery")
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$")  # argon2-cffi's default parameters
    assert await verify_password(stored, "correct horse battery")
    assert not await verify_password(stored, "correct horse battery ")  # nothing is trimmed
    assert not await verify_password(stored, "Correct horse battery")
    assert not needs_rehash(stored)


async def test_no_account_and_unusable_hashes_cost_a_verification_and_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = passwords._dummy_hash()
    verified: list[str] = []
    real = passwords._hasher

    class Spy:  # PasswordHasher has __slots__, so the instance cannot be patched directly
        def verify(self, stored: str, password: bytes) -> bool:
            verified.append(stored)
            return real.verify(stored, password)

    monkeypatch.setattr(passwords, "_hasher", Spy())
    assert not await verify_password(None, "anything at all")
    assert not await verify_password("!legacy-owner-without-password", "!legacy-owner-without-password")
    assert verified == [dummy, "!legacy-owner-without-password", dummy]
    monkeypatch.setattr(passwords, "_hasher", real)
    assert needs_rehash("!legacy-owner-without-password")


def test_outdated_parameters_need_a_rehash() -> None:
    assert needs_rehash(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("x" * 10))


async def test_a_lone_surrogate_is_just_another_password() -> None:
    stored = await hash_password("\ud800 abcdefghij")
    assert await verify_password(stored, "\ud800 abcdefghij")
    assert not await verify_password(stored, "\udc00 abcdefghij")


async def test_at_most_a_few_hashes_run_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    running = peak = 0
    lock = threading.Lock()

    def slow_hash(password: str) -> str:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return "h"

    monkeypatch.setattr(passwords, "hash_password_sync", slow_hash)
    await asyncio.gather(*(hash_password("x") for _ in range(4 * MAX_CONCURRENT_HASHES)))
    assert peak == MAX_CONCURRENT_HASHES
