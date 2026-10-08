"""CREATE workflow end to end with FakeLLM and the in-memory repository."""

import copy

import pytest

from app.agent.checks import fa
from app.agent.context import Limits
from app.agent.llm import ToolCall, Usage
from app.agent.orchestrator import OrchestratorError
from app.agent.repository import ActiveRunExists
from tests.unit.agent.helpers import (
    GOLDEN_PROMPT,
    blocking_question,
    build_ok,
    finish,
    golden_acceptance,
    golden_spec,
    harness,
    patch,
    sample_out,
    set_spec,
    understand_out,
)

WAITLIST_PATH = ["capabilities", "book_workshop", "waitlist"]


def spec_without_waitlist() -> dict:
    spec = golden_spec()
    spec["capabilities"][1]["waitlist"] = {"enabled": False, "auto_promote": True}
    return spec


async def test_golden_create_run_reaches_an_activated_revision() -> None:
    h = harness()
    run = await h.start()
    assert run.status == "waiting_approval", run.state.error
    assert run.phase == "await_approval"
    state = run.state
    assert state.test_report is not None and state.test_report.failed == 0
    assert len(state.scenarios) == 6 and len(state.derived) > 0
    assert state.test_report.total == len(state.scenarios) + len(state.derived)
    assert [s.id for s in state.scenarios] == state.new_scenario_ids
    assert all(s.id.startswith("acc_") for s in state.scenarios)

    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval == {"revision_id": state.revision_id, "can_approve": True}
    revision = h.repo.revisions[state.revision_id]
    assert revision.status == "draft" and revision.parent_id is None
    assert revision.change_request == GOLDEN_PROMPT
    assert len(revision.sample_data) == 2  # the invalid sample record was dropped
    assert len(h.repo.sandbox[h.bot_id]) == 2

    done = await h.orch.approve(run.id)
    assert done.status == "done" and done.phase == "deploy"
    assert done.result_revision_id == state.revision_id
    assert h.repo.bots[h.bot_id].active_revision_id == state.revision_id
    assert h.repo.revisions[state.revision_id].status == "active"
    assert h.of_type(run.id, "deployed") == [{"revision_id": state.revision_id, "number": 1}]
    assert h.repo.save_count >= 6  # saved after every phase


async def test_event_sequence_and_payload_shapes_for_a_normal_run() -> None:
    h = harness()
    run = await h.start()
    await h.orch.approve(run.id)
    events = h.events(run.id)
    assert [e.id for e in events] == sorted(e.id for e in events)
    phases = [(e.type, e.payload["phase"]) for e in events if e.type in ("phase_started", "phase_finished")]
    assert phases == [
        (kind, phase)
        for phase in ("understand", "build", "testgen", "run", "review", "deploy")
        for kind in ("phase_started", "phase_finished")
    ]
    types = [e.type for e in events]
    assert types[0] == "owner_message"
    assert types.index("requirements") < types.index("tool_call") < types.index("tests_generated")
    assert types.index("tests_generated") < types.index("test_report") < types.index("approval_requested")
    assert types.index("approval_requested") < types.index("deployed")
    statuses = [(e.payload["status"], e.payload["phase"]) for e in events if e.type == "run_status"]
    assert statuses == [
        ("running", "understand"),
        ("waiting_approval", "await_approval"),
        ("running", "deploy"),
        ("done", "deploy"),
    ]
    assert types[-1] == "run_status"

    shapes = {
        "run_status": {"status", "phase"},
        "activity": {"phase", "label"},
        "owner_message": {"text"},
        "agent_message": {"text"},
        "phase_started": {"phase"},
        "phase_finished": {"phase", "ok"},
        "requirements": {"requirements"},
        "tool_call": {"loop", "name", "summary"},
        "tool_result": {"name", "ok", "summary"},
        "spec_updated": {"outline"},
        "tests_generated": {"derived", "acceptance"},
        "test_report": {"total", "passed", "failed", "failures"},
        "approval_requested": {"revision_id", "can_approve"},
        "deployed": {"revision_id", "number"},
        "usage": {"input_tokens", "output_tokens", "cached_tokens", "tool_calls"},
    }
    for e in events:
        assert set(e.payload) == shapes[e.type], (e.type, e.payload)
        assert e.run_id == run.id
    calls = [e.payload for e in events if e.type == "tool_call"]
    assert [c["name"] for c in calls] == ["set_spec", "finish"]
    assert all(c["loop"] == "build" for c in calls)
    assert [r["ok"] for r in h.of_type(run.id, "tool_result")] == [True, True]
    (outline_event,) = h.of_type(run.id, "spec_updated")
    assert {c["key"] for c in outline_event["outline"]["capabilities"]} == {"info", "book_workshop"}
    assert "capacity" not in str(outline_event["outline"])  # outlines omit rule values
    (report,) = h.of_type(run.id, "test_report")
    assert report["failed"] == 0 and report["failures"] == [] and report["passed"] == report["total"]
    (req,) = h.of_type(run.id, "requirements")
    assert [i["id"] for i in req["requirements"]["items"]] == [f"R{n}" for n in range(1, 8)]
    usage = h.of_type(run.id, "usage")[-1]
    assert usage["tool_calls"] == 2 and usage["input_tokens"] > 0
    texts = [m["text"] for m in h.of_type(run.id, "agent_message")]
    assert any(fa(report["total"]) in t for t in texts)  # review summary with Persian digits


