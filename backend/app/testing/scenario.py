"""Scenario and test-report models (frozen contract, WP0).

Scenarios are semantic: steps name business actions, and drivers perform them through the same
RuntimeEvents a user would send. Expectations on actions compare the Outcome the runtime returns;
state expectations read the store.
"""

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, model_validator

from app.botspec.models import Key, StrictModel
from app.botspec.records import normalize_digits, to_utc_iso
from app.runtime.contracts import NoticeKind, ReasonCode

OWNER = "owner"  # reserved actor id: the bot owner persona (is_owner=True)
ActorId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,23}$")]

StepDo = Literal[
    "book",
    "cancel",
    "expect_booking",
    "expect_counts",
    "submit_request",
    "owner_action",
    "expect_request",
    "expect_notified",
    "open",
    "advance_time",
]


class KV(StrictModel):
    key: str
    value: str  # value in string form; coerced by field type


class SeedRecord(StrictModel):
    ref: str  # name used by steps, e.g. "w1"
    collection: Key  # resource key
    values: list[KV]  # datetime values may be relative: "+48h", "-1h" (see resolve_relative)


# Per-`do` rules: required fields, allowed `expect` values (None = expect must be omitted;
# "*" = any non-empty string, required), and whether `expect` is mandatory.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "book": ("actor", "capability", "item"),
    "cancel": ("actor", "capability", "item"),
    "expect_booking": ("actor", "capability", "item", "expect"),
    "expect_counts": ("capability", "item"),
    "submit_request": ("actor", "capability"),
    "owner_action": ("capability", "action", "target_actor"),
    "expect_request": ("actor", "capability", "expect"),
    "expect_notified": ("actor",),
    "open": ("actor", "capability"),
    "advance_time": ("hours",),
}
_EXPECT: dict[str, frozenset[str] | None] = {
    "book": frozenset({"confirmed", "waitlisted", "rejected"}),
    "cancel": frozenset({"cancelled", "rejected"}),
    "submit_request": frozenset({"submitted", "rejected"}),
    "owner_action": frozenset({"ok", "rejected"}),
    "expect_booking": frozenset({"confirmed", "waitlisted", "cancelled", "none"}),
    "expect_request": frozenset({"*"}),
    "expect_counts": None,
    "expect_notified": None,
    "open": None,
    "advance_time": None,
}
ACTION_STEPS = frozenset({"book", "cancel", "submit_request", "owner_action"})


