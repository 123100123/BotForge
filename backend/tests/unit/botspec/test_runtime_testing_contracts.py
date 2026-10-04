from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.requirements import Requirements, RequirementsDelta
from app.runtime.callbacks import (
    ACT_CANCEL,
    ACT_OWN,
    ACTIONS_BY_TYPE,
    MENU,
    CallbackError,
    make_callback,
    parse_callback,
)
from app.runtime.contracts import Actor, Button, OutMessage, RuntimeEvent
from app.runtime.store import Record
from app.testing.scenario import Scenario, Step, TestReport, resolve_relative

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

# ---------------------------------------------------------------- callbacks


@pytest.mark.parametrize(
    ("cap", "action", "arg"),
    [
        (MENU, "home", ""),
        (MENU, "open", "workshops"),
        ("book_workshop", "book", "42"),
        ("repair", ACT_OWN, "17.approve"),
        ("x", "ans", "2"),
        ("info", "show", "a:b"),
    ],
)
def test_callback_roundtrip(cap: str, action: str, arg: str) -> None:
    data = make_callback(cap, action, arg)
    assert data == f"{cap}:{action}:{arg}"
    assert parse_callback(data) == (cap, action, arg)


def test_callback_length_limit() -> None:
    longest_cap = "c" * 24
    assert len(make_callback(longest_cap, ACT_CANCEL, "9" * 12).encode()) <= 64
    with pytest.raises(CallbackError):
        make_callback(longest_cap, ACT_OWN, "999999999999." + "a" * 24)
    with pytest.raises(CallbackError):
        make_callback("info", "show", "ص" * 30)  # 60 bytes of UTF-8 in the arg
    with pytest.raises(CallbackError):
        parse_callback("x" * 65)


@pytest.mark.parametrize(
    "call",
    [
        lambda: make_callback("book_workshop", "delete", "1"),
        lambda: make_callback("Bad", "list"),
        lambda: parse_callback("book_workshop:book"),
        lambda: parse_callback("book_workshop:zap:1"),
    ],
)
def test_callback_rejects_unknown(call: Any) -> None:
    with pytest.raises(CallbackError):
        call()


def test_callback_vocabulary() -> None:
    assert ACTIONS_BY_TYPE[MENU] == {"home", "open"}
    assert {"list", "item", "book", "mine", "cancel", "ans", "skip", "stop"} == ACTIONS_BY_TYPE["booking"]
    assert {"new", "pick", "mine", "own"} <= ACTIONS_BY_TYPE["request"]
    assert ACTIONS_BY_TYPE["info"] == {"show"} and ACTIONS_BY_TYPE["catalog"] == {"list", "item"}


# ---------------------------------------------------------------- runtime contracts


