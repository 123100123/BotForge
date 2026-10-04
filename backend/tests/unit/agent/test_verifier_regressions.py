"""Regressions from the independent verifier's scripted runs (WP6/WP7 follow-up)."""

import copy

import pytest

from app.agent.context import Limits
from app.agent.llm import ToolCall
from app.agent.modify import merge_delta, normalize_statement
from app.agent.orchestrator import OrchestratorError
from app.agent.phases import STEP_LIMIT_TEXT
from app.agent.phases.testgen import NO_ACCEPTANCE
from app.agent.requirements import Requirements, RequirementsDelta
from tests.unit.agent.helpers import (
    CAPACITY_VALUE,
    DEADLINE_HOURS,
    MOD_CAPACITY,
    MOD_DEADLINE,
    build_ok,
    capacity_requirement,
    capacity_scenario,
    change_out,
    deadline_requirement,
    deadline_scenarios,
    finish,
    golden_acceptance,
    golden_requirements,
    harness,
    modify_harness,
    patch,
    run_tests,
    sample_out,
    set_spec,
    supersede,
    triage_out,
    understand_out,
)


def two_round_scripts(round2_testgen: list) -> dict:
    """The verifier's script: round 1 adds a deadline (R8); during review the owner asks for the
    capacity change and the model returns a delta with ONLY the capacity change."""
    return {
        "structured": {
            "triage": [triage_out()],
            "understand": [
                change_out(added=[deadline_requirement("R99")]),
                change_out(changed=[capacity_requirement(12)]),
            ],
            "testgen": [{"scenarios": deadline_scenarios("R8")}, {"scenarios": round2_testgen}],
        },
        "loops": {
            "build": [
                [[patch({"op": "set", "path": DEADLINE_HOURS, "value": 2})], [finish()]],
                [[patch({"op": "set", "path": CAPACITY_VALUE, "value": 12})], [finish()]],
            ],
            "repair": [[[supersede("golden_capacity_10_real")], [run_tests()], [finish()]]],
        },
    }


# --------------------------------------------------------------------------- item 1


async def test_second_request_during_review_keeps_the_first_change_and_its_tests() -> None:
    h = modify_harness(two_round_scripts([capacity_scenario(12)]))
    run = await h.start_change(MOD_DEADLINE)
    assert run.status == "waiting_approval", run.state.error
    run = await h.answer(run.id, MOD_CAPACITY)
    assert run.status == "waiting_approval", run.state.error
    state = run.state
    # The delta is cumulative: R8 (round 1) stays, R2 (round 2) is added to it.
    assert [r.id for r in state.delta.added] == ["R8"] and [r.id for r in state.delta.changed] == ["R2"]
    assert "R8" in {r.id for r in state.requirements.items}
    assert state.delta_touched == ["R2"]
    # Round-1 tests are kept as this run's tests; round 2 wrote tests for R2 only.
    assert state.new_scenario_ids == ["acc_cancel_too_late", "acc_cancel_in_time", "acc_capacity_n"]
    second_testgen = [c for c in h.llm.calls if c.task == "testgen"][1].messages[0]["content"]
    focus = second_testgen.split("<changed_requirements>")[1].split("</changed_requirements>")[0]
    assert '"R2"' in focus and '"R8"' not in focus
    assert state.test_report.failed == 0
    (diff,) = h.of_type(run.id, "diff")[-1:]
    assert [r["id"] for r in diff["requirements"]["added"]] == ["R8"]
    assert [r["id"] for r in diff["requirements"]["changed"]] == ["R2"]
    assert h.of_type(run.id, "approval_requested")[-1]["can_approve"] is True
    await h.orch.approve(run.id)
    live = h.repo.revisions[h.repo.bots[h.bot_id].active_revision_id]
    booking = live.spec.capability("book_workshop")
    assert booking.capacity.value == 12 and booking.cancellation.deadline_hours == 2
    assert "R8" in {r["id"] for r in live.requirements["items"]}
    assert {"acc_cancel_too_late", "acc_cancel_in_time"} <= {s["id"] for s in live.scenarios}


