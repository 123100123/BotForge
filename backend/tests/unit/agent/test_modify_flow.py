"""MODIFY workflow end to end with FakeLLM and the in-memory repository (roadmap: "Modification
Workflow"). The base is the golden workshop revision: examples/workshop.botspec.json, its
requirements, and all nine golden scenarios as acceptance scenarios."""

import copy

import pytest

from app.agent.llm import ToolCall
from app.agent.modify import apply_delta, normalize_delta, risk_level
from app.agent.orchestrator import OrchestratorError
from app.agent.repository import ActiveRunExists, LiveStats
from app.agent.requirements import Requirements, RequirementsDelta
from app.botspec.diff import diff_specs
from app.botspec.models import BotSpec
from app.botspec.validate import SpecIssue
from tests.unit.agent.helpers import (
    CAPACITY_VALUE,
    DEADLINE_HOURS,
    MOD_CAPACITY,
    MOD_DEADLINE,
    all_golden_scenarios,
    blocking_question,
    capacity_requirement,
    capacity_scripts,
    change_out,
    deadline_requirement,
    deadline_scenarios,
    deadline_scripts,
    finish,
    golden_requirements,
    golden_spec,
    modify_harness,
    patch,
    run_tests,
    sample_out,
    supersede,
    triage_out,
)

GOLDEN_IDS = [s["id"] for s in all_golden_scenarios()]
CARRIED_AFTER_CAPACITY = [i for i in GOLDEN_IDS if i != "golden_capacity_10_real"]


def _failing(run) -> list[str]:
    return [r.scenario_id for r in run.state.test_report.results if not r.passed]


# --------------------------------------------------------------------------- golden modifications


async def test_golden_capacity_change_supersedes_only_the_capacity_scenario() -> None:
    h = modify_harness(capacity_scripts(12))
    run = await h.start_change(MOD_CAPACITY)
    assert run.status == "waiting_approval", run.state.error
    state = run.state
    assert run.kind == "modify" and run.base_revision_id == h.base_id

    # The patch made the 10-seat scenario fail; the scripted agent superseded it (R2 is in the delta).
    first_report = h.of_type(run.id, "test_report")[0]
    assert [f["id"] for f in first_report["failures"]] == ["golden_capacity_10_real"]
    (result,) = h.tool_results("supersede_scenario")
    assert result["ok"] is True
    assert [s.scenario.id for s in state.superseded] == ["golden_capacity_10_real"]
    assert state.superseded[0].reason

    # Final run: all green; the other eight carried scenarios ran untouched; one new scenario.
    assert state.test_report.failed == 0
    by_id = {s.id: s for s in state.scenarios}
    assert state.carried_ids == CARRIED_AFTER_CAPACITY
    golden = {s["id"]: s for s in all_golden_scenarios()}
    for sid in CARRIED_AFTER_CAPACITY:
        assert by_id[sid].model_dump(mode="json", exclude_none=True) == {
            k: v for k, v in _canonical(golden[sid]).items()
        }
    assert state.new_scenario_ids == ["acc_capacity_n"]
    passed = {r.scenario_id for r in state.test_report.results if r.passed}
    assert set(CARRIED_AFTER_CAPACITY) | {"acc_capacity_n"} <= passed
    assert "golden_capacity_10_real" not in {r.scenario_id for r in state.test_report.results}

    # Diff: exactly the capacity change, risk low.
    (diff,) = h.of_type(run.id, "diff")
    assert diff == {
        "changes": [{"label_fa": "ظرفیت: ۱۰ ← ۱۲", "kind": "changed"}],
        "affected_capabilities": ["book_workshop"],
        "tests": {
            "carried": 8,
            "new": 1,
            "superseded": [
                {"title": golden["golden_capacity_10_real"]["title"], "reason": state.superseded[0].reason}
            ],
        },
        "risk": "low",
        "warnings": [],
        "requirements": {
            "added": [],
            "changed": [
                {
                    "id": "R2",
                    "before": golden_requirements()["items"][1]["statement"],
                    "after": capacity_requirement(12)["statement"],
                }
            ],
            "removed": [],
        },
    }
    # Nothing else changed in the spec.
    base = BotSpec.model_validate(golden_spec())
    expected = copy.deepcopy(golden_spec())
    expected["capabilities"][1]["capacity"]["value"] = 12
    assert state.draft_spec.model_dump(mode="json") == BotSpec.model_validate(expected).model_dump(
        mode="json"
    )
    assert [c.path for c in diff_specs(base, state.draft_spec)] == [CAPACITY_VALUE]

    # The live bot is untouched until approval.
    assert h.repo.bots[h.bot_id].active_revision_id == h.base_id
    assert h.repo.revisions[h.base_id].spec.capability("book_workshop").capacity.value == 10

    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval == {"revision_id": state.revision_id, "can_approve": True}
    draft = h.repo.revisions[state.revision_id]
    assert draft.parent_id == h.base_id and draft.status == "draft"
    assert draft.patch == [{"op": "set", "path": CAPACITY_VALUE, "value": 12, "before": None}]
    assert draft.change_request == f"Owner: {MOD_CAPACITY}"
    assert [s["scenario"]["id"] for s in draft.superseded] == ["golden_capacity_10_real"]
    assert {s["id"] for s in draft.scenarios} >= set(CARRIED_AFTER_CAPACITY) | {"acc_capacity_n"}
    assert "golden_capacity_10_real" not in {s["id"] for s in draft.scenarios}
    assert len(draft.sample_data) == 2  # carried from the base; no resource was added
    assert "sample_data" not in {c.task for c in h.llm.calls}

    done = await h.orch.approve(run.id)
    assert done.status == "done" and done.result_revision_id == state.revision_id
    assert h.repo.bots[h.bot_id].active_revision_id == state.revision_id
    assert h.repo.revisions[h.base_id].status == "superseded"
    assert h.of_type(run.id, "deployed") == [{"revision_id": state.revision_id, "number": 2}]


