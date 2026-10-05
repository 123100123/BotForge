"""The owner-link predicate shared by the Settings status and the webhook. No database."""

import uuid

import pytest

from app.db.models import Bot
from app.integrations.telegram.onboarding import armed_owner_code, status_of

LINK = "https://t.me/shop_bot?start=owner_c0de"


def bot(*, connected: bool = True, owner: str | None = None, code: str | None = "c0de") -> Bot:
    return Bot(
        owner_id=uuid.uuid4(),
        name="ربات",
        tg_token_enc="ENCRYPTED" if connected else None,
        tg_username="shop_bot" if connected else None,
        owner_actor_id=owner,
        owner_link_code=code,
    )


@pytest.mark.parametrize(
    ("connected", "owner", "code", "linked", "link"),
    [
        (True, None, "c0de", False, LINK),  # right after connect
        (True, "900", None, True, None),  # the link was used
        (True, "900", "c0de", True, None),  # left by older code: it cannot replace the owner
        (True, None, None, False, None),  # nothing armed
        (False, None, None, False, None),  # after disconnect
        (False, None, "c0de", False, None),  # a new bot: no webhook yet, connect arms a new code
    ],
)
def test_a_link_is_shown_exactly_when_it_would_link_an_owner(
    connected: bool, owner: str | None, code: str | None, linked: bool, link: str | None
) -> None:
    status = status_of(bot(connected=connected, owner=owner, code=code))
    assert (status.owner_linked, status.owner_link) == (linked, link)


def test_a_code_is_armed_only_while_no_owner_is_linked() -> None:
    assert armed_owner_code(bot(owner=None, code="c0de")) == "c0de"
    assert armed_owner_code(bot(owner="900", code="c0de")) is None
    assert armed_owner_code(bot(owner=None, code=None)) is None
    assert armed_owner_code(bot(owner=None, code="")) is None