async def test_acceptance_author_sees_requirements_and_outline_only() -> None:
    h = harness()
    await h.start()
    (testgen_call,) = [c for c in h.llm.calls if c.task == "testgen"]
    prompt = testgen_call.messages[0]["content"]
    assert "<bot_outline>" in prompt and "<requirements>" in prompt
    assert '"capacity"' not in prompt and '"waitlist"' not in prompt  # no rule values
    systems = {c.system for c in h.llm.calls}
    assert len(systems) == 1  # one identical system prompt -> one cache prefix
    (sample_call,) = [c for c in h.llm.calls if c.task == "sample_data"]
    assert sample_call.tier == "fast"


async def test_clarification_round_then_build() -> None:
    questions = [blocking_question(f"Q{i}", f"سؤال {i}؟") for i in range(1, 6)]
    h = harness(structured={"understand": [understand_out(questions=questions), understand_out()]})
    run = await h.start()
    assert run.status == "waiting_user" and run.phase == "clarify"
    (asked,) = h.of_type(run.id, "questions")
    assert [q["id"] for q in asked["questions"]] == ["Q1", "Q2", "Q3"]  # at most three per round
    assert run.state.clarify_rounds == 1

    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)
    run = await h.answer(run.id, "بله، شماره تماس هم بگیرید.")
    assert run.status == "waiting_approval"
    second = [c for c in h.llm.calls if c.task == "understand"][1]
    assert "بله، شماره تماس هم بگیرید." in second.messages[0]["content"]
    assert "<previous_requirements>" in second.messages[0]["content"]


async def test_two_clarification_rounds_then_questions_become_assumptions() -> None:
    q = [blocking_question("Q1", "سؤال اول؟")]
    h = harness(structured={"understand": [understand_out(questions=q)] * 3})
    run = await h.start()
    assert run.status == "waiting_user"
    run = await h.answer(run.id, "پاسخ اول")
    assert run.status == "waiting_user" and run.state.clarify_rounds == 2
    run = await h.answer(run.id, "پاسخ دوم")
    assert run.status == "waiting_approval", run.state.error
    third = [c for c in h.llm.calls if c.task == "understand"][2]
    assert "No more questions are allowed" in third.messages[0]["content"]
    req = run.state.requirements
    assert req is not None and req.open_questions == []
    assumed = [r for r in req.items if r.status == "assumed" and "سؤال اول" in r.statement]
    assert len(assumed) == 1 and assumed[0].id == "R8"
    assert len(h.of_type(run.id, "questions")) == 2


async def test_important_questions_are_never_asked() -> None:
    important = {**blocking_question(), "severity": "important"}
    h = harness(structured={"understand": [understand_out(questions=[important])]})
    run = await h.start()
    assert run.status == "waiting_approval"
    assert h.of_type(run.id, "questions") == []
    assert any(
        r.status == "assumed" and r.statement.endswith("فرض: بله") for r in run.state.requirements.items
    )


async def test_build_loop_corrects_an_invalid_spec() -> None:
    bad = golden_spec()
    bad["menu"][0]["capability"] = "missing_cap"  # semantic error: unknown capability
    fix = patch({"op": "set", "path": ["menu", "workshops", "capability"], "value": "book_workshop"})
    h = harness(loops={"build": [[[set_spec(bad)], [finish()], [fix], [finish()]]]})
    run = await h.start()
    assert run.status == "waiting_approval", run.state.error
    first, refused_finish, patched, finished = h.llm.tool_results
    assert first.content["ok"] is False and first.content["stored"] is True
    assert any(i["code"] == "unknown_capability" for i in first.content["issues"])
    assert refused_finish.content["ok"] is False  # finish refused while errors remain
    assert patched.content["ok"] is True and patched.content["changed_paths"] == ["menu/workshops/capability"]
    assert finished.content == {"ok": True}
    assert [r["ok"] for r in h.of_type(run.id, "tool_result")] == [False, False, True, True]
    assert len(h.of_type(run.id, "spec_updated")) == 2


