"""Callback args beyond the database's integer range are invalid, never an exception."""

import pytest

from app.runtime.ctx import parse_int
from tests.unit.runtime.harness import Harness, load_example

INT64_MAX = 2**63 - 1


def test_parse_int_bounds() -> None:
    assert parse_int("0") == 0
    assert parse_int(" ۱۲ ") == 12
    assert parse_int(str(INT64_MAX)) == INT64_MAX
    assert parse_int(str(INT64_MAX + 1)) is None
    assert parse_int("9" * 400) is None
    assert parse_int("-1") is None and parse_int("1.5") is None and parse_int("") is None


@pytest.mark.parametrize("action", ["item", "book", "cancel"])
async def test_oversized_booking_callback_args_get_the_stale_reply(action: str) -> None:
    h = Harness(load_example("workshop.botspec.json"))
    resp = await h.tap("ali", f"book_workshop:{action}:{INT64_MAX + 1}")
    assert resp.messages and resp.messages[0].text


async def test_oversized_admin_record_id_is_rejected_without_error() -> None:
    h = Harness(load_example("workshop.botspec.json"))
    resp = await h.admin(f"book_workshop:cancel:{INT64_MAX + 1}")
    assert resp.outcomes and resp.outcomes[0].result == "rejected"