async def test_uncovered_requirement_blocks_approval_and_is_named() -> None:
    h = modify_harness(two_round_scripts([]))  # round 2 writes no test for the capacity change
    run = await h.start_change(MOD_DEADLINE)
    run = await h.answer(run.id, MOD_CAPACITY)
    assert run.status == "waiting_approval", run.state.error
    assert run.state.test_report.failed == 0
    approval = h.of_type(run.id, "approval_requested")[-1]
    assert approval["can_approve"] is False
    assert "R2" in approval["blocked_reason"] and "ثابت نشده" in approval["blocked_reason"]
    assert "R8" not in approval["blocked_reason"]  # covered by the kept round-1 tests
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.approve(run.id)
    assert "R2" in refused.value.message


async def test_a_changed_requirement_regenerates_its_earlier_tests() -> None:
    later = deadline_scenarios("R8")
    for s in later:
        s["id"] = s["id"] + "_v2"
    scripts = two_round_scripts(later)
    scripts["structured"]["understand"][1] = change_out(
        changed=[
            {**deadline_requirement("R8"), "statement": "لغو ثبت‌نام فقط تا ۳ ساعت قبل از شروع ممکن است."}
        ]
    )
    scripts["loops"]["build"][1] = [[patch({"op": "set", "path": DEADLINE_HOURS, "value": 2})], [finish()]]
    h = modify_harness(scripts)
    run = await h.start_change(MOD_DEADLINE)
    run = await h.answer(run.id, "مهلت را ۳ ساعت کن")
    assert run.state.delta_touched == ["R8"]
    assert run.state.new_scenario_ids == ["acc_cancel_too_late_v2", "acc_cancel_in_time_v2"]
    assert run.state.delta.added[0].statement.startswith("لغو ثبت‌نام فقط تا ۳")


def test_merge_delta_is_cumulative_with_stable_ids() -> None:
    base = Requirements.model_validate(golden_requirements())
    first = merge_delta(
        None, RequirementsDelta.model_validate(change_out(added=[deadline_requirement("R1")])["delta"]), base
    )
    assert [r.id for r in first.delta.added] == ["R8"] and first.touched == {"R8"}
    # The model re-lists R8 (same statement) and changes R2: R8 is untouched, R2 is touched.
    second = merge_delta(
        first.delta,
        RequirementsDelta.model_validate(
            change_out(added=[deadline_requirement("R8")], changed=[capacity_requirement(12)])["delta"]
        ),
        base,
    )
    assert [r.id for r in second.delta.added] == ["R8"] and second.touched == {"R2"}
    # Removing the earlier addition drops it; reverting R2 to its base statement drops the change.
    third = merge_delta(
        second.delta,
        RequirementsDelta.model_validate(
            change_out(removed=["R8"], changed=[golden_requirements()["items"][1]])["delta"]
        ),
        base,
    )
    assert third.delta.added == [] and third.delta.changed == [] and third.touched == {"R8", "R2"}
    # A new addition after a removal never reuses the removed id.
    fourth = merge_delta(
        third.delta,
        RequirementsDelta.model_validate(change_out(added=[capacity_requirement(9, "R1")])["delta"]),
        base,
    )
    assert [r.id for r in fourth.delta.added] == ["R8"]  # R8 is free again only because nothing kept it


# --------------------------------------------------------------------------- item 5