async def test_schema_invalid_spec_is_not_stored() -> None:
    bad = golden_spec()
    bad["capabilities"][1]["capacity"] = {"mode": "fixed", "value": None, "field": None}
    h = harness(loops={"build": [[[set_spec(bad)], [set_spec()], [finish()]]]})
    run = await h.start()
    assert run.status == "waiting_approval"
    first = h.llm.tool_results[0].content
    assert first["stored"] is False and first["issues"][0]["code"] == "capacity_mode_mismatch"
    assert first["issues"][0]["path"] == "capabilities/book_workshop/capacity"


async def test_wrong_spec_is_caught_by_acceptance_and_repaired() -> None:
    enable = patch({"op": "set", "path": WAITLIST_PATH, "value": {"enabled": True, "auto_promote": True}})
    repair_turns = [
        [ToolCall("get_failure", {"scenario_id": "acc_golden_capacity_waitlist"})],
        [enable],
        [ToolCall("run_tests")],
        [finish("enabled the waitlist")],
    ]
    h = harness(
        loops={"build": [[[set_spec(spec_without_waitlist())], [finish()]]], "repair": [repair_turns]}
    )
    run = await h.start()
    assert run.status == "waiting_approval", run.state.error
    reports = h.of_type(run.id, "test_report")
    assert len(reports) == 2
    failing_ids = {f["id"] for f in reports[0]["failures"]}
    assert "acc_golden_capacity_waitlist" in failing_ids
    assert all(f["title"] and f["message"] for f in reports[0]["failures"])
    assert reports[1]["failed"] == 0
    assert run.state.repair_rounds == 1
    failure = h.tool_results("get_failure")[0]
    assert failure["fixable"] is True and failure["failed_step"] is not None and failure["transcript_tail"]
    run_tests = h.tool_results("run_tests")[0]
    assert run_tests["failed"] == []
    assert {c["loop"] for c in h.of_type(run.id, "tool_call") if c["name"] == "run_tests"} == {"repair"}
    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval["can_approve"] is True
    assert run.state.draft_spec.capability("book_workshop").waitlist.enabled is True


async def test_repair_exhaustion_blocks_approval() -> None:
    h = harness(
        loops={
            "build": [[[set_spec(spec_without_waitlist())], [finish()]]],
            "repair": [[[finish("cannot")]], [[finish("still cannot")]]],
        }
    )
    run = await h.start()
    assert run.status == "waiting_approval"
    assert run.state.repair_rounds == 2
    assert len(h.of_type(run.id, "test_report")) == 3
    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval["can_approve"] is False and "۲ دور اصلاح" in approval["blocked_reason"]
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.approve(run.id)
    assert refused.value.code == "approval_blocked"
    revision = h.repo.revisions[run.state.revision_id]
    assert revision.status == "draft" and revision.test_report["failed"] > 0
    assert h.repo.bots[h.bot_id].active_revision_id is None
    rejected = await h.orch.reject(run.id)
    assert rejected.status == "rejected" and revision.status == "rejected"


async def test_fix_scenario_refuses_derived_and_fixes_this_runs_acceptance() -> None:
    wrong = golden_acceptance(("golden_capacity_waitlist",))[0]
    wrong["steps"][2]["expect"] = "confirmed"  # misstates R3: the third booking should be waitlisted
    acceptance = [*golden_acceptance(("golden_basic_book",)), wrong]
    corrected = golden_acceptance(("golden_capacity_waitlist",))[0]

    repair_turns = [
        [
            ToolCall(
                "fix_scenario",
                {"scenario_id": "derived:book_workshop:basic", "scenario": corrected, "reason": "x"},
            )
        ],
        [
            ToolCall(
                "fix_scenario",
                {
                    "scenario_id": "acc_golden_capacity_waitlist",
                    "scenario": corrected,
                    "reason": "نفر سوم باید به لیست انتظار برود.",
                },
            )
        ],
        [finish()],
    ]
    h = harness(structured={"testgen": [{"scenarios": acceptance}]}, loops={"repair": [repair_turns]})
    run = await h.start()
    assert run.status == "waiting_approval", run.state.error
    derived_attempt, fixed = h.tool_results("fix_scenario")
    assert derived_attempt["ok"] is False and derived_attempt["refused"] is True
    assert fixed == {"ok": True}
    assert [f.scenario_id for f in run.state.scenario_fixes] == ["acc_golden_capacity_waitlist"]
    assert any("نفر سوم" in m["text"] for m in h.of_type(run.id, "agent_message"))
    assert run.state.test_report.failed == 0


