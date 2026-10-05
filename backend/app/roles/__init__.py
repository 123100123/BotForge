"""Roles of a bot's Telegram users (roadmap: Roles): the pure policy.

Three roles: ``customer`` (the default), ``staff`` and ``manager``. This module holds only the
decisions and imports no database code, so the deterministic runtime uses it directly. Storage, the
staff invite link and the Team API helpers are in ``roles/service.py``.

- Every decision uses ``Actor.effective_role``: the bot owner is a manager whatever ``bot_users``
  says. A live Telegram event gets its role from ``bot_users`` (``services/dispatch.py`` reads it
  under the bot's lock and overwrites whatever the caller put in the event); a sandbox event carries
  the simulator persona's role.
- A stored value that is not a known role counts as ``customer`` (``parse_role``): a damaged or
  hand-edited row can only lose rights, never gain them.
- Owner actions (Telegram ``own`` buttons and web-admin events: request status changes, order status
  changes, owner cancels) on a capability (``can_run_owner_actions``):
    audience "everyone"            staff and managers: staff work the customers' queue;
    audience "staff" / "managers"  managers only: these are internal workflows whose submitters are
                                   staff (leave requests, expense claims), and no staff member
                                   decides on their own submission or a colleague's.
  Customers never run owner actions.
"""

from app.botspec.models import AnyCapability, Role
from app.runtime.contracts import Actor

ROLES: tuple[Role, ...] = ("customer", "staff", "manager")
TEAM_ROLES: frozenset[Role] = frozenset({"staff", "manager"})  # the roles that run owner actions at all


def parse_role(value: object) -> Role:
    """The role a stored value stands for; anything unknown is ``customer`` (fails closed)."""
    if value == "staff":
        return "staff"
    if value == "manager":
        return "manager"
    return "customer"


def can_run_owner_actions(cap: AnyCapability, actor: Actor) -> bool:
    """Whether ``actor`` may run ``cap``'s owner actions (see the module docstring)."""
    role = actor.effective_role
    if cap.audience == "everyone":
        return role in TEAM_ROLES
    return role == "manager"


def role_after_staff_link(current: Role) -> Role:
    """The role of a user who opens a valid staff link: a customer becomes staff, staff and managers
    keep their role. Idempotent, and it never lowers a role."""
    return current if current in TEAM_ROLES else "staff"


__all__ = [
    "ROLES",
    "TEAM_ROLES",
    "can_run_owner_actions",
    "parse_role",
    "role_after_staff_link",
]
