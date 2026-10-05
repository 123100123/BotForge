"""Runtime contracts: events in, responses out (frozen contract, WP0).

The concrete ``BotRuntime`` lives in ``runtime/runtime.py`` (WP1) and must satisfy
``RuntimeHandler``. The runtime is deterministic: its only inputs are the event (including
``now``), the spec, and the store.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, field_validator

from app.botspec.models import Audience, BotSpec, Role
from app.runtime.callbacks import MAX_CALLBACK_BYTES

if TYPE_CHECKING:
    from app.runtime.store import Store


class Actor(BaseModel):
    id: str  # Telegram user id as string, or persona id ("ali"); "owner" = the bot owner persona
    display_name: str
    is_owner: bool = False
    role: Role = "customer"  # stored role of the bot user; the owner is a manager regardless

    @property
    def effective_role(self) -> Role:
        """The role used for gating: "manager" for the owner, else the stored role."""
        return "manager" if self.is_owner else self.role


def audience_allows(audience: Audience, actor: Actor) -> bool:
    """Whether ``actor`` may use a capability with this ``audience``.

    everyone: all actors; staff: staff and managers; managers: managers only (the owner is one).
    """
    role = actor.effective_role
    if audience == "everyone":
        return True
    if audience == "staff":
        return role in ("staff", "manager")
    return role == "manager"


class RuntimeEvent(BaseModel):
    """One inbound interaction.

    kind:
      start    - /start (clears the session, shows welcome + main menu)
      text     - free text (session-owned form input; otherwise re-shows the menu)
      callback - an inline button press; ``data`` is callback data from ``runtime/callbacks.py``
      admin    - an owner action issued from the web admin; actor is the owner; ``data`` is
                 callback data. Booking: ``make_callback(cap_key, "cancel", str(record_id))``
                 (Outcome.action = "cancel"; ignores the cancellation deadline). Request:
                 ``make_callback(cap_key, "own", f"{record_id}.{owner_action_key}")``
                 (Outcome.action = "owner_action").

    chat_type: where the interaction happened. "group" (a Telegram group the bot was added to):
      start and text events get an empty response, a ``menu`` callback gets an empty response,
      other callbacks route normally (engines handle group specifics). Admin events ignore it.
    """

    bot_id: str
    env: Literal["live", "sandbox"]
    actor: Actor
    kind: Literal["start", "text", "callback", "admin"]
    text: str | None = None
    data: str | None = None  # callback data
    now: datetime  # timezone-aware UTC; always injected
    chat_type: Literal["private", "group"] = "private"

    @field_validator("now")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return v


class Button(BaseModel):
    label: str
    data: str  # <= 64 bytes UTF-8

    @field_validator("data")
    @classmethod
    def _limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_CALLBACK_BYTES:
            raise ValueError(f"button data exceeds {MAX_CALLBACK_BYTES} bytes")
        return v


NoticeKind = Literal[
    "booked",
    "waitlisted",
    "cancelled",
    "promoted",
    "submitted",
    "status_changed",
    "ordered",
    "order_status_changed",
    "reminder",
    "announcement",
]


class OutMessage(BaseModel):
    to_actor_id: str
    text: str  # plain text; the adapter escapes it
    buttons: list[list[Button]] = []
    edit: bool = False  # replace the message that carried the callback
    notice: NoticeKind | None = None  # set on notifications sent to someone other than the actor


ReasonCode = Literal[
    "capacity_full",
    "duplicate",
    "user_limit",
    "booking_closed",
    "cancel_deadline_passed",
    "cancellation_disabled",
    "not_found",
    "invalid_input",
    "not_allowed",
    "out_of_stock",
]


class Outcome(BaseModel):  # machine-readable result of a business action
    capability: str
    action: Literal["book", "cancel", "submit", "owner_action", "order"]
    result: Literal["confirmed", "waitlisted", "cancelled", "submitted", "ok", "rejected"]
    reason: ReasonCode | None = None
    record_id: int | None = None


class Effect(BaseModel):
    kind: Literal["record_created", "record_updated", "record_deleted", "notification"]
    collection: str | None = None
    record_id: int | None = None
    status: str | None = None
    to_actor_id: str | None = None


class RuntimeResponse(BaseModel):
    messages: list[OutMessage]
    outcomes: list[Outcome] = []
    effects: list[Effect] = []


class RuntimeHandler(Protocol):
    """What adapters and drivers call. Implemented by ``runtime.runtime.BotRuntime``."""

    async def handle(self, event: RuntimeEvent, spec: BotSpec, store: "Store") -> RuntimeResponse: ...