async def test_restating_every_requirement_with_punctuation_releases_nothing() -> None:
    """The verifier appended "!" to every statement to make all carried scenarios supersedable."""
    restated = [
        {**item, "statement": item["statement"].rstrip(".") + " !"} for item in golden_requirements()["items"]
    ]
    restated[1] = capacity_requirement(12)
    scripts = {
        "structured": {
            "triage": [triage_out()],
            "understand": [change_out(changed=restated)],
            "testgen": [{"scenarios": [capacity_scenario(12)]}],
        },
        "loops": {
            "build": [[[patch({"op": "set", "path": CAPACITY_VALUE, "value": 12})], [finish()]]],
            "repair": [
                [
                    [supersede("golden_capacity_waitlist")],
                    [supersede("golden_basic_book")],
                    [supersede("golden_capacity_10_real")],
                    [run_tests()],
                    [finish()],
                ]
            ],
        },
    }
    h = modify_harness(scripts)
    run = await h.start_change(MOD_CAPACITY)
    assert [r.id for r in run.state.delta.changed] == ["R2"]
    assert [r["ok"] for r in h.tool_results("supersede_scenario")] == [False, False, True]
    (diff,) = h.of_type(run.id, "diff")
    assert [c["id"] for c in diff["requirements"]["changed"]] == ["R2"]
    assert run.status == "waiting_approval" and run.state.test_report.failed == 0


def test_statement_normalization() -> None:
    assert normalize_statement("ظرفیت هر کارگاه ۱۰ نفر است.") == normalize_statement(
        "ظرفیت  هر‌کارگاه 10 نفر است!"
    )
    assert normalize_statement("ظرفیت ۱۰") != normalize_statement("ظرفیت ۱۲")


# --------------------------------------------------------------------------- item 2


async def test_create_with_zero_acceptance_scenarios_cannot_be_approved() -> None:
    bad = golden_acceptance(("golden_basic_book", "golden_capacity_waitlist"))
    for s in bad:
        s["requirement_ids"] = []
    h = harness(structured={"testgen": [{"scenarios": bad}, {"scenarios": copy.deepcopy(bad)}]})
    run = await h.start()
    assert run.status == "waiting_approval"
    (generated,) = h.of_type(run.id, "tests_generated")
    assert generated["acceptance"] == 0 and generated["derived"] > 0
    assert run.state.test_report.failed == 0  # derived scenarios all pass
    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval["can_approve"] is False and NO_ACCEPTANCE in approval["blocked_reason"]
    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)
    assert h.repo.bots[h.bot_id].active_revision_id is None


async def test_create_with_one_acceptance_scenario_can_be_approved_with_a_note() -> None:
    h = harness(structured={"testgen": [{"scenarios": golden_acceptance(("golden_basic_book",))}]})
    run = await h.start()
    (generated,) = h.of_type(run.id, "tests_generated")
    assert generated["acceptance"] == 1 and "at least 2 expected" in " ".join(generated["notes"])
    assert h.of_type(run.id, "approval_requested")[0]["can_approve"] is True
    assert (await h.orch.approve(run.id)).status == "done"


# --------------------------------------------------------------------------- item 3


async def test_build_tool_limit_blocks_approval_until_a_later_loop_finishes() -> None:
    validate = [ToolCall("validate_spec")]
    h = harness(
        limits=Limits(max_tool_calls=5),
        structured={
            "understand": [understand_out(), understand_out()],
            "testgen": [{"scenarios": golden_acceptance()}] * 2,
            "sample_data": [sample_out()] * 2,
        },
        loops={"build": [[[set_spec()], validate, validate, validate, validate, validate], [[finish()]]]},
    )
    run = await h.start()
    assert run.status == "waiting_approval", run.state.error
    assert run.state.step_limit_hit == "build" and run.state.test_report.failed == 0
    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval["can_approve"] is False and STEP_LIMIT_TEXT in approval["blocked_reason"]
    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)
    run = await h.answer(run.id, "ادامه بده")
    assert run.state.step_limit_hit is None
    assert h.of_type(run.id, "approval_requested")[-1]["can_approve"] is True
    assert (await h.orch.approve(run.id)).status == "done"