def _canonical(raw: dict) -> dict:
    from app.testing.scenario import Scenario

    return Scenario.model_validate(raw).model_dump(mode="json", exclude_none=True)


async def test_golden_deadline_change_adds_a_requirement_and_supersedes_nothing() -> None:
    h = modify_harness(deadline_scripts())
    run = await h.start_change(MOD_DEADLINE)
    assert run.status == "waiting_approval", run.state.error
    state = run.state
    assert state.superseded == [] and state.repair_rounds == 0
    assert state.test_report.failed == 0
    assert state.carried_ids == GOLDEN_IDS
    assert state.new_scenario_ids == ["acc_cancel_too_late", "acc_cancel_in_time"]
    late = next(s for s in state.scenarios if s.id == "acc_cancel_too_late")
    assert any(step.do == "advance_time" for step in late.steps)

    # Requirement ids continue the base numbering; the saved requirements reflect the delta.
    assert [r.id for r in state.delta.added] == ["R8"]
    saved = h.repo.revisions[state.revision_id].requirements
    assert [r["id"] for r in saved["items"]] == [f"R{i}" for i in range(1, 9)]
    assert saved["items"][-1]["statement"] == deadline_requirement()["statement"]
    assert saved["items"][:7] == golden_requirements()["items"]

    (diff,) = h.of_type(run.id, "diff")
    assert diff["changes"] == [
        {"label_fa": "مهلت لغو ثبت‌نام: بدون محدودیت ← تا ۲ ساعت قبل از شروع", "kind": "changed"}
    ]
    assert diff["tests"] == {"carried": 9, "new": 2, "superseded": []}
    assert diff["risk"] == "low" and diff["affected_capabilities"] == ["book_workshop"]
    assert [c.path for c in diff_specs(BotSpec.model_validate(golden_spec()), state.draft_spec)] == [
        DEADLINE_HOURS
    ]
    done = await h.orch.approve(run.id)
    assert done.status == "done"
    assert h.repo.bots[h.bot_id].active_revision_id == state.revision_id