class Step(StrictModel):
    """One semantic step. A single flat model; a validator enforces the per-`do` fields.

    do               required                         expect
    book             actor, capability, item          confirmed|waitlisted|rejected (optional)
    cancel           actor, capability, item          cancelled|rejected (optional)
    submit_request   actor, capability [item, form]   submitted|rejected (optional)
    owner_action     capability, action, target_actor ok|rejected (optional); actor defaults to
                                                      "owner" (another actor tests not_allowed);
                                                      acts on target_actor's latest request
    expect_booking   actor, capability, item, expect  confirmed|waitlisted|cancelled|none
                                                      (the actor's latest booking on the item)
    expect_counts    capability, item, and confirmed and/or waitlisted
    expect_request   actor, capability, expect        a status key of the actor's latest request
    expect_notified  actor [event, contains]          see below
    open             actor, capability [item, view, contains]   view defaults to "main"; item
                                                      opens that item's detail; contains is
                                                      checked against the reply texts
    advance_time     hours (> 0)                      moves the scenario clock forward

    `reason` is allowed only with expect == "rejected" and then must match Outcome.reason.
    `form` (KV list) is allowed only on book and submit_request.
    Actor ids match ^[a-z][a-z0-9_]{0,23}$; "owner" is reserved for the bot owner.

    expect_notified semantics: the runner keeps a per-actor inbox of messages that actor received
    while NOT being the acting actor of the event. The step passes if the actor's inbox holds a
    message whose OutMessage.notice equals `event` (if given) and whose text contains `contains`
    (if given), or any message if neither is given. The step then clears that actor's inbox.
    """

    do: StepDo
    actor: ActorId | None = None  # persona id: "ali", "sara", "reza", "u1", "owner"
    capability: Key | None = None
    item: str | None = None  # seed ref
    form: list[KV] = []
    action: Key | None = None  # owner_action key
    target_actor: ActorId | None = None  # owner_action: whose request
    expect: str | None = None
    reason: ReasonCode | None = None  # with expect == rejected
    confirmed: int | None = None  # expect_counts
    waitlisted: int | None = None  # expect_counts
    contains: str | None = None  # expect_notified / open: substring
    hours: float | None = None  # advance_time
    view: Literal["main", "mine"] | None = None  # open
    event: NoticeKind | None = None  # expect_notified

    @model_validator(mode="after")
    def _check_shape(self) -> "Step":
        do = self.do
        missing = [f for f in _REQUIRED[do] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"step '{do}' requires {', '.join(missing)}")
        allowed = _EXPECT[do]
        if allowed is None:
            if self.expect is not None:
                raise ValueError(f"step '{do}' takes no 'expect'")
        elif self.expect is not None and "*" not in allowed and self.expect not in allowed:
            raise ValueError(f"step '{do}': expect must be one of {sorted(allowed)}")
        if self.reason is not None and self.expect != "rejected":
            raise ValueError("'reason' is only allowed with expect == 'rejected'")
        if self.form and do not in ("book", "submit_request"):
            raise ValueError("'form' is only allowed on book and submit_request")
        if do == "expect_counts":
            if self.confirmed is None and self.waitlisted is None:
                raise ValueError("expect_counts needs 'confirmed' and/or 'waitlisted'")
        elif self.confirmed is not None or self.waitlisted is not None:
            raise ValueError("'confirmed'/'waitlisted' are only allowed on expect_counts")
        if do == "advance_time":
            if self.hours is None or self.hours <= 0:
                raise ValueError("advance_time needs hours > 0")
        elif self.hours is not None:
            raise ValueError("'hours' is only allowed on advance_time")
        if self.view is not None and do != "open":
            raise ValueError("'view' is only allowed on open")
        if self.event is not None and do != "expect_notified":
            raise ValueError("'event' is only allowed on expect_notified")
        if self.contains is not None and do not in ("expect_notified", "open"):
            raise ValueError("'contains' is only allowed on expect_notified and open")
        if (self.action is not None or self.target_actor is not None) and do != "owner_action":
            raise ValueError("'action'/'target_actor' are only allowed on owner_action")
        return self


class Scenario(StrictModel):
    id: str
    title: str  # Persian
    source: Literal["derived", "acceptance"]
    requirement_ids: list[str] = []
    capability_keys: list[Key] = []
    # Before running, the runner sets capacity.value to this number on every booking capability
    # whose capacity mode is "fixed" (in a copy of the spec); ignored for "per_item".
    capacity_override: int | None = None
    seed: list[SeedRecord] = []
    steps: list[Step]

    @model_validator(mode="after")
    def _check_refs(self) -> "Scenario":
        if not self.steps:
            raise ValueError("a scenario needs at least one step")
        if self.capacity_override is not None and self.capacity_override < 1:
            raise ValueError("capacity_override must be >= 1")
        refs = [s.ref for s in self.seed]
        if len(set(refs)) != len(refs):
            raise ValueError("seed refs must be unique")
        for i, step in enumerate(self.steps):
            if step.item is not None and step.item not in refs:
                raise ValueError(f"step {i}: item '{step.item}' is not a seed ref")
        return self


class StepResult(BaseModel):
    index: int
    passed: bool
    message: str | None = None
    narrative: str  # Persian sentence


class TranscriptEntry(BaseModel):
    actor: str
    direction: Literal["in", "out"]  # in = sent by the actor, out = received by the actor
    text: str
    buttons: list[str] = []  # button labels


class ScenarioResult(BaseModel):
    scenario_id: str
    passed: bool
    failed_step: int | None = None
    steps: list[StepResult]
    transcript: list[TranscriptEntry]


class TestReport(BaseModel):
    __test__ = False  # not a pytest test class

    total: int
    passed: int
    failed: int
    results: list[ScenarioResult]
    duration_ms: int


_RELATIVE_RE = re.compile(r"^([+-])(\d+(?:\.\d+)?)([mhd])$")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


def resolve_relative(value: str, now: datetime) -> str:
    """Resolve "+48h", "-1h", "+30m", "+2d" against ``now`` to the canonical UTC ISO string.

    Any other value is returned unchanged (absolute datetimes go through validate_record).
    ``now`` must be timezone-aware.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    m = _RELATIVE_RE.fullmatch(normalize_digits(value.strip()))
    if m is None:
        return value
    sign, amount, unit = m.groups()
    delta = timedelta(**{_UNITS[unit]: float(amount)})
    return to_utc_iso(now + delta if sign == "+" else now - delta)