async def test_fix_scenario_refuses_scenarios_not_written_in_this_run() -> None:
    h = harness()
    run = await h.start()
    from app.agent.tools import REPAIR_TOOLS, AgentTools

    state = run.state
    carried = state.scenarios[0]
    state.new_scenario_ids = [s.id for s in state.scenarios[1:]]  # as if carried forward

    async def emit(_: object) -> None:
        return None

    tools = AgentTools(state, loop="repair", emit=emit, names=REPAIR_TOOLS)
    outcome = await tools.handle(
        "fix_scenario",
        {"scenario_id": carried.id, "scenario": carried.model_dump(mode="json"), "reason": "تست"},
    )
    assert outcome.content["refused"] is True and "carried forward" in outcome.content["error"]


async def test_acceptance_scenarios_without_requirement_ids_are_rejected() -> None:
    good = golden_acceptance(("golden_basic_book", "golden_capacity_waitlist"))
    no_ids = golden_acceptance(("golden_duplicate_rejected",))[0]
    no_ids["requirement_ids"] = []
    unknown_ids = golden_acceptance(("golden_cancel_frees_seat",))[0]
    unknown_ids["requirement_ids"] = ["R99"]
    uses_contains = golden_acceptance(("golden_promotion_notifies",))[0]
    uses_contains["steps"][4] = {"do": "expect_notified", "actor": "reza", "contains": "تبریک"}
    retry_fixed = golden_acceptance(("golden_duplicate_rejected",))[0]
    still_bad = copy.deepcopy(unknown_ids)
    testgen = [
        {"scenarios": [*good, no_ids, unknown_ids, uses_contains]},
        {"scenarios": [retry_fixed, still_bad]},
    ]
    h = harness(structured={"testgen": testgen})
    run = await h.start()
    assert run.status == "waiting_approval"
    (generated,) = h.of_type(run.id, "tests_generated")
    assert generated["acceptance"] == 3
    notes = " ".join(generated["notes"])
    assert "golden_cancel_frees_seat" in notes and "golden_promotion_notifies" in notes
    assert "2 invalid acceptance scenario(s) dropped" in notes
    retry_call = [c for c in h.llm.calls if c.task == "testgen"][1]
    feedback = retry_call.messages[-1]["content"]
    assert "requirement_ids must contain at least one existing requirement id" in feedback
    assert "never 'contains'" in feedback
    assert all(s.requirement_ids for s in run.state.scenarios)


async def test_unsupported_request_is_recorded_and_reported() -> None:
    unsupported = [
        {
            "statement": "پرداخت آنلاین هزینهٔ کارگاه",
            "reason": "پرداخت آنلاین در این نسخه پشتیبانی نمی‌شود",
            "alternative": "نمایش قیمت و تأیید ثبت‌نام توسط شما",
        }
    ]
    h = harness(structured={"understand": [understand_out(unsupported=unsupported)]})
    run = await h.start(GOLDEN_PROMPT + " مشتری‌ها هزینه را آنلاین پرداخت کنند.")
    assert run.status == "waiting_approval"
    (req,) = h.of_type(run.id, "requirements")
    assert req["requirements"]["unsupported"][0]["statement"] == "پرداخت آنلاین هزینهٔ کارگاه"
    first_message = h.of_type(run.id, "agent_message")[0]["text"]
    assert "نمی‌توانم بسازم" in first_message and "پیشنهاد: نمایش قیمت" in first_message
    assert run.state.requirements.unsupported[0].alternative


async def test_tool_call_limit_fails_the_build() -> None:
    bad = golden_spec()
    bad["menu"][0]["capability"] = "missing_cap"
    turns = [[set_spec(bad)]] + [[ToolCall("validate_spec")] for _ in range(20)]
    h = harness(limits=Limits(max_tool_calls=15), loops={"build": [turns]})
    run = await h.start()
    assert run.status == "failed" and run.phase == "failed"
    assert len(h.llm.tool_results) == 15  # the 16th call was never executed
    (error,) = h.of_type(run.id, "error")
    assert "سقف" in error["message"]
    assert run.state.usage.tool_calls == 15


