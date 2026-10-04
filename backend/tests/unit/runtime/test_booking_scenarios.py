"""The nine golden workshop scenarios (examples/workshop.scenarios.json), executed at event level.

This is a minimal stand-in for the scenario runner, written only to prove the booking engine
satisfies every golden scenario: it follows the roadmap's runner/driver semantics (fresh
MemoryStore, fixed start clock, capacity_override on fixed capacity, relative seed datetimes,
buttons found by parsed callback action/arg, owner actions as ``admin`` events, per-actor inboxes
for ``expect_notified``). Every step goes through ``BotRuntime.handle``.
"""

import json
from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.records import validate_record
from app.runtime.contracts import Actor, Outcome, OutMessage, RuntimeResponse
from app.testing.scenario import OWNER, Scenario, Step, resolve_relative
from tests.unit.runtime.harness import EXAMPLES, Harness, load_example
from tests.unit.runtime.test_booking import (
    book_ok,
    booking_spec,
    cancel_via_mine,
    counts,
    find,
    seed_item,
    with_capacity,
)

NAMES = {"ali": "علی", "sara": "سارا", "reza": "رضا", OWNER: "مدیر"}
ACTIVE = ["confirmed", "waitlisted"]


def load_scenarios() -> list[Scenario]:
    raw = json.loads((EXAMPLES / "workshop.scenarios.json").read_text(encoding="utf-8"))
    return [Scenario.model_validate(s) for s in raw]


SCENARIOS = load_scenarios()