async def test_repair_tool_limit_blocks_approval() -> None:
    scripts = {
        "structured": {
            "triage": [triage_out()],
            "understand": [change_out(changed=[capacity_requirement(12)])],
            "testgen": [{"scenarios": [capacity_scenario(12)]}],
        },
        "loops": {
            "build": [[[patch({"op": "set", "path": CAPACITY_VALUE, "value": 12})], [finish()]]],
            "repair": [
                [
                    [supersede("golden_capacity_10_real")],
                    [run_tests()],
                    [ToolCall("validate_spec")],
                    [ToolCall("validate_spec")],
                    [ToolCall("validate_spec")],
                    [ToolCall("validate_spec")],
                ]
            ],
        },
    }
    h = modify_harness(scripts, limits=Limits(max_tool_calls=5))
    run = await h.start_change()
    assert run.status == "waiting_approval", run.state.error
    assert run.state.test_report.failed == 0 and run.state.step_limit_hit == "repair"
    approval = h.of_type(run.id, "approval_requested")[-1]
    assert approval["can_approve"] is False and STEP_LIMIT_TEXT in approval["blocked_reason"]
    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)


# --------------------------------------------------------------------------- item 4


def _statuses(h, run_id: str) -> list[tuple[str, str]]:
    return [(p["status"], p["phase"]) for p in h.of_type(run_id, "run_status")]


async def test_modify_run_status_sequence() -> None:
    from tests.unit.agent.helpers import capacity_scripts

    h = modify_harness(capacity_scripts(12))
    run = await h.start_change()
    await h.orch.approve(run.id)
    assert _statuses(h, run.id) == [
        ("running", "triage"),
        ("waiting_approval", "await_approval"),
        ("running", "deploy"),
        ("done", "deploy"),
    ]
    assert h.types(run.id)[-1] == "run_status"


@pytest.mark.parametrize("intent", ["question", "data_request", "unsupported"])
async def test_triage_outcomes_announce_done(intent: str) -> None:
    h = modify_harness({"structured": {"triage": [triage_out(intent, "")]}})
    run = await h.start_change("سؤال")
    assert _statuses(h, run.id) == [("running", "triage"), ("done", "triage")]
    types = h.types(run.id)
    assert types[-1] == "run_status" and "agent_message" in types
    assert "error" not in types


async def test_silent_waiting_user_pauses_announce_status_and_explain() -> None:
    # modify: empty delta (no questions event)
    h = modify_harness({"structured": {"triage": [triage_out()], "understand": [change_out()] * 3}})
    run = await h.start_change("بهترش کن")
    assert run.status == "waiting_user" and h.of_type(run.id, "questions") == []
    assert _statuses(h, run.id)[-1] == ("waiting_user", "clarify")
    assert h.of_type(run.id, "agent_message")
    run = await h.answer(run.id, "نمی‌دانم")
    run = await h.answer(run.id, "هیچ")  # end_without_change
    assert run.status == "done" and _statuses(h, run.id)[-1] == ("done", "understand")
    # create: no capability requirement
    no_caps = understand_out()
    no_caps["requirements"]["items"] = [
        r for r in no_caps["requirements"]["items"] if r["kind"] != "capability"
    ]
    c = harness(structured={"understand": [no_caps]})
    created = await c.start()
    assert created.status == "waiting_user" and c.of_type(created.id, "questions") == []
    assert _statuses(c, created.id) == [("running", "understand"), ("waiting_user", "clarify")]
    assert c.of_type(created.id, "agent_message")


async def test_activation_refused_returns_to_waiting_approval_without_an_error_event() -> None:
    from app.agent.repository import ActivationRefused

    h = harness()
    run = await h.start()

    async def refuse(revision_id: str) -> int:
        raise ActivationRefused("نسخه هنوز آماده نیست.", code="invalid_revision_state")

    h.repo.activate = refuse  # type: ignore[method-assign]
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.approve(run.id)
    assert refused.value.code == "invalid_revision_state"
    assert (await h.repo.load_run(run.id)).status == "waiting_approval"
    assert "error" not in h.types(run.id)
    assert "نسخه هنوز آماده نیست." in h.of_type(run.id, "agent_message")[-1]["text"]
    assert _statuses(h, run.id)[-2:] == [("running", "deploy"), ("waiting_approval", "await_approval")]


