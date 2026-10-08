"""Telegram manager screen «👥 کارکنان» (``nav:go:mgr.team``) and the user directory helpers the
manager screens share (U6).

The team screen is read only: role counts, the team members (display names and role words) and,
for the bot owner only, the staff invite link (``roles.service.staff_link``). Role changes and new
links stay in the web Control Center, and the screen says so.

Store extensions (optional, not part of the frozen ``Store`` protocol; looked up with ``getattr`` so
any store without them still works):
  ``await store.team_overview()``      -> ``schemas.business.TeamOut | None`` (``PgStore``: the
                                          Team API's ``roles.service.team_of``)
  ``await store.display_names(ids)``   -> ``{actor_id: display_name}`` for the ids it knows
                                          (``PgStore`` and ``MemoryStore``)
Without ``team_overview`` the screen says the list is on the web; without ``display_names`` the
order screens fall back to a checkout answer that looks like a name.

The staff link is a secret the roles service shows only to the authenticated owner, so here too
only ``actor.is_owner`` sees it; other managers are told to ask the owner (Decision: U6 report).
"""

from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from app.botspec.text_keys import fill_text
from app.runtime import formatting, nav
from app.runtime.contracts import Button
from app.runtime.texts import manager as tx
from app.runtime.texts import nav as nav_texts

if TYPE_CHECKING:
    from app.runtime.ctx import Ctx

TEAM_ROUTE = "mgr.team"
MAX_MEMBERS_SHOWN = 15


def _fill(template: str, **values: object) -> str:
    return fill_text(template, {k: str(v) for k, v in values.items()})


def _num(value: int) -> str:
    return formatting.to_persian_digits(value)


def manager_button() -> Button:
    """«🧭 مدیریت» -> the manager home."""
    return nav.nav_button(tx.MANAGER, nav.MGR)


def screen_heading(ctx: "Ctx", route: str, *extra: str) -> str:
    """``🧭 مدیریت › <route breadcrumb> › extra`` (nav leaves the root out of breadcrumbs)."""
    crumbs = ctx.heading(route, *extra)
    return f"{tx.MANAGER}{nav_texts.CRUMB_SEPARATOR}{crumbs}" if crumbs else tx.MANAGER


async def display_names(ctx: "Ctx", actor_ids: Iterable[str | None]) -> dict[str, str]:
    """``{actor_id: display_name}`` through the optional store extension; ``{}`` without it."""
    ids = sorted({a for a in actor_ids if a})
    lookup = getattr(ctx.store, "display_names", None)
    if not ids or lookup is None:
        return {}
    names = await lookup(ids)
    return {k: v for k, v in names.items() if isinstance(v, str) and v.strip()}


async def _team_overview(ctx: "Ctx") -> Any | None:
    lookup = getattr(ctx.store, "team_overview", None)
    return await lookup() if lookup is not None else None


def _member_line(member: Any, owner_id: str | None) -> str:
    name = (member.display_name or "").strip() or member.actor_id
    role = tx.ROLE_WORDS.get(member.role, member.role)
    if owner_id is not None and member.actor_id == owner_id:
        return _fill(tx.TEAM_MEMBER_OWNER, name=name, role=role, owner=tx.OWNER_MARK)
    return _fill(tx.TEAM_MEMBER, name=name, role=role)


async def show_team(ctx: "Ctx", target: nav.Target) -> None:
    lines = [screen_heading(ctx, TEAM_ROUTE)]
    team = await _team_overview(ctx)
    if team is None:
        lines.append(tx.TEAM_UNAVAILABLE)
    else:
        counts = team.counts
        lines.append(
            _fill(
                tx.TEAM_COUNTS,
                managers=_num(counts.get("manager", 0)),
                staff=_num(counts.get("staff", 0)),
                customers=_num(counts.get("customer", 0)),
            )
        )
        members = list(team.members)
        others = [m for m in members if m.actor_id != ctx.owner_id]
        if not others:
            lines.append(tx.TEAM_EMPTY)
        if members:
            lines.append(tx.TEAM_MEMBERS)
            lines += [_member_line(m, ctx.owner_id) for m in members[:MAX_MEMBERS_SHOWN]]
            if len(members) > MAX_MEMBERS_SHOWN:
                lines.append(_fill(tx.TEAM_MORE, count=_num(len(members) - MAX_MEMBERS_SHOWN)))
        lines.append("")
        if not ctx.actor.is_owner:
            lines.append(tx.TEAM_LINK_OWNER_ONLY)
        elif team.staff_link:
            lines.append(_fill(tx.TEAM_LINK, link=team.staff_link))
        else:
            lines.append(tx.TEAM_NO_LINK)
    lines.append(tx.TEAM_WEB_NOTE)
    ctx.reply("\n".join(lines), [[manager_button()]])


nav.register_route(replace(nav.ROUTES[TEAM_ROUTE], resolve=show_team, ready=True))