async def test_parallel_calls_beyond_the_limit_are_not_executed() -> None:
    h = harness(
        limits=Limits(max_tool_calls=2),
        loops={"build": [[[set_spec(), ToolCall("validate_spec"), finish()]]]},
    )
    run = await h.start()
    assert [r.name for r in h.llm.tool_results] == ["set_spec", "validate_spec"]
    assert run.status == "waiting_approval"  # stopped at the limit with a valid draft: proceeds


async def test_token_budget_blocks_approval_when_a_valid_draft_exists() -> None:
    usage = Usage(input_tokens=1000, output_tokens=10, llm_calls=1)
    h = harness(limits=Limits(input_budget=2500), usage_per_call=usage)
    run = await h.start()
    # understand (1000) + build turn 1 (2000) + build turn 2 (3000 > budget): loop stops after set_spec.
    assert run.status == "waiting_approval"
    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval["can_approve"] is False and "بودجه" in approval["blocked_reason"]
    assert [c.task for c in h.llm.calls] == ["understand", "build"]  # no testgen or sample data calls
    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)


async def test_token_budget_without_a_valid_draft_fails() -> None:
    usage = Usage(input_tokens=10, output_tokens=1000, llm_calls=1)
    bad = golden_spec()
    bad["menu"][0]["capability"] = "missing_cap"
    h = harness(
        limits=Limits(output_budget=1500),
        usage_per_call=usage,
        loops={"build": [[[set_spec(bad)], [finish()]]]},
    )
    run = await h.start()
    assert run.status == "failed"
    assert "بودجه" in h.of_type(run.id, "error")[0]["message"]


async def test_exception_inside_a_phase_marks_the_run_failed() -> None:
    h = harness(structured={"understand": [RuntimeError("boom")]})
    run = await h.start()
    assert run.status == "failed" and run.phase == "failed"
    assert "RuntimeError: boom" in run.state.error
    (error,) = h.of_type(run.id, "error")
    assert error["message"].startswith("خطای غیرمنتظره")
    assert h.types(run.id)[-2:] == ["error", "run_status"]
    assert h.of_type(run.id, "run_status")[-1] == {"status": "failed", "phase": "failed"}


async def test_exception_in_a_tool_handler_is_reported_to_the_model_not_raised() -> None:
    h = harness(loops={"build": [[[ToolCall("get_spec", {"path": 5})], [set_spec()], [finish()]]]})
    run = await h.start()
    assert run.status == "waiting_approval"
    assert h.llm.tool_results[0].content["ok"] is False


async def test_owner_message_while_awaiting_approval_restarts_from_the_draft() -> None:
    to_twelve = patch(
        {"op": "set", "path": ["capabilities", "book_workshop", "capacity", "value"], "value": 12}
    )
    h = harness(
        structured={
            "understand": [understand_out(), understand_out()],
            "testgen": [{"scenarios": golden_acceptance()}] * 2,
            "sample_data": [sample_out()] * 2,
        },
        loops={"build": [build_ok(), [[to_twelve], [finish()]]]},
    )
    run = await h.start()
    first_revision = run.state.revision_id
    run = await h.answer(run.id, "ظرفیت را ۱۲ نفر کن.")
    assert run.status == "waiting_approval", run.state.error
    second_build = [c for c in h.llm.calls if c.task == "build"][1]
    assert "<current_draft_spec>" in second_build.messages[0]["content"]
    second_understand = [c for c in h.llm.calls if c.task == "understand"][1]
    assert "<current_draft_spec>" in second_understand.messages[0]["content"]
    assert run.state.revision_id != first_revision
    assert h.repo.revisions[first_revision].status == "rejected"
    assert h.repo.revisions[run.state.revision_id].number == 2
    assert run.state.draft_spec.capability("book_workshop").capacity.value == 12
    done = await h.orch.approve(run.id)
    assert done.status == "done"


async def test_one_active_run_per_bot_and_no_create_on_an_active_bot() -> None:
    h = harness()
    run = await h.start()
    with pytest.raises(ActiveRunExists):
        await h.orch.start_create(h.bot_id, "دوباره")
    await h.orch.approve(run.id)
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.start_create(h.bot_id, "تغییر")
    assert refused.value.code == "modify_not_available"


async def test_messages_and_approval_require_the_right_status() -> None:
    h = harness()
    run = await h.start()
    assert run.status == "waiting_approval"
    await h.orch.approve(run.id)
    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)
    with pytest.raises(OrchestratorError):
        await h.orch.post_message(run.id, "بعد از پایان")
