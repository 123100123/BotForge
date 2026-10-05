"""Per-event context handed to engines: event, spec, store and a response builder (WP1).

Builder methods (``reply``, ``notify``, ``notify_owner``, ``outcome``, ``effect``, ``reject``,
``stale``, ``show_menu``) are synchronous and only append to the response. Store-touching helpers
(``get_session``, ``set_session``, ``clear_session``, ``create_record``, ``update_record``,
``delete_record``) are async. ``Ctx.create`` reads ``store.owner_actor_id()`` once, so
``notify_owner`` needs no ``await``.
"""

from datetime import datetime
from typing import Any, Literal

from app.botspec.models import AnyCapability, BotSpec, FieldDef
from app.botspec.text_keys import fill_text
from app.runtime import formatting
from app.runtime.callbacks import ACT_HOME, ACT_OPEN, MENU, make_callback
from app.runtime.contracts import (
    Actor,
    Button,
    Effect,
    NoticeKind,
    Outcome,
    OutMessage,
    ReasonCode,
    RuntimeEvent,
    RuntimeResponse,
    audience_allows,
)
from app.runtime.store import Record, Store
from app.runtime.texts import common, default_text

Buttons = list[list[Button]]
OutcomeAction = Literal["book", "cancel", "submit", "owner_action", "order"]
OutcomeResult = Literal["confirmed", "waitlisted", "cancelled", "submitted", "ok", "rejected"]
EffectKind = Literal["record_created", "record_updated", "record_deleted", "notification"]


class _ActingActor:
    """Sentinel: ``create_record(actor_id=ACTING)`` means the acting actor's id."""

    def __repr__(self) -> str:
        return "ACTING"


ACTING = _ActingActor()

MAX_RECORD_ID = 2**63 - 1  # records.id is a bigint


def _cap_key(cap: AnyCapability | str) -> str:
    return cap if isinstance(cap, str) else cap.key


def capability_available(cap: AnyCapability, actor: Actor) -> bool:
    """Whether ``actor`` may use ``cap`` from Telegram: it is enabled and its audience allows the
    actor. Web-admin events bypass this check (the runtime never calls it for them)."""
    return cap.enabled and audience_allows(cap.audience, actor)