async def test_rejected_interrupted_and_reconciled_statuses() -> None:
    import asyncio

    h = harness()
    run = await h.start()
    await h.orch.reject(run.id)
    assert _statuses(h, run.id)[-1] == ("rejected", "await_approval")

    def cancel(messages: list) -> dict:
        raise asyncio.CancelledError

    c = harness(structured={"understand": [cancel]})
    record = await c.orch.start_create(c.bot_id, "x")
    with pytest.raises(asyncio.CancelledError):
        await c.orch.advance(record.id)
    assert _statuses(c, record.id)[-1] == ("interrupted", "understand")

    # A run marked interrupted outside the orchestrator (startup) gets its event once.
    d = harness()
    other = await d.orch.start_create(d.bot_id, "x")
    d.repo.runs[other.id].status = "interrupted"
    await d.orch.ensure_status_event(other.id)
    await d.orch.ensure_status_event(other.id)
    assert _statuses(d, other.id) == [("running", "understand"), ("interrupted", "understand")]


# --------------------------------------------------------------------------- item 6

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ"


async def test_a_pasted_telegram_token_never_reaches_events_state_or_the_model() -> None:
    from tests.unit.agent.helpers import GOLDEN_PROMPT

    h = harness(
        structured={
            "understand": [understand_out(), understand_out()],
            "testgen": [{"scenarios": golden_acceptance()}] * 2,
            "sample_data": [sample_out()] * 2,
        },
        loops={"build": [build_ok(), build_ok()]},
    )
    run = await h.start(f"{GOLDEN_PROMPT} توکن ربات: {TOKEN}")
    run = await h.answer(run.id, f"این هم توکن {TOKEN}")
    assert run.status == "waiting_approval", run.state.error
    dumped = run.state.model_dump_json() + str([e.payload for e in h.events(run.id)])
    assert TOKEN not in dumped and "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ" not in dumped
    assert TOKEN not in str([c.messages for c in h.llm.calls])
    assert "[REDACTED]" in h.events(run.id)[0].payload["text"]
    notices = [m["text"] for m in h.of_type(run.id, "agent_message") if "«تنظیمات»" in m["text"]]
    assert len(notices) == 2


async def test_a_token_in_a_change_request_is_redacted_before_triage() -> None:
    h = modify_harness({"structured": {"triage": [triage_out("question", "بله.")]}})
    run = await h.start_change(f"توکن جدید {TOKEN} را بگذار")
    assert TOKEN not in str(h.llm.calls[0].messages) and TOKEN not in run.state.model_dump_json()
    assert any("«تنظیمات»" in m["text"] for m in h.of_type(run.id, "agent_message"))


# --------------------------------------------------------------------------- item 7


async def test_tool_result_summaries_list_the_changes() -> None:
    from app.agent.tools import change_summary
    from app.botspec.models import BotSpec
    from tests.unit.agent.helpers import capacity_scripts, golden_spec

    h = modify_harness(capacity_scripts(12))
    run = await h.start_change()
    results = [
        e.payload
        for e in h.events(run.id)
        if e.type == "tool_result" and e.payload["name"] == "apply_spec_patch"
    ]
    assert results[0]["summary"] == "ظرفیت: ۱۰ ← ۱۲"
    c = harness()
    created = await c.start()
    first = next(p for p in c.of_type(created.id, "tool_result") if p["name"] == "set_spec")
    assert first["summary"].startswith("مشخصات کامل ربات نوشته شد")
    base = BotSpec.model_validate(golden_spec())
    many = golden_spec()
    booking = many["capabilities"][1]
    booking["capacity"]["value"] = 12
    booking["cancellation"]["deadline_hours"] = 2
    booking["max_active_per_user"] = 3
    booking["closes_hours_before_start"] = 1
    many["bot"]["name"] = "نام تازه"
    summary = change_summary(base, BotSpec.model_validate(many))
    assert summary.count("؛") == 3 and summary.endswith("و ۱ مورد دیگر")
    assert change_summary(base, base) == "تغییری در مشخصات ایجاد نشد"