async def test_two_golden_modifications_in_sequence_build_on_each_other() -> None:
    h = modify_harness(capacity_scripts(12))
    first = await h.start_change(MOD_CAPACITY)
    await h.orch.approve(first.id)
    scripts = deadline_scripts()
    h.llm.structured_scripts.update({k: list(v) for k, v in scripts["structured"].items()})
    h.llm.loop_scripts.update({k: list(v) for k, v in scripts["loops"].items()})
    second = await h.start_change(MOD_DEADLINE)
    assert second.status == "waiting_approval", second.state.error
    assert second.base_revision_id == first.state.revision_id
    # Carried from revision 2: its acceptance scenarios (8 golden + the 12-seat one), none superseded.
    assert second.state.carried_ids == [*CARRIED_AFTER_CAPACITY, "acc_capacity_n"]
    assert second.state.test_report.failed == 0
    spec = second.state.draft_spec.capability("book_workshop")
    assert spec.capacity.value == 12 and spec.cancellation.deadline_hours == 2
    await h.orch.approve(second.id)
    numbers = sorted(r.number for r in h.repo.revisions.values())
    assert numbers == [1, 2, 3]
    assert h.repo.revisions[second.state.revision_id].status == "active"


# --------------------------------------------------------------------------- guards


async def test_superseding_an_unrelated_derived_or_new_scenario_is_refused() -> None:
    scripts = capacity_scripts(12)
    scripts["loops"]["repair"] = [
        [
            [supersede("golden_capacity_waitlist")],  # R3: not in the delta
            [supersede("acc_capacity_n")],  # written in this run
            [supersede("book_workshop_basic")],  # derived (or unknown): never supersedable
            [supersede("golden_capacity_10_real")],
            [run_tests()],
            [finish()],
        ]
    ]
    h = modify_harness(scripts)
    run = await h.start_change()
    assert run.status == "waiting_approval", run.state.error
    unrelated, new, derived, allowed = h.tool_results("supersede_scenario")
    assert unrelated["ok"] is False and unrelated["refused"] is True
    assert "R3" in unrelated["error"] and "regression" in unrelated["error"]
    assert new["ok"] is False and "fix_scenario" in new["error"]
    assert derived["ok"] is False
    assert allowed["ok"] is True
    assert [s.scenario.id for s in run.state.superseded] == ["golden_capacity_10_real"]
    assert "golden_capacity_waitlist" in run.state.carried_ids


async def test_superseding_a_derived_scenario_is_refused() -> None:
    scripts = capacity_scripts(12)
    h = modify_harness(scripts)
    run = await h.start_change()
    derived_id = run.state.derived[0].id
    h2 = modify_harness(capacity_scripts(12))
    h2.llm.loop_scripts["repair"] = [
        [[supersede(derived_id)], [supersede("golden_capacity_10_real")], [run_tests()], [finish()]]
    ]
    run2 = await h2.start_change()
    refused, ok = h2.tool_results("supersede_scenario")
    assert refused["refused"] is True and "derived" in refused["error"]
    assert ok["ok"] is True and run2.status == "waiting_approval"


async def test_fix_scenario_on_a_carried_scenario_is_refused() -> None:
    scripts = capacity_scripts(12)
    fixed = copy.deepcopy(next(s for s in all_golden_scenarios() if s["id"] == "golden_capacity_10_real"))
    scripts["loops"]["repair"] = [
        [
            [
                ToolCall(
                    "fix_scenario",
                    {"scenario_id": "golden_capacity_10_real", "scenario": fixed, "reason": "x"},
                )
            ],
            [supersede("golden_capacity_10_real")],
            [run_tests()],
            [finish()],
        ]
    ]
    h = modify_harness(scripts)
    run = await h.start_change()
    (refused,) = h.tool_results("fix_scenario")
    assert refused["ok"] is False and refused["refused"] is True and "carried" in refused["error"]
    assert run.state.scenario_fixes == []
    assert run.status == "waiting_approval"


