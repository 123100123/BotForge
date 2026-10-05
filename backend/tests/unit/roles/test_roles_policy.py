"""The pure role policy (``app/roles/__init__.py``): stored values, owner actions, the staff link."""

import pytest

from app.roles import ROLES, TEAM_ROLES, can_run_owner_actions, parse_role, role_after_staff_link
from app.runtime.contracts import Actor
from tests.unit.runtime.test_request import repair_spec

CUSTOMER = Actor(id="ali", display_name="علی")
STAFF = Actor(id="sam", display_name="سام", role="staff")
MANAGER = Actor(id="mina", display_name="مینا", role="manager")
OWNER = Actor(id="owner", display_name="مدیر", is_owner=True)  # stored role customer: still a manager


def test_known_roles_parse_and_anything_else_is_a_customer() -> None:
    assert [parse_role(r) for r in ROLES] == list(ROLES)
    for junk in (None, "", "admin", "owner", "Staff", "MANAGER", " staff", "staff ", 1, True, b"staff"):
        assert parse_role(junk) == "customer", junk
    assert frozenset({"staff", "manager"}) == TEAM_ROLES


@pytest.mark.parametrize(
    ("audience", "allowed"),
    [
        ("everyone", {"sam", "mina", "owner"}),  # staff work the customers' queue
        ("staff", {"mina", "owner"}),  # internal workflow: staff submit, managers decide
        ("managers", {"mina", "owner"}),
    ],
)
def test_who_runs_owner_actions(audience: str, allowed: set[str]) -> None:
    cap = repair_spec(audience=audience).capability("repair")
    assert cap is not None
    for actor in (CUSTOMER, STAFF, MANAGER, OWNER):
        assert can_run_owner_actions(cap, actor) is (actor.id in allowed), (audience, actor.id)


def test_a_disabled_capability_does_not_change_who_may_decide() -> None:
    # Telegram never reaches a disabled capability (the runtime's gating); the web owner still does.
    cap = repair_spec(enabled=False).capability("repair")
    assert cap is not None and can_run_owner_actions(cap, OWNER) and not can_run_owner_actions(cap, CUSTOMER)


def test_the_staff_link_makes_customers_staff_and_never_lowers_a_role() -> None:
    assert role_after_staff_link("customer") == "staff"
    assert role_after_staff_link("staff") == "staff"
    assert role_after_staff_link("manager") == "manager"
    for role in ROLES:  # idempotent
        once = role_after_staff_link(role)
        assert role_after_staff_link(once) == once