class Ctx:
    def __init__(self, event: RuntimeEvent, spec: BotSpec, store: Store, owner_id: str | None) -> None:
        self.event = event
        self.spec = spec
        self.store = store
        self.owner_id = owner_id
        self.messages: list[OutMessage] = []
        self.outcomes: list[Outcome] = []
        self.effects: list[Effect] = []
        self._edit_used = False

    @classmethod
    async def create(cls, event: RuntimeEvent, spec: BotSpec, store: Store) -> "Ctx":
        return cls(event, spec, store, await store.owner_actor_id())

    # --- event shortcuts ---------------------------------------------------------------------

    @property
    def actor(self) -> Actor:
        return self.event.actor

    @property
    def now(self) -> datetime:
        return self.event.now

    @property
    def tz(self) -> str:
        return self.spec.bot.timezone

    @property
    def is_callback(self) -> bool:
        return self.event.kind == "callback"

    # --- response builder --------------------------------------------------------------------

    def reply(self, text: str, buttons: Buttons | None = None, edit: bool | None = None) -> None:
        """Message to the acting actor.

        ``edit`` defaults to True for the first reply to a callback event (it replaces the message
        that carried the button) and False otherwise; only one message per event can be an edit.
        """
        if edit is None:
            edit = self.is_callback and not self._edit_used
        if edit:
            self._edit_used = True
        self.messages.append(
            OutMessage(to_actor_id=self.actor.id, text=text, buttons=buttons or [], edit=edit)
        )

    def notify(
        self, actor_id: str | None, notice: NoticeKind, text: str, buttons: Buttons | None = None
    ) -> None:
        """Message to another actor with ``OutMessage.notice`` set, plus a ``notification`` Effect.

        Does nothing when ``actor_id`` is None.
        """
        if actor_id is None:
            return
        self.messages.append(
            OutMessage(to_actor_id=actor_id, text=text, buttons=buttons or [], notice=notice)
        )
        self.effects.append(Effect(kind="notification", to_actor_id=actor_id))

    def notify_owner(self, notice: NoticeKind, text: str, buttons: Buttons | None = None) -> None:
        """Notify the bot owner; skipped when no owner is linked or the owner is the acting actor."""
        if self.owner_id is None or self.owner_id == self.actor.id:
            return
        self.notify(self.owner_id, notice, text, buttons)

    def outcome(
        self,
        cap: AnyCapability | str,
        action: OutcomeAction,
        result: OutcomeResult,
        reason: ReasonCode | None = None,
        record_id: int | None = None,
    ) -> Outcome:
        out = Outcome(
            capability=_cap_key(cap), action=action, result=result, reason=reason, record_id=record_id
        )
        self.outcomes.append(out)
        return out

    def effect(
        self,
        kind: EffectKind,
        *,
        collection: str | None = None,
        record_id: int | None = None,
        status: str | None = None,
        to_actor_id: str | None = None,
    ) -> Effect:
        eff = Effect(
            kind=kind, collection=collection, record_id=record_id, status=status, to_actor_id=to_actor_id
        )
        self.effects.append(eff)
        return eff

    def reject(
        self,
        cap: AnyCapability | str,
        action: OutcomeAction,
        reason: ReasonCode,
        text: str,
        buttons: Buttons | None = None,
        record_id: int | None = None,
    ) -> Outcome:
        """Refuse a business action: Persian explanation to the actor plus a rejected Outcome."""
        self.reply(text, buttons)
        return self.outcome(cap, action, "rejected", reason=reason, record_id=record_id)

    def response(self) -> RuntimeResponse:
        return RuntimeResponse(
            messages=list(self.messages), outcomes=list(self.outcomes), effects=list(self.effects)
        )

    # --- texts and formatting ----------------------------------------------------------------

    def t(self, cap: AnyCapability, key: str, **placeholders: object) -> str:
        """Bot text ``key`` for ``cap``: the spec override in ``cap.texts`` if present, else the
        engine default from ``runtime/texts/<type>.py`` (form keys fall back to
        ``common.FORM_TEXTS``). Placeholders are filled with ``fill_text`` (values via ``str``).
        Raises KeyError for a key that has no text anywhere (an engine bug).
        """
        template: str | None = None
        for override in getattr(cap, "texts", None) or []:
            if override.key == key:
                template = override.value
                break
        if template is None:
            template = default_text(cap.type, key)
        if template is None:
            template = common.FORM_TEXTS.get(key)
        if template is None:
            raise KeyError(f"no text for {cap.type}.{key}")
        return fill_text(template, {k: str(v) for k, v in placeholders.items()})

    def fmt(self, field: FieldDef, value: Any) -> str:
        """``formatting.format_field_value`` in the bot's timezone."""
        return formatting.format_field_value(field, value, self.tz)

    def fmt_datetime(self, value: Any) -> str:
        return formatting.format_datetime(value, self.tz)

    # --- buttons and menus -------------------------------------------------------------------

    @staticmethod
    def button(label: str, cap: AnyCapability | str, action: str, arg: str | int = "") -> Button:
        return Button(label=label, data=make_callback(_cap_key(cap), action, str(arg)))

    @staticmethod
    def home_button() -> Button:
        return Button(label=common.HOME, data=make_callback(MENU, ACT_HOME))

    def home_row(self) -> list[Button]:
        return [self.home_button()]

    def back_home_row(self, cap: AnyCapability | str, action: str, arg: str | int = "") -> list[Button]:
        """``[بازگشت -> cap:action:arg, منوی اصلی]``."""
        return [self.button(common.BACK, cap, action, arg), self.home_button()]

    def can_use(self, cap: AnyCapability) -> bool:
        """``capability_available(cap, self.actor)``."""
        return capability_available(cap, self.actor)

    def _menu_item_visible(self, cap_key: str) -> bool:
        """A menu item is shown unless its capability exists and is disabled or not allowed for
        the actor (a missing capability keeps the old behaviour: shown, then stale on press)."""
        cap = self.spec.capability(cap_key)
        return cap is None or self.can_use(cap)

    def menu_button_for(
        self, cap: AnyCapability | str, view: str = "main", label: str | None = None
    ) -> Button | None:
        """Button re-opening ``cap`` the way the menu does (first menu item for that capability
        and view), or None if no menu item points at it or the capability is hidden from the
        actor (disabled or not allowed)."""
        key = _cap_key(cap)
        if not self._menu_item_visible(key):
            return None
        item = next((m for m in self.spec.menu if m.capability == key and m.view == view), None)
        if item is None:
            return None
        return Button(label=label or common.BACK, data=make_callback(MENU, ACT_OPEN, item.key))

    def menu_buttons(self) -> Buttons:
        """One row per visible ``spec.menu`` item, callback ``menu:open:<item key>``. Items whose
        capability is disabled or not allowed for the actor are left out."""
        return [
            [Button(label=m.label, data=make_callback(MENU, ACT_OPEN, m.key))]
            for m in self.spec.menu
            if self._menu_item_visible(m.capability)
        ]

    def show_menu(self, text: str | None = None, edit: bool | None = None) -> None:
        self.reply(text if text is not None else common.MENU_HEADER, self.menu_buttons(), edit=edit)

    def stale(self) -> None:
        """The pressed option no longer exists: short Persian notice plus the main menu."""
        self.reply(common.STALE, self.menu_buttons())

    # --- session -----------------------------------------------------------------------------

    async def get_session(self) -> dict[str, Any] | None:
        return await self.store.get_session(self.actor.id)

    async def set_session(self, state: dict[str, Any]) -> None:
        """State shape: ``{"capability": cap.key, "step": str, "vars": {...JSON-safe...}}``."""
        await self.store.set_session(self.actor.id, state)

    async def clear_session(self) -> None:
        await self.store.set_session(self.actor.id, None)

    # --- records with effects ----------------------------------------------------------------

    async def create_record(
        self,
        collection: str,
        data: dict[str, Any],
        *,
        status: str | None = None,
        actor_id: str | _ActingActor | None = ACTING,
        item_id: int | None = None,
    ) -> Record:
        """Create with ``now = event.now``; ``actor_id`` defaults to the acting actor. Adds a
        ``record_created`` Effect."""
        owner = self.actor.id if isinstance(actor_id, _ActingActor) else actor_id
        rec = await self.store.create_record(
            collection, data, status=status, actor_id=owner, item_id=item_id, now=self.now
        )
        self.effect("record_created", collection=collection, record_id=rec.id, status=rec.status)
        return rec

    async def update_record(
        self,
        collection: str,
        record_id: int,
        *,
        data: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> Record:
        """Update with ``now = event.now``. Adds a ``record_updated`` Effect. KeyError if missing."""
        rec = await self.store.update_record(collection, record_id, data=data, status=status, now=self.now)
        self.effect("record_updated", collection=collection, record_id=rec.id, status=rec.status)
        return rec

    async def delete_record(self, collection: str, record_id: int) -> None:
        await self.store.delete_record(collection, record_id)
        self.effect("record_deleted", collection=collection, record_id=record_id)


def parse_int(arg: str) -> int | None:
    """Parse a callback arg as a non-negative int that fits the database (int64); else None."""
    s = formatting.to_ascii_digits(arg.strip())
    if not (s.isdigit() and s.isascii()):
        return None
    value = int(s)
    return value if value <= MAX_RECORD_ID else None