async def test_a_failing_carried_scenario_blocks_approval() -> None:
    scripts = capacity_scripts(12)
    scripts["loops"]["repair"] = [[[finish()]], [[finish()]]]  # never supersedes
    h = modify_harness(scripts)
    run = await h.start_change()
    assert run.status == "waiting_approval"
    assert _failing(run) == ["golden_capacity_10_real"]
    (approval,) = h.of_type(run.id, "approval_requested")
    assert approval["can_approve"] is False and approval["blocked_reason"]
    assert set(approval) == {"revision_id", "can_approve", "blocked_reason"}
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.approve(run.id)
    assert refused.value.code == "approval_blocked"
    assert h.repo.bots[h.bot_id].active_revision_id == h.base_id
    assert (await h.repo.load_run(run.id)).status == "waiting_approval"


async def test_a_regression_in_an_unrelated_carried_scenario_cannot_be_superseded() -> None:
    """The agent breaks the waitlist while changing capacity: the guard keeps the test, approval blocked."""
    scripts = capacity_scripts(12)
    scripts["loops"]["build"] = [
        [
            [
                patch(
                    {"op": "set", "path": CAPACITY_VALUE, "value": 12},
                    {
                        "op": "set",
                        "path": ["capabilities", "book_workshop", "waitlist", "enabled"],
                        "value": False,
                    },
                )
            ],
            [finish()],
        ]
    ]
    scripts["loops"]["repair"] = [
        [[supersede("golden_capacity_waitlist")], [supersede("golden_capacity_10_real")], [finish()]],
        [[supersede("golden_promotion_order")], [finish()]],
    ]
    h = modify_harness(scripts)
    run = await h.start_change()
    results = h.tool_results("supersede_scenario")
    assert [r["ok"] for r in results] == [False, True, False]
    assert "golden_capacity_waitlist" in _failing(run)
    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)


async def test_compat_error_blocks_the_build_and_is_fed_back() -> None:
    price_type = ["resources", "workshop", "fields", "price", "type"]
    scripts = capacity_scripts(12)
    scripts["loops"]["build"] = [
        [
            [
                patch(
                    {"op": "set", "path": price_type, "value": "text"},
                    {"op": "set", "path": CAPACITY_VALUE, "value": 12},
                )
            ],
            [finish()],  # refused: incompatible with the 3 live workshops
            [patch({"op": "set", "path": price_type, "value": "integer"})],
            [finish()],
        ]
    ]
    h = modify_harness(scripts, live=LiveStats(record_counts={"workshop": 3}))
    run = await h.start_change()
    first_patch, _ = h.tool_results("apply_spec_patch")
    assert first_patch["compat_errors"][0]["code"] == "field_type_changed"
    refused, accepted = [r.content for r in h.llm.tool_results if r.name == "finish" and r.task == "build"]
    assert refused["ok"] is False and refused["compat_errors"][0]["code"] == "field_type_changed"
    assert accepted["ok"] is True
    assert run.status == "waiting_approval", run.state.error
    build = next(c for c in h.llm.calls if c.task == "build")
    assert '"workshop":3' in build.messages[0]["content"]  # counts only, never records


async def test_unfixed_compat_error_fails_the_run_after_feedback_rounds() -> None:
    price_type = ["resources", "workshop", "fields", "price", "type"]
    scripts = capacity_scripts(12)
    scripts["loops"]["build"] = [
        [[patch({"op": "set", "path": price_type, "value": "text"})], [finish()]],
        [[finish()]],
        [[finish()]],
    ]
    h = modify_harness(scripts, live=LiveStats(record_counts={"workshop": 3}))
    run = await h.start_change()
    assert run.status == "failed" and run.phase == "failed"
    builds = [c for c in h.llm.calls if c.task == "build"]
    assert len(builds) == 3
    assert "<compat_errors>" not in builds[0].messages[0]["content"]
    assert "<compat_errors>" in builds[1].messages[0]["content"]
    assert "field_type_changed" in builds[1].messages[0]["content"]
    assert h.of_type(run.id, "error")[-1]["message"].startswith("این تغییر با داده‌های فعلی ربات سازگار نیست")
    assert [r.id for r in h.repo.revisions.values()] == [h.base_id]  # no draft written
    assert h.repo.bots[h.bot_id].active_revision_id == h.base_id