def test_runtime_event_and_messages() -> None:
    owner = Actor(id="owner", display_name="مدیر", is_owner=True)
    ev = RuntimeEvent(
        bot_id="b1",
        env="sandbox",
        actor=owner,
        kind="admin",
        data=make_callback("book_workshop", ACT_CANCEL, "5"),
        now=NOW,
    )
    assert ev.kind == "admin"
    with pytest.raises(ValidationError):
        RuntimeEvent(bot_id="b1", env="live", actor=owner, kind="start", now=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        Button(label="x", data="a" * 65)
    msg = OutMessage(to_actor_id="reza", text="شما تأیید شدید", notice="promoted")
    assert msg.notice == "promoted" and msg.buttons == []
    with pytest.raises(ValidationError):
        OutMessage(to_actor_id="reza", text="x", notice="hello")  # type: ignore[arg-type]
    rec = Record(id=1, collection="workshop", data={"title": "x"}, created_at=NOW, updated_at=NOW)
    assert rec.status is None


def test_requirements_models() -> None:
    req = Requirements.model_validate(
        {
            "business_summary": "آموزشگاه",
            "items": [{"id": "R1", "kind": "rule", "statement": "ظرفیت ۱۰ نفر", "status": "confirmed"}],
            "unsupported": [{"statement": "پرداخت", "reason": "پشتیبانی نمی‌شود", "alternative": None}],
            "open_questions": [],
        }
    )
    assert req.items[0].id == "R1"
    RequirementsDelta(added=[], changed=req.items, removed=["R2"], unsupported=[], open_questions=[])
    with pytest.raises(ValidationError):
        Requirements.model_validate(
            {"business_summary": "x", "items": [], "unsupported": [], "open_questions": [], "extra": {}}
        )


# ---------------------------------------------------------------- scenarios


def test_golden_scenarios_load(scenarios_data: list[dict[str, Any]]) -> None:
    scenarios = [Scenario.model_validate(s) for s in scenarios_data]
    assert 6 <= len(scenarios) <= 9
    assert len({s.id for s in scenarios}) == len(scenarios)
    owner_cancel = [st for s in scenarios for st in s.steps if st.do == "owner_action"]
    assert [(st.action, st.item, st.target_actor, st.expect) for st in owner_cancel] == [
        ("cancel", "w1", "ali", "ok")
    ]
    real = [s for s in scenarios if s.capacity_override is None]
    assert len(real) == 1
    actors = [st.actor for st in real[0].steps if st.do == "book"]
    assert actors == [f"u{i}" for i in range(1, 12)]
    assert all(s.capacity_override == 2 for s in scenarios if s is not real[0])
    events = [st.event for s in scenarios for st in s.steps if st.do == "expect_notified"]
    assert "promoted" in events
    assert all(st.contains is None for s in scenarios for st in s.steps if st.do == "expect_notified")


def test_golden_scenarios_reference_golden_requirements(
    scenarios_data: list[dict[str, Any]], requirements_data: dict[str, Any]
) -> None:
    reqs = Requirements.model_validate(requirements_data)
    known = {r.id for r in reqs.items}
    assert known == {f"R{i}" for i in range(1, 8)}
    assert reqs.unsupported == [] and reqs.open_questions == []
    capacity_req = "R2"
    for s in (Scenario.model_validate(d) for d in scenarios_data):
        assert s.requirement_ids, f"{s.id} has no requirement ids"
        assert set(s.requirement_ids) <= known, s.id
        if s.capacity_override is None:
            assert s.requirement_ids == [capacity_req], s.id
        else:
            assert capacity_req not in s.requirement_ids, s.id


def test_owner_action_step_item_optional() -> None:
    Step.model_validate(
        {
            "do": "owner_action",
            "capability": "b",
            "action": "cancel",
            "target_actor": "ali",
            "item": "w1",
            "expect": "ok",
        }
    )
    Step.model_validate({"do": "owner_action", "capability": "r", "action": "approve", "target_actor": "ali"})
    with pytest.raises(ValidationError):
        Step.model_validate(
            {"do": "owner_action", "capability": "b", "action": "cancel", "item": "w1", "expect": "cancelled"}
        )


VALID_STEPS: list[dict[str, Any]] = [
    {"do": "book", "actor": "ali", "capability": "b", "item": "w1"},
    {
        "do": "book",
        "actor": "ali",
        "capability": "b",
        "item": "w1",
        "expect": "rejected",
        "reason": "capacity_full",
    },
    {"do": "cancel", "actor": "u11", "capability": "b", "item": "w1", "expect": "cancelled"},
    {"do": "expect_booking", "actor": "ali", "capability": "b", "item": "w1", "expect": "none"},
    {"do": "expect_counts", "capability": "b", "item": "w1", "waitlisted": 0},
    {"do": "submit_request", "actor": "ali", "capability": "r", "form": [{"key": "a", "value": "b"}]},
    {"do": "owner_action", "capability": "r", "action": "approve", "target_actor": "ali", "expect": "ok"},
    {"do": "expect_request", "actor": "ali", "capability": "r", "expect": "approved"},
    {"do": "expect_notified", "actor": "owner"},
    {"do": "expect_notified", "actor": "ali", "event": "status_changed", "contains": "تأیید"},
    {"do": "open", "actor": "ali", "capability": "b", "view": "mine", "contains": "عکاسی"},
    {"do": "advance_time", "hours": 1.5},
]

INVALID_STEPS: list[dict[str, Any]] = [
    {"do": "book", "actor": "ali", "capability": "b"},  # no item
    {"do": "book", "actor": "ali", "capability": "b", "item": "w1", "expect": "ok"},
    {"do": "cancel", "actor": "ali", "capability": "b", "item": "w1", "reason": "duplicate"},
    {"do": "expect_booking", "actor": "ali", "capability": "b", "item": "w1"},
    {"do": "expect_counts", "capability": "b", "item": "w1"},
    {"do": "expect_counts", "capability": "b", "item": "w1", "confirmed": 1, "expect": "confirmed"},
    {"do": "owner_action", "capability": "r", "action": "approve"},
    {"do": "expect_notified", "actor": "ali", "event": "hello"},
    {"do": "open", "actor": "ali", "capability": "b", "event": "promoted"},
    {"do": "book", "actor": "ali", "capability": "b", "item": "w1", "view": "mine"},
    {"do": "advance_time", "hours": 0},
    {"do": "advance_time"},
    {"do": "book", "actor": "Ali", "capability": "b", "item": "w1"},
    {"do": "cancel", "actor": "ali", "capability": "b", "item": "w1", "form": [{"key": "a", "value": "b"}]},
    {"do": "book", "actor": "ali", "capability": "b", "item": "w1", "hours": 2},
    {"do": "fly", "actor": "ali"},
    {"do": "book", "actor": "ali", "capability": "b", "item": "w1", "unknown": 1},
]


@pytest.mark.parametrize("step", VALID_STEPS)
def test_valid_steps(step: dict[str, Any]) -> None:
    Step.model_validate(step)


@pytest.mark.parametrize("step", INVALID_STEPS)
def test_invalid_steps(step: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Step.model_validate(step)


def _scenario(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "s",
        "title": "t",
        "source": "acceptance",
        "seed": [{"ref": "w1", "collection": "workshop", "values": []}],
        "steps": [{"do": "book", "actor": "ali", "capability": "b", "item": "w1"}],
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    "bad",
    [
        {"steps": []},
        {"capacity_override": 0},
        {"steps": [{"do": "book", "actor": "ali", "capability": "b", "item": "w9"}]},
        {"seed": [{"ref": "w1", "collection": "workshop", "values": []}] * 2},
        {"source": "manual"},
    ],
)
def test_invalid_scenarios(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(_scenario(**bad))


def test_report_model() -> None:
    TestReport(total=0, passed=0, failed=0, results=[], duration_ms=0)


def test_resolve_relative() -> None:
    assert resolve_relative("+48h", NOW) == "2026-10-07T12:00:00+00:00"
    assert resolve_relative("-1h", NOW) == "2026-10-05T11:00:00+00:00"
    assert resolve_relative("+30m", NOW) == "2026-10-05T12:30:00+00:00"
    assert resolve_relative("+2d", NOW) == "2026-10-07T12:00:00+00:00"
    assert resolve_relative("+۱.۵h", NOW) == "2026-10-05T13:30:00+00:00"
    tehran = NOW.astimezone(__import__("datetime").timezone(timedelta(hours=3, minutes=30)))
    assert resolve_relative("+1h", tehran) == "2026-10-05T13:00:00+00:00"
    assert resolve_relative("2026-10-06T10:00:00+00:00", NOW) == "2026-10-06T10:00:00+00:00"
    assert resolve_relative("کارگاه", NOW) == "کارگاه"
    with pytest.raises(ValueError):
        resolve_relative("+1h", datetime(2026, 1, 1))


def test_llm_facing_json_schemas_build() -> None:
    from app.botspec.models import BotSpec
    from app.botspec.patch import PatchOp

    for model in (BotSpec, Scenario, Requirements, RequirementsDelta, PatchOp):
        schema = model.model_json_schema()
        assert schema["type"] == "object"
