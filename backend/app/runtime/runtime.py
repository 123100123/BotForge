"""``BotRuntime``: the deterministic event router every adapter calls (WP1).

Inputs are only the event (including ``event.now``), the spec and the store. Routing:

  start                      clear session; welcome text + main menu
  text, no session           welcome text + main menu
  text, session              engine.on_text of the session's capability (gone -> drop session, menu)
  callback menu:home         main menu (clears any session)
  callback menu:open:<item>  engine.open(cap, item.view) (clears any session)
  callback <cap>:own:<r.k>   staff/managers -> engine.owner_action(record_id, k)
  callback <cap>:<act>:<arg> engine.on_callback; a non-form action (not ans/skip/stop) first
                             clears the actor's session, so a form abandoned by navigating away
                             never captures later text
  admin <cap>:cancel:<id>    staff/managers -> engine.owner_action(id, "cancel")   Outcome.action cancel
  admin <cap>:own:<id>.<k>   staff/managers -> engine.owner_action(id, k)          Outcome.action owner_action

Malformed or stale data (bad format, unknown menu item or capability, action not valid for the
capability type) gets a short Persian "no longer available" reply plus the main menu and never
raises. A capability type whose engine module does not exist yet gets a "not available yet" reply.
Every event upserts the acting user first.

Owner actions (roles, roadmap: Roles): who may run them is ``roles.can_run_owner_actions``, decided
on ``actor.effective_role`` (the owner is a manager): staff and managers on a customer-facing
capability (``audience="everyone"``), managers only on an internal one (``audience`` staff or
managers, whose submitters are staff). Anyone else gets ``Outcome(result="rejected",
reason="not_allowed")`` and never reaches the engine. Customers are refused before the capability is
even looked up, as before roles existed.

Capability gating (Business OS): a capability that is disabled (``enabled=False``) or whose
``audience`` does not allow the actor (``ctx.capability_available``) is treated exactly like a
missing one on the Telegram paths (callback, menu open, text with a session): stale reply plus the
main menu, never an engine call; the main menu hides it. Admin events bypass gating.

Group context (``event.chat_type == "group"``): start and text events and any ``menu`` callback
return an empty response without side effects (no user upsert, no session change); other
callbacks route normally. Admin events are unaffected.
"""

from typing import Literal

from app.botspec.models import AnyCapability, BotSpec
from app.roles import TEAM_ROLES, can_run_owner_actions
from app.runtime.callbacks import (
    ACT_CANCEL,
    ACT_HOME,
    ACT_OPEN,
    ACT_OWN,
    ACTIONS_BY_TYPE,
    FORM_ACTIONS,
    MENU,
    CallbackError,
    parse_callback,
)
from app.runtime.contracts import RuntimeEvent, RuntimeResponse
from app.runtime.ctx import Ctx, parse_int
from app.runtime.engines import EngineUnavailable, get_engine
from app.runtime.engines.base import Engine
from app.runtime.store import Store
from app.runtime.texts import common


def _group_noop(event: RuntimeEvent) -> bool:
    """Group events the runtime ignores: start, text, and any ``menu`` callback (malformed
    callback data included: a group never gets the stale menu)."""
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
    return cap_key == MENU


class BotRuntime:
    async def handle(self, event: RuntimeEvent, spec: BotSpec, store: Store) -> RuntimeResponse:
        if _group_noop(event):
            return RuntimeResponse(messages=[])
        await store.upsert_user(event.actor)
        ctx = await Ctx.create(event, spec, store)
        if event.kind == "start":
            await ctx.clear_session()
            self._welcome(ctx)
        elif event.kind == "text":
            await self._on_text(ctx, event.text or "")
        elif event.kind == "callback":
            await self._on_callback(ctx, event.data)
        elif event.kind == "admin":
            await self._on_admin(ctx, event.data)
        return ctx.response()

    # --- routes ------------------------------------------------------------------------------

    @staticmethod
    def _welcome(ctx: Ctx) -> None:
        ctx.show_menu(ctx.spec.bot.welcome_text)

    @staticmethod
    def _engine(ctx: Ctx, cap: AnyCapability) -> Engine | None:
        try:
            return get_engine(cap.type)
        except EngineUnavailable:
            ctx.reply(common.NOT_AVAILABLE, ctx.menu_buttons())
            return None

    async def _on_text(self, ctx: Ctx, text: str) -> None:
        session = await ctx.get_session()
        if session is None:
            self._welcome(ctx)
            return
        cap_key = session.get("capability") if isinstance(session, dict) else None
        cap = ctx.spec.capability(cap_key) if isinstance(cap_key, str) else None
        if cap is None:
            await ctx.clear_session()
            self._welcome(ctx)
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
        if cap_key == MENU:
            await self._on_menu(ctx, action, arg)
            return
        cap = ctx.spec.capability(cap_key)
        if cap is None or action not in ACTIONS_BY_TYPE.get(cap.type, frozenset()) or not ctx.can_use(cap):
            ctx.stale()
            return
        if action not in FORM_ACTIONS:
            await ctx.clear_session()
        if action == ACT_OWN:
            await self._owner_action(ctx, cap, action, arg)
            return
        engine = self._engine(ctx, cap)
        if engine is not None:
            await engine.on_callback(ctx, cap, action, arg)

    async def _on_menu(self, ctx: Ctx, action: str, arg: str) -> None:
        await ctx.clear_session()
        if action == ACT_HOME:
            ctx.show_menu()
            return
        item = next((m for m in ctx.spec.menu if m.key == arg), None) if action == ACT_OPEN else None
        cap = ctx.spec.capability(item.capability) if item is not None else None
        if item is None or cap is None or not ctx.can_use(cap):
            ctx.stale()
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