async def test_compat_warning_makes_the_risk_high() -> None:
    scripts = capacity_scripts(8)
    scripts["loops"]["repair"] = [
        [[supersede("golden_capacity_10_real", "ظرفیت از ۱۰ به ۸ تغییر کرد.")], [run_tests()], [finish()]]
    ]
    live = LiveStats(
        record_counts={"workshop": 2, "book_workshop": 15}, max_confirmed_per_item={"book_workshop": 9}
    )
    h = modify_harness(scripts, live=live)
    run = await h.start_change("ظرفیت را ۸ نفر کن.")
    assert run.status == "waiting_approval", run.state.error
    (diff,) = h.of_type(run.id, "diff")
    assert diff["risk"] == "high"
    assert diff["changes"] == [{"label_fa": "ظرفیت: ۱۰ ← ۸", "kind": "changed"}]
    assert len(diff["warnings"]) == 1 and "ظرفیت کمتر می‌شود" in diff["warnings"][0]
    assert h.of_type(run.id, "approval_requested")[0]["can_approve"] is True  # warnings do not block


async def test_reject_leaves_the_active_revision_and_its_spec_unchanged() -> None:
    h = modify_harness(capacity_scripts(12))
    base_spec = h.repo.revisions[h.base_id].spec.model_dump(mode="json")
    run = await h.start_change()
    done = await h.orch.reject(run.id)
    assert done.status == "rejected"
    assert h.repo.revisions[run.state.revision_id].status == "rejected"
    assert h.repo.bots[h.bot_id].active_revision_id == h.base_id
    assert h.repo.revisions[h.base_id].status == "active"
    assert h.repo.revisions[h.base_id].spec.model_dump(mode="json") == base_spec
    with pytest.raises(OrchestratorError):
        await h.orch.approve(run.id)


async def test_stale_base_at_approval_ends_the_run() -> None:
    h = modify_harness(capacity_scripts(12))
    run = await h.start_change()
    # Meanwhile the owner rolled back / activated another revision.
    other = h.repo.add_revision(h.bot_id, BotSpec.model_validate(golden_spec()))
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.approve(run.id)
    assert refused.value.code == "stale_base"
    assert "دوباره بفرستید" in refused.value.message
    ended = await h.repo.load_run(run.id)
    assert ended.status == "failed" and ended.state.error == "stale_base"
    assert h.repo.revisions[run.state.revision_id].status == "rejected"
    assert h.repo.bots[h.bot_id].active_revision_id == other
    assert h.of_type(run.id, "agent_message")[-1]["text"] == refused.value.message
    assert h.of_type(run.id, "deployed") == []


async def test_stale_base_refused_by_activation_also_ends_the_run() -> None:
    """Same outcome when only the revisions service notices (the parent check at activation)."""
    h = modify_harness(capacity_scripts(12))
    run = await h.start_change()
    h.repo.revisions[run.state.revision_id].parent_id = "someone-else"
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.approve(run.id)
    assert refused.value.code == "stale_base"
    assert (await h.repo.load_run(run.id)).status == "failed"
    assert h.repo.bots[h.bot_id].active_revision_id == h.base_id


# --------------------------------------------------------------------------- triage


