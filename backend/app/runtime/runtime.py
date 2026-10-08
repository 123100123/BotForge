"""``BotRuntime``: the deterministic event router every adapter calls (WP1).

Inputs are only the event (including ``event.now``), the spec and the store. Routing:

  start                      clear session; managers: the manager home; everyone else: the welcome
                             text over the user home (``runtime/nav.py`` compiles both)
  text, no session           the same as start (without clearing anything)
  text /menu /panel /help    bot commands (``/cmd@botname`` too; any session is cleared first):
                             /menu the role home, /panel the manager home for managers (everyone
                             else: their role home), /help a short help text derived from the role
                             home entries + [🏠 خانه]
  text, session              engine.on_text of the session's capability (gone -> drop session, home)
  callback nav:go:<route>    ``nav.go``: role homes, engine entry points, manager screens; unknown or
                             disabled routes -> the role home as a NEW message under the stale notice
                             (clears any session, like every navigation)
  callback menu:home         legacy: the role home (clears any session)
  callback menu:open:<key>   legacy: a ``spec.menu`` item -> engine.open(cap, item.view); else a
                             route id (``menu:open:shop``) -> ``nav.go``; ``_mgr`` -> ``nav:go:mgr``,
                             ``_rep.<k>`` -> ``nav:go:mgr.rep.<k>``; anything else -> stale home
  callback <cap>:own:<r.k>   staff/managers -> engine.owner_action(record_id, k)
  callback <cap>:<act>:<arg> engine.on_callback; a non-form action (not ans/skip/stop) first
                             clears the actor's session, so a form abandoned by navigating away
                             never captures later text (not in groups: see below)
  admin <cap>:cancel:<id>    staff/managers -> engine.owner_action(id, "cancel")   Outcome.action cancel
  admin <cap>:own:<id>.<k>   staff/managers -> engine.owner_action(id, k)          Outcome.action owner_action

Malformed or stale capability data (bad format, unknown capability, action not valid for the
capability type) gets ``ctx.stale()``: a NEW message «این منو قدیمی شده است.» with one button to the
current menu; the pressed message is never modified and nothing raises. A capability type whose
engine module does not exist yet gets a "not available yet" reply.
Every event upserts the acting user first.

Owner actions (roles, roadmap: Roles): who may run them is ``roles.can_run_owner_actions``, decided
on ``actor.effective_role`` (the owner is a manager): staff and managers on a customer-facing
capability (``audience="everyone"``), managers only on an internal one (``audience`` staff or
managers, whose submitters are staff). Anyone else gets ``Outcome(result="rejected",
reason="not_allowed")`` and never reaches the engine. Customers are refused before the capability is
even looked up, as before roles existed.

Capability gating (Business OS): a capability that is disabled (``enabled=False``) or whose
``audience`` does not allow the actor (``ctx.capability_available``) is treated exactly like a
missing one on the Telegram paths (callback, menu open, nav route, text with a session); the homes
leave it out. Admin events bypass gating.

Group context (``event.chat_type == "group"``): start and text events and any ``menu`` or ``nav``
callback return an empty response without side effects (no user upsert, no session change); other
callbacks route normally and never clear the presser's (private-chat) session: a group button
(the RSVP card's ``book``) must not abandon a form the user is filling in privately. Admin events
are unaffected.
"""

from typing import Literal

from app.botspec.models import AnyCapability, BotSpec
from app.roles import TEAM_ROLES, can_run_owner_actions
from app.runtime import manager, nav
from app.runtime.callbacks import (
    ACT_CANCEL,
    ACT_GO,
    ACT_HOME,
    ACT_OPEN,
    ACT_OWN,
    ACTIONS_BY_TYPE,
    FORM_ACTIONS,
    MENU,
    NAV,
    CallbackError,
    parse_callback,
)
from app.runtime.contracts import Button, RuntimeEvent, RuntimeResponse
from app.runtime.ctx import Ctx, parse_int
from app.runtime.engines import EngineUnavailable, get_engine
from app.runtime.engines.base import Engine
from app.runtime.store import Store
from app.runtime.texts import commands as cmd_tx
from app.runtime.texts import common

COMMANDS = frozenset({"/menu", "/panel", "/help"})


