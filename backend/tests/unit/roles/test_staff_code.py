"""The staff invite code without a database: comparison, link, payload, rotate/revoke/redeem order.

The SQL itself (upserts, the advisory lock, the Team API) runs against Postgres in
``tests/integration/test_team_api.py``.
"""

import hmac
import re
import uuid
from typing import Any

import pytest

from app.db.models import Bot
from app.roles import parse_role, service

CODE = "A" * 31 + "b"


def bot(**kw: Any) -> Bot:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "name": "ربات",
        "tg_token_enc": "encrypted",
        "tg_username": "shop_bot",
        "staff_link_code": CODE,
    }
    fields.update(kw)
    return Bot(**fields)


class FakeSession:
    """Records the calls ``service`` makes; ``get`` returns the bot as the database would."""

    def __init__(self, row: Bot | None) -> None:
        self.row = row
        self.calls: list[tuple[Any, ...]] = []

    async def execute(self, stmt: Any, params: Any = None) -> None:
        sql = str(stmt)
        self.calls.append(("lock",) if "pg_advisory_xact_lock" in sql else ("execute", sql))

    async def get(self, model: Any, key: Any, populate_existing: bool = False) -> Bot | None:
        self.calls.append(("get", populate_existing))
        return self.row

    async def flush(self) -> None:
        self.calls.append(("flush", self.row.staff_link_code if self.row is not None else None))


# --- comparison -----------------------------------------------------------------------------------


def test_only_the_exact_code_matches() -> None:
    assert service.staff_code_matches(CODE, CODE)
    for wrong in (CODE[:-1] + "c", CODE[:-1], CODE + "x", CODE.lower(), " " + CODE, "", "staff_" + CODE):
        assert not service.staff_code_matches(wrong, CODE), wrong
    # no code configured (revoked) or nothing presented: never a match, not even "" against ""
    for given, expected in ((CODE, None), (CODE, ""), ("", ""), (None, CODE), (None, None)):
        assert not service.staff_code_matches(given, expected)


def test_hostile_payloads_are_refused_without_raising() -> None:
    for hostile in ("\ud800", "کد" * 10, "\x00" * 32, "😀" * 8, "A" * 5000):
        assert not service.staff_code_matches(hostile, CODE)


def test_the_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(service.hmac, "compare_digest", spy)
    assert service.staff_code_matches(CODE, CODE)
    assert not service.staff_code_matches(CODE[:-1] + "c", CODE)  # differs only in the last character
    assert seen == [(CODE.encode(), CODE.encode()), ((CODE[:-1] + "c").encode(), CODE.encode())]


# --- payload and link -----------------------------------------------------------------------------


def test_the_payload_prefix() -> None:
    assert service.staff_code_from_payload(f"staff_{CODE}") == CODE
    assert service.staff_code_from_payload("staff_") == ""
    for other in (None, "owner_abc", "Staff_abc", "staffabc", "xstaff_abc", ""):
        assert service.staff_code_from_payload(other) is None, other


def test_the_link_exists_only_for_a_connected_bot_with_a_code() -> None:
    assert service.staff_link(bot()) == f"https://t.me/shop_bot?start=staff_{CODE}"
    assert service.staff_link(bot(tg_token_enc=None)) is None  # disconnected
    assert service.staff_link(bot(tg_username=None)) is None
    assert service.staff_link(bot(staff_link_code=None)) is None  # revoked


# --- rotate, revoke, redeem -----------------------------------------------------------------------


async def test_rotate_takes_the_lock_and_writes_a_fresh_url_safe_code() -> None:
    row = bot()
    codes: set[str] = set()
    for _ in range(20):
        session = FakeSession(row)
        code = await service.rotate_staff_code(session, row)  # type: ignore[arg-type]
        assert session.calls == [("lock",), ("flush", code)]  # written under the bot's lock
        assert row.staff_link_code == code
        assert re.fullmatch(r"[A-Za-z0-9_-]{32}", code), code
        assert len(f"staff_{code}") <= 64  # Telegram's start-payload limit
        codes.add(code)
    assert len(codes) == 20 and CODE not in codes


async def test_revoke_takes_the_lock_and_clears_the_code() -> None:
    row = bot()
    session = FakeSession(row)
    await service.revoke_staff_code(session, row)  # type: ignore[arg-type]
    assert row.staff_link_code is None
    assert session.calls == [("lock",), ("flush", None)]


@pytest.fixture
def roles(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """bot_users.role of the live bot, in memory, behind the service's own read and write."""
    stored: dict[str, str] = {}

    async def get_role(session: FakeSession, bot_id: uuid.UUID, env: str, actor_id: str) -> str:
        assert env == "live"
        return parse_role(stored.get(actor_id))

    async def set_role(
        session: FakeSession, bot_id: uuid.UUID, env: str, actor_id: str, role: str, **kw: Any
    ) -> None:
        assert env == "live"
        session.calls.append(("set_role", actor_id, role, kw.get("display_name")))
        stored[actor_id] = role

    monkeypatch.setattr(service, "get_role", get_role)
    monkeypatch.setattr(service, "set_role", set_role)
    return stored


async def test_redeem_checks_under_the_lock_and_is_idempotent(roles: dict[str, str]) -> None:
    row = bot()
    session = FakeSession(row)
    first = await service.redeem_staff_code(session, row, "700", CODE, display_name="نگار")  # type: ignore[arg-type]
    assert first is True and roles == {"700": "staff"}
    # the lock first, then the bot re-read under it, then the write
    assert session.calls == [("lock",), ("get", True), ("set_role", "700", "staff", "نگار")]
    again = await service.redeem_staff_code(session, row, "700", CODE)  # type: ignore[arg-type]
    assert again is True and roles == {"700": "staff"}


async def test_redeem_never_demotes_and_upgrades_junk(roles: dict[str, str]) -> None:
    row = bot()
    roles.update({"800": "manager", "801": "admin"})
    for actor in ("800", "801"):
        assert await service.redeem_staff_code(FakeSession(row), row, actor, CODE)  # type: ignore[arg-type]
    assert roles == {"800": "manager", "801": "staff"}


async def test_the_owner_opening_the_link_gets_no_stored_role(roles: dict[str, str]) -> None:
    row = bot(owner_actor_id="900")
    session = FakeSession(row)
    assert await service.redeem_staff_code(session, row, "900", CODE) is True  # type: ignore[arg-type]
    assert session.calls == [("lock",), ("get", True)] and roles == {}  # a manager by ownership


async def test_a_wrong_or_revoked_code_writes_nothing(roles: dict[str, str]) -> None:
    row = bot()
    for code in ("", CODE[:-1] + "c", "x" * 32):
        session = FakeSession(row)
        assert await service.redeem_staff_code(session, row, "700", code) is False  # type: ignore[arg-type]
        assert session.calls == [("lock",), ("get", True)]
    # the code read under the lock is what counts: one revoked meanwhile does not work
    stale_copy, current = bot(), bot(staff_link_code=None)
    session = FakeSession(current)
    assert await service.redeem_staff_code(session, stale_copy, "700", CODE) is False  # type: ignore[arg-type]
    gone = FakeSession(None)  # the bot was deleted
    assert await service.redeem_staff_code(gone, stale_copy, "700", CODE) is False  # type: ignore[arg-type]
    assert roles == {}