@pytest.mark.parametrize(
    ("intent", "reply", "expect"),
    [
        ("question", "ظرفیت هر کارگاه ۱۰ نفر است.", "ظرفیت هر کارگاه ۱۰ نفر است."),
        ("data_request", "برای افزودن کارگاه جدید", "«داده‌ها»"),
        ("data_request", "این کار را در بخش داده‌ها انجام دهید.", "این کار را در بخش داده‌ها انجام دهید."),
        ("unsupported", "پرداخت آنلاین پشتیبانی نمی‌شود؛ می‌توانید قیمت را نمایش دهید.", "پرداخت آنلاین"),
        ("unsupported", "", "قابل ساخت نیست"),
    ],
)
async def test_triage_non_change_outcomes_end_the_run_without_a_revision(
    intent: str, reply: str, expect: str
) -> None:
    h = modify_harness({"structured": {"triage": [triage_out(intent, reply)]}})
    run = await h.start_change("یک کارگاه جمعه اضافه کن")
    assert run.status == "done" and run.state.triage == intent
    assert [c.task for c in h.llm.calls] == ["triage"]
    triage_call = h.llm.calls[0]
    assert triage_call.tier == "fast"
    content = triage_call.messages[0]["content"]
    assert (
        "<owner_message>" in content
        and "<bot_outline>" in content
        and "ظرفیت هر کارگاه ۱۰ نفر است." in content
    )
    assert '"value":10' not in content  # outline only, never rule values
    assert expect in h.of_type(run.id, "agent_message")[-1]["text"]
    assert list(h.repo.revisions) == [h.base_id]
    phases = [(e.type, e.payload["phase"]) for e in h.events(run.id) if e.type.startswith("phase_")]
    assert phases == [("phase_started", "triage"), ("phase_finished", "triage")]
    # The bot is free for the next run.
    h.llm.structured_scripts["triage"] = [triage_out("question", "بله.")]
    assert (await h.start_change("سؤال دیگر")).status == "done"


async def test_triage_change_continues_into_understand_change() -> None:
    h = modify_harness(capacity_scripts(12))
    run = await h.start_change()
    assert run.state.triage == "change"
    assert [c.task for c in h.llm.calls][:2] == ["triage", "understand"]
    understand = h.llm.calls[1]
    assert understand.tier == "strong"
    content = understand.messages[0]["content"]
    assert "<base_requirements>" in content and "<bot_outline>" in content
    assert "Task: understand (change to a live bot)" in content


# --------------------------------------------------------------------------- understand_change


def test_normalize_delta_ids_and_application() -> None:
    base = Requirements.model_validate(golden_requirements())
    raw = RequirementsDelta.model_validate(
        {
            "added": [deadline_requirement("R1")],  # a reused id: renumbered
            "changed": [
                capacity_requirement(12),
                capacity_requirement(12, "R77"),
                golden_requirements()["items"][0],
            ],
            "removed": ["R6", "R6", "R99"],
            "unsupported": [],
            "open_questions": [],
        }
    )
    delta = normalize_delta(raw, base)
    assert [r.id for r in delta.added] == ["R8", "R9"]  # R77 is unknown: treated as an addition
    assert [r.id for r in delta.changed] == ["R2"]  # R1 unchanged statement dropped
    assert delta.removed == ["R6"]
    new = apply_delta(base, delta)
    assert [r.id for r in new.items] == ["R1", "R2", "R3", "R4", "R5", "R7", "R8", "R9"]
    assert new.items[1].statement == capacity_requirement(12)["statement"]


async def test_blocking_question_pauses_then_the_answer_resumes_the_change() -> None:
    scripts = capacity_scripts(12)
    scripts["structured"]["understand"] = [
        change_out(
            changed=[capacity_requirement(12)], questions=[blocking_question(text="برای همهٔ کارگاه‌ها؟")]
        ),
        change_out(changed=[capacity_requirement(12)]),
    ]
    h = modify_harness(scripts)
    run = await h.start_change()
    assert run.status == "waiting_user" and run.phase == "clarify"
    assert h.of_type(run.id, "questions")[0]["questions"][0]["text"] == "برای همهٔ کارگاه‌ها؟"
    run = await h.answer(run.id, "بله، همه.")
    assert run.status == "waiting_approval", run.state.error
    assert [c.task for c in h.llm.calls].count("triage") == 1  # answers go to understand, not triage
    second = [c for c in h.llm.calls if c.task == "understand"][1]
    assert (
        "بله، همه." in second.messages[0]["content"] and "<previous_delta>" in second.messages[0]["content"]
    )


async def test_important_question_becomes_an_assumed_added_requirement() -> None:
    scripts = deadline_scripts(rid="R8")
    important = {**blocking_question(), "severity": "important"}
    scripts["structured"]["understand"] = [
        change_out(added=[deadline_requirement("R1")], questions=[important])
    ]
    h = modify_harness(scripts)
    run = await h.start_change(MOD_DEADLINE)
    assert run.status == "waiting_approval", run.state.error
    assert [(r.id, r.status) for r in run.state.delta.added] == [("R8", "confirmed"), ("R9", "assumed")]
    assert h.of_type(run.id, "questions") == []