class MiniRunner:
    def __init__(self, spec: BotSpec, scenario: Scenario) -> None:
        if scenario.capacity_override is not None:
            spec = with_capacity(spec, scenario.capacity_override)
        self.spec = spec
        self.h = Harness(spec)
        self.refs: dict[str, int] = {}
        self.inbox: dict[str, list[OutMessage]] = {}

    @staticmethod
    def actor(actor_id: str) -> Actor:
        return Actor(id=actor_id, display_name=NAMES.get(actor_id, actor_id), is_owner=actor_id == OWNER)

    async def seed(self, scenario: Scenario) -> None:
        for s in scenario.seed:
            resource = self.spec.resource(s.collection)
            assert resource is not None
            values = {kv.key: resolve_relative(kv.value, self.h.now) for kv in s.values}
            cleaned, errors = validate_record(resource.fields, values)
            assert not errors, errors
            self.refs[s.ref] = await self.h.seed(s.collection, cleaned)

    async def send(self, actor_id: str, kind: str, **kw: Any) -> RuntimeResponse:
        r = await self.h.event(self.actor(actor_id), kind, **kw)
        for m in r.messages:
            if m.to_actor_id != actor_id:
                self.inbox.setdefault(m.to_actor_id, []).append(m)
        return r

    def menu_item(self, cap_key: str, view: str) -> str:
        item = next(m for m in self.spec.menu if m.capability == cap_key and m.view == view)
        return f"menu:open:{item.key}"

    async def latest_booking(self, cap_key: str, actor_id: str, item_id: int, active: bool) -> Any:
        rows = await self.h.store.list_records(
            cap_key, actor_id=actor_id, item_id=item_id, status_in=ACTIVE if active else None
        )
        return rows[-1] if rows else None

    @staticmethod
    def check_outcome(resp: RuntimeResponse, step: Step, ok_results: tuple[str, ...] = ()) -> None:
        assert resp.outcomes, f"no outcome for {step}"
        o: Outcome = resp.outcomes[-1]
        if step.expect is None:
            return
        if step.expect == "rejected":
            assert o.result == "rejected", o
            if step.reason is not None:
                assert o.reason == step.reason, o
        elif ok_results:
            assert o.result in ok_results, o
        else:
            assert o.result == step.expect, o

    async def run_step(self, step: Step) -> None:
        cap = step.capability or ""
        item_id = self.refs.get(step.item or "")
        if step.do == "book":
            assert step.actor is not None and item_id is not None
            await self.send(step.actor, "start")
            r = await self.send(step.actor, "callback", data=self.menu_item(cap, "main"))
            r = await self.send(step.actor, "callback", data=find(r, "item", item_id).data)
            r = await self.send(step.actor, "callback", data=find(r, "book", item_id).data)
            self.check_outcome(r, step)
        elif step.do == "cancel":
            assert step.actor is not None and item_id is not None
            booking = await self.latest_booking(cap, step.actor, item_id, active=True)
            assert booking is not None, f"{step.actor} has no active booking"
            r = await self.send(step.actor, "callback", data=self.menu_item(cap, "mine"))
            r = await self.send(step.actor, "callback", data=find(r, "cancel", booking.id).data)
            self.check_outcome(r, step)
        elif step.do == "owner_action":
            assert step.target_actor is not None and item_id is not None and step.action == "cancel"
            booking = await self.latest_booking(cap, step.target_actor, item_id, active=True)
            assert booking is not None
            r = await self.send(step.actor or OWNER, "admin", data=f"{cap}:cancel:{booking.id}")
            self.check_outcome(r, step, ok_results=("ok", "cancelled") if step.expect == "ok" else ())
        elif step.do == "expect_booking":
            assert step.actor is not None and item_id is not None
            booking = await self.latest_booking(cap, step.actor, item_id, active=False)
            assert (booking.status if booking else "none") == step.expect
        elif step.do == "expect_counts":
            assert item_id is not None
            store = self.h.store
            if step.confirmed is not None:
                assert (
                    await store.count_records(cap, status_in=["confirmed"], item_id=item_id) == step.confirmed
                )
            if step.waitlisted is not None:
                assert (
                    await store.count_records(cap, status_in=["waitlisted"], item_id=item_id)
                    == step.waitlisted
                )
        elif step.do == "expect_notified":
            assert step.actor is not None
            box = self.inbox.get(step.actor, [])
            assert any(
                (step.event is None or m.notice == step.event)
                and (step.contains is None or step.contains in m.text)
                for m in box
            ), f"{step.actor} inbox: {[(m.notice, m.text) for m in box]}"
            self.inbox[step.actor] = []
        elif step.do == "open":
            assert step.actor is not None
            r = await self.send(step.actor, "callback", data=self.menu_item(cap, step.view or "main"))
            if item_id is not None:
                r = await self.send(step.actor, "callback", data=find(r, "item", item_id).data)
            if step.contains is not None:
                assert any(step.contains in m.text for m in r.messages)
        elif step.do == "advance_time":
            self.h.advance(step.hours or 0)
        else:  # pragma: no cover - request steps are not in the workshop scenarios
            raise AssertionError(step.do)


def test_all_nine_golden_scenarios_present() -> None:
    assert len(SCENARIOS) == 9


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
async def test_golden_scenario(scenario: Scenario) -> None:
    runner = MiniRunner(load_example("workshop.botspec.json"), scenario)
    await runner.seed(scenario)
    for i, step in enumerate(scenario.steps):
        try:
            await runner.run_step(step)
        except AssertionError as exc:
            raise AssertionError(f"{scenario.id} step {i} ({step.do}): {exc}") from exc


# --- the same flows hand-encoded, so a regression points at the exact rule --------------------


async def test_golden_capacity_10_eleventh_waitlisted() -> None:
    h = Harness(booking_spec(capacity=10))
    w = await seed_item(h)
    for i in range(1, 11):
        await book_ok(h, f"u{i}", w)
    await book_ok(h, "u11", w, "waitlisted")
    assert await counts(h, w) == (10, 1)


async def test_golden_cancel_frees_seat_without_waitlisted() -> None:
    h = Harness(booking_spec(capacity=2))
    w = await seed_item(h)
    ali = await book_ok(h, "ali", w)
    await book_ok(h, "sara", w)
    r = await cancel_via_mine(h, "ali", ali)
    assert ("owner", "cancelled") in [(m.to_actor_id, m.notice) for m in r.messages]
    assert await counts(h, w) == (1, 0)
    await book_ok(h, "reza", w)
    assert await counts(h, w) == (2, 0)