def bot_command(text: str) -> str | None:
    """``/menu``, ``/panel`` or ``/help`` when ``text`` is that bot command (``/menu@botname`` and
    trailing arguments allowed, case-insensitive), else ``None``. ``/start`` is handled before the
    runtime (the adapter turns it into a ``start`` event)."""
    words = text.split(maxsplit=1)
    command = words[0].split("@", 1)[0].lower() if words else ""
    return command if command in COMMANDS else None


def _group_noop(event: RuntimeEvent) -> bool:
    """Group events the runtime ignores: start, text, and any ``menu`` or ``nav`` callback
    (malformed callback data included: a group never gets the stale menu)."""
    if event.chat_type != "group":
        return False
    if event.kind in ("start", "text"):
        return True
    if event.kind != "callback":
        return False
    try:
        cap_key, _, _ = parse_callback(event.data or "")
    except CallbackError:
        return True
    return cap_key in (MENU, NAV)


class BotRuntime:
    async def handle(self, event: RuntimeEvent, spec: BotSpec, store: Store) -> RuntimeResponse:
        if _group_noop(event):
            return RuntimeResponse(messages=[])
        await store.upsert_user(event.actor)
        ctx = await Ctx.create(event, spec, store)
        if event.kind == "start":
            await ctx.clear_session()
            await self._welcome(ctx)
        elif event.kind == "text":
            await self._on_text(ctx, event.text or "")
        elif event.kind == "callback":
            await self._on_callback(ctx, event.data)
        elif event.kind == "admin":
            await self._on_admin(ctx, event.data)
        return ctx.response()

    # --- routes ------------------------------------------------------------------------------

    @staticmethod
    async def _welcome(ctx: Ctx) -> None:
        """Managers land on the manager home; everyone else gets the welcome text over the user
        home."""
        await nav.show_home(ctx, ctx.spec.bot.welcome_text)

    @staticmethod
    def _engine(ctx: Ctx, cap: AnyCapability) -> Engine | None:
        try:
            return get_engine(cap.type)
        except EngineUnavailable:
            ctx.reply(common.NOT_AVAILABLE, ctx.menu_buttons())
            return None

    @staticmethod
    async def _on_command(ctx: Ctx, command: str) -> None:
        """Commands abandon any form in progress, like every navigation."""
        await ctx.clear_session()
        if command == "/panel" and ctx.actor.effective_role == "manager":
            await nav.go(ctx, nav.MGR)
        elif command == "/help":
            text, rows = BotRuntime._help(ctx)
            ctx.reply(text, rows, edit=False)
        else:  # /menu, and /panel for everyone who has no manager panel: their own role home
            await nav.show_home(ctx, edit=False)

    @staticmethod
    def _help(ctx: Ctx) -> tuple[str, list[list[Button]]]:
        """A short help text from the role home's entries, the commands, and a Home button."""
        role = ctx.actor.effective_role
        is_manager = role == "manager"
        entries = [e for e in nav.compile_home(ctx.spec, role) if e.key != nav.CUST]
        lines = [cmd_tx.HELP_HEADING.format(business=ctx.spec.bot.name)]
        if entries:
            lines.append(cmd_tx.HELP_ENTRIES_MANAGER if is_manager else cmd_tx.HELP_ENTRIES)
            lines += [f"• {e.label}" for e in entries]
        else:
            lines.append(cmd_tx.HELP_EMPTY)
        lines += ["", cmd_tx.HELP_COMMANDS, cmd_tx.HELP_MENU]
        if is_manager:
            lines.append(cmd_tx.HELP_PANEL)
        lines += [cmd_tx.HELP_START, cmd_tx.HELP_HELP]
        return "\n".join(lines), [[nav.home_button()]]

    async def _on_text(self, ctx: Ctx, text: str) -> None:
        command = bot_command(text)
        if command is not None:
            await self._on_command(ctx, command)
            return
        session = await ctx.get_session()
        if session is None:
            await self._welcome(ctx)
            return
        cap_key = session.get("capability") if isinstance(session, dict) else None
        cap = ctx.spec.capability(cap_key) if isinstance(cap_key, str) else None
        if cap is None:
            await ctx.clear_session()
            await self._welcome(ctx)
            return
        if not ctx.can_use(cap):
            await ctx.clear_session()
            ctx.stale()
            return
        engine = self._engine(ctx, cap)
        if engine is None:
            await ctx.clear_session()
            return
        await engine.on_text(ctx, cap, text)

    async def _on_callback(self, ctx: Ctx, data: str | None) -> None:
        try:
            cap_key, action, arg = parse_callback(data or "")
        except CallbackError:
            ctx.stale()
            return
        if cap_key == NAV:
            await ctx.clear_session()
            if action == ACT_GO:
                await nav.go(ctx, arg)
            else:  # e.g. "nav:open:x": parses (the action exists elsewhere) but means nothing here
                await nav.stale_home(ctx)
            return
        if cap_key == MENU:
            await self._on_menu(ctx, action, arg)
            return
        cap = ctx.spec.capability(cap_key)
        if cap is None or action not in ACTIONS_BY_TYPE.get(cap.type, frozenset()) or not ctx.can_use(cap):
            ctx.stale()
            return
        if action not in FORM_ACTIONS and ctx.event.chat_type != "group":
            await ctx.clear_session()
        if action == ACT_OWN:
            await self._owner_action(ctx, cap, action, arg)
            return
        engine = self._engine(ctx, cap)
        if engine is not None:
            await engine.on_callback(ctx, cap, action, arg)

    async def _on_menu(self, ctx: Ctx, action: str, arg: str) -> None:
        """Legacy ``menu:*`` buttons (still on messages sent before nav routes existed)."""
        await ctx.clear_session()
        if action == ACT_HOME:
            await nav.show_home(ctx)
            return
        if action != ACT_OPEN:
            await nav.stale_home(ctx)
            return
        if manager.is_manager_item(arg):  # pseudo items; spec keys never start with _
            await nav.go(ctx, manager.legacy_route(arg))
            return
        item = next((m for m in ctx.spec.menu if m.key == arg), None)
        if item is None:
            await nav.go(ctx, arg)  # a route id (``menu:open:shop``), else the stale home
            return
        cap = ctx.spec.capability(item.capability)
        if cap is None or not ctx.can_use(cap):
            await nav.stale_home(ctx)
            return
        engine = self._engine(ctx, cap)
        if engine is not None:
            await engine.open(ctx, cap, item.view)

    async def _on_admin(self, ctx: Ctx, data: str | None) -> None:
        try:
            cap_key, action, arg = parse_callback(data or "")
        except CallbackError:
            ctx.stale()
            return
        outcome_action: Literal["cancel", "owner_action"] = (
            "cancel" if action == ACT_CANCEL else "owner_action"
        )
        if ctx.actor.effective_role not in TEAM_ROLES:  # customers: refused before any lookup
            ctx.reject(cap_key, outcome_action, "not_allowed", common.NOT_ALLOWED)
            return
        cap = ctx.spec.capability(cap_key)
        if cap is None:
            ctx.reject(cap_key, outcome_action, "not_found", common.STALE)
            return
        if action not in (ACT_CANCEL, ACT_OWN) or action not in ACTIONS_BY_TYPE.get(cap.type, frozenset()):
            ctx.reject(cap_key, outcome_action, "invalid_input", common.STALE)
            return
        await self._owner_action(ctx, cap, action, arg)

    async def _owner_action(self, ctx: Ctx, cap: AnyCapability, action: str, arg: str) -> None:
        """Shared path for Telegram ``own`` buttons and web-admin events: the one authorization
        check for owner actions (``roles.can_run_owner_actions``)."""
        outcome_action: Literal["cancel", "owner_action"] = (
            "cancel" if action == ACT_CANCEL else "owner_action"
        )
        if not can_run_owner_actions(cap, ctx.actor):
            ctx.reject(cap, outcome_action, "not_allowed", common.NOT_ALLOWED)
            return
        if action == ACT_CANCEL:
            record_id, action_key = parse_int(arg), ACT_CANCEL
        else:
            rid, _, action_key = arg.partition(".")
            record_id = parse_int(rid)
        if record_id is None or not action_key:
            ctx.reject(cap, outcome_action, "invalid_input", common.STALE)
            return
        engine = self._engine(ctx, cap)
        if engine is not None:
            await engine.owner_action(ctx, cap, record_id, action_key)