async def test_empty_delta_asks_what_to_change_then_ends_without_a_revision() -> None:
    h = modify_harness({"structured": {"triage": [triage_out()], "understand": [change_out()] * 3}})
    run = await h.start_change("یک چیزی را بهتر کن")
    assert run.status == "waiting_user"
    run = await h.answer(run.id, "نمی‌دانم")
    assert run.status == "waiting_user"
    run = await h.answer(run.id, "هیچ")
    assert run.status == "done"
    assert list(h.repo.revisions) == [h.base_id]


async def test_owner_message_while_awaiting_approval_reenters_understand_change_with_the_draft() -> None:
    scripts = capacity_scripts(12)
    scripts["structured"]["understand"].append(
        change_out(changed=[capacity_requirement(12)], added=[deadline_requirement("R8")])
    )
    # Round 2 keeps the 12-seat scenario (R2 untouched this round) and writes tests for R8 only.
    scripts["structured"]["testgen"].append({"scenarios": deadline_scenarios("R8")})
    scripts["loops"]["build"].append([[patch({"op": "set", "path": DEADLINE_HOURS, "value": 2})], [finish()]])
    h = modify_harness(scripts)
    run = await h.start_change()
    first_revision = run.state.revision_id
    run = await h.answer(run.id, MOD_DEADLINE)
    assert run.status == "waiting_approval", run.state.error
    understand = [c for c in h.llm.calls if c.task == "understand"][1]
    assert (
        MOD_CAPACITY in understand.messages[0]["content"]
        and MOD_DEADLINE in understand.messages[0]["content"]
    )
    build = [c for c in h.llm.calls if c.task == "build"][1]
    assert '"value":12' in build.messages[0]["content"]  # the current draft, not the base
    assert h.repo.revisions[first_revision].status == "rejected"
    draft = h.repo.revisions[run.state.revision_id]
    assert draft.parent_id == h.base_id
    assert [op["path"] for op in draft.patch] == [CAPACITY_VALUE, DEADLINE_HOURS]
    # The 10-seat scenario stays superseded: R2 is still changed.
    assert [s["scenario"]["id"] for s in draft.superseded] == ["golden_capacity_10_real"]
    assert run.state.test_report.failed == 0
    assert len(h.of_type(run.id, "diff")[-1]["changes"]) == 2
    done = await h.orch.approve(run.id)
    assert done.status == "done"


# --------------------------------------------------------------------------- events, risk, API rules


async def test_event_sequence_and_payload_shapes() -> None:
    h = modify_harness(capacity_scripts(12))
    run = await h.start_change()
    await h.orch.approve(run.id)
    events = h.events(run.id)
    phases = [(e.type, e.payload["phase"]) for e in events if e.type in ("phase_started", "phase_finished")]
    assert phases == [
        (kind, phase)
        for phase in ("triage", "understand", "build", "testgen", "run", "repair", "run", "review", "deploy")
        for kind in ("phase_started", "phase_finished")
    ]
    types = [e.type for e in events]
    assert types[0] == "owner_message"
    assert types.index("requirements") < types.index("tool_call") < types.index("tests_generated")
    assert (
        types.index("test_report")
        < types.index("diff")
        < types.index("approval_requested")
        < types.index("deployed")
    )
    (diff,) = h.of_type(run.id, "diff")
    assert set(diff) == {"changes", "affected_capabilities", "tests", "risk", "warnings", "requirements"}
    assert set(diff["requirements"]) == {"added", "changed", "removed"}
    assert all(set(c) == {"id", "before", "after"} for c in diff["requirements"]["changed"])
    assert set(diff["tests"]) == {"carried", "new", "superseded"}
    assert all(set(c) == {"label_fa", "kind"} for c in diff["changes"])
    assert all(set(s) == {"title", "reason"} for s in diff["tests"]["superseded"])
    assert diff["risk"] in ("low", "medium", "high")
    calls = [e.payload for e in events if e.type == "tool_call"]
    assert {c["loop"] for c in calls} == {"build", "repair"}
    assert all(set(c) == {"loop", "name", "summary"} for c in calls)
    build_tools = next(c for c in h.llm.calls if c.task == "build").tools
    assert "set_spec" not in build_tools and "apply_spec_patch" in build_tools
    repair_tools = next(c for c in h.llm.calls if c.task == "repair").tools
    assert "supersede_scenario" in repair_tools and "fix_scenario" in repair_tools


def _change(path: list[str], kind: str, old: object = None, new: object = None):
    from app.botspec.diff import SpecChange

    return SpecChange(path=path, kind=kind, old=old, new=new, label_fa="x")  # type: ignore[arg-type]


def test_risk_rule() -> None:
    scalar = _change(CAPACITY_VALUE, "changed", 10, 12)
    text = _change(["capabilities", "book_workshop", "texts", "booked"], "added", None, {"key": "booked"})
    welcome = _change(["bot", "welcome_text"], "changed", "a", "b")
    menu = _change(["menu", "about"], "removed", {"key": "about"})
    field = _change(["resources", "workshop", "fields", "phone"], "added", None, {"key": "phone"})
    warning = SpecIssue(path=["x"], code="capacity_lowered", message="m", severity="warning")
    assert risk_level([], []) == "low"
    assert risk_level([scalar, welcome, text], []) == "low"
    assert risk_level([scalar, menu], []) == "medium"
    assert risk_level([field], []) == "medium"
    assert risk_level([scalar], [warning]) == "high"


async def test_one_active_run_per_bot_and_modify_needs_an_active_revision() -> None:
    h = modify_harness(capacity_scripts(12))
    run = await h.start_change()
    with pytest.raises(ActiveRunExists):
        await h.orch.start_modify(h.bot_id, "دوباره")
    await h.orch.reject(run.id)
    empty_bot = h.repo.add_bot("بدون نسخه")
    with pytest.raises(OrchestratorError) as refused:
        await h.orch.start_modify(empty_bot, "تغییر")
    assert refused.value.code == "no_active_revision"
    started = await h.orch.start(h.bot_id, "سؤال")
    assert started.kind == "modify"


async def test_sample_data_is_regenerated_only_for_an_added_resource() -> None:
    teacher = {
        "key": "teacher_res",
        "label": "مدرس",
        "label_plural": "مدرسان",
        "title_field": "name",
        "fields": [
            {
                "key": "name",
                "label": "نام",
                "type": "text",
                "required": True,
                "choices": None,
                "default": None,
            }
        ],
    }
    added = {"id": "R1", "kind": "data", "statement": "فهرست مدرسان نگه داشته می‌شود.", "status": "confirmed"}
    teacher_scenario = {
        **deadline_scenarios("R8")[1],
        "id": "acc_still_books",
        "requirement_ids": ["R8"],
    }
    sample = {
        "records": [{"ref": "t1", "collection": "teacher_res", "values": [{"key": "name", "value": "مریم"}]}]
    }
    h = modify_harness(
        {
            "structured": {
                "triage": [triage_out()],
                "understand": [change_out(added=[added])],
                "testgen": [{"scenarios": [teacher_scenario]}],
                "sample_data": [sample],
            },
            "loops": {
                "build": [[[patch({"op": "add", "path": ["resources"], "value": teacher})], [finish()]]]
            },
        }
    )
    run = await h.start_change("فهرست مدرسان را هم نگه دار")
    assert run.status == "waiting_approval", run.state.error
    sample_call = next(c for c in h.llm.calls if c.task == "sample_data")
    assert (
        "teacher_res" in sample_call.messages[0]["content"]
        and '"key":"workshop"' not in sample_call.messages[0]["content"]
    )
    collections = [s.collection for s in h.repo.revisions[run.state.revision_id].sample_data]
    assert collections == ["workshop", "workshop", "teacher_res"]
    (diff,) = h.of_type(run.id, "diff")
    assert diff["risk"] == "medium"
    assert sample_out()["records"][0]["ref"] == "s1"
