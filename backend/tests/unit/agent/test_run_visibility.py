"""Run visibility events: activity, retrying, error codes, retry, and the terminal run_status."""

import asyncio
from typing import Any

import pytest

from app.agent import events as ev
from app.agent.llm import FakeLLM, LLMError, PlainJsonRetry, Usage
from app.agent.orchestrator import LLM_UNAVAILABLE_TEXT, OrchestratorError
from app.agent.repository import ActiveRunExists
from tests.unit.agent.helpers import (
    GOLDEN_PROMPT,
    Harness,
    golden_acceptance,
    harness,
    understand_out,
)


def sequence(h: Harness, run_id: str, *types: str) -> list[tuple[str, dict[str, Any]]]:
    return [(e.type, e.payload) for e in h.events(run_id) if e.type in types]


def test_activity_labels_are_persian_and_turn_aware() -> None:
    assert ev.activity("understand") == (
        "activity",
        {"phase": "understand", "label": "در حال فهمیدن درخواست شما…"},
    )
    assert ev.activity("triage")[1]["label"] == "در حال بررسی درخواست تغییر…"
    assert ev.activity("build")[1]["label"] == "در حال ساخت پیکربندی ربات…"
    assert ev.activity("build", 2)[1]["label"] == "در حال ادامهٔ ساخت…"
    assert ev.activity("testgen")[1]["label"] == "در حال نوشتن آزمون‌ها…"
    assert ev.activity("repair")[1]["label"] == "در حال رفع مشکل آزمون‌ها…"
    assert ev.activity("review")[1]["label"] == "در حال آماده کردن خلاصه برای شما…"
    assert ev.activity("understand", 3)[1]["label"] == ev.ACTIVITY_LABELS["understand"]
    assert ev.retrying("build", 2, "x") == ("retrying", {"phase": "build", "attempt": 2, "reason": "x"})
    assert ev.run_interrupted() == ("run_interrupted", {"reason": "server_restart"})


async def test_activity_follows_phase_started_before_each_model_call() -> None:
    h = harness()
    run = await h.start()
    seq = sequence(h, run.id, "phase_started", "phase_finished", "activity")
    label = ev.ACTIVITY_LABELS
    assert seq == [
        ("phase_started", {"phase": "understand"}),
        ("activity", {"phase": "understand", "label": label["understand"]}),
        ("phase_finished", {"phase": "understand", "ok": True}),
        ("phase_started", {"phase": "build"}),
        ("activity", {"phase": "build", "label": label["build"]}),
        ("activity", {"phase": "build", "label": ev.CONTINUE_LABELS["build"]}),  # build_ok has 2 turns
        ("phase_finished", {"phase": "build", "ok": True}),
        ("phase_started", {"phase": "testgen"}),
        ("activity", {"phase": "testgen", "label": label["testgen"]}),
        ("phase_finished", {"phase": "testgen", "ok": True}),
        ("phase_started", {"phase": "run"}),
        ("phase_finished", {"phase": "run", "ok": True}),
        ("phase_started", {"phase": "review"}),
        ("activity", {"phase": "review", "label": label["review"]}),  # the sample-data call
        ("phase_finished", {"phase": "review", "ok": True}),
    ]
    # The activity event comes before what the call produced.
    types = [e.type for e in h.events(run.id)]
    assert types.index("activity") < types.index("requirements")
    assert types.index("activity", types.index("requirements")) < types.index("tool_call")


async def test_plain_json_fallback_emits_retrying_after_activity() -> None:
    h = harness(structured={"understand": [PlainJsonRetry(understand_out())]})
    run = await h.start()
    types = [e.type for e in h.events(run.id)]
    i = types.index("retrying")
    assert types[i - 1] == "activity"
    assert h.events(run.id)[i].payload == {
        "phase": "understand",
        "attempt": 2,
        "reason": "ساختار خروجی مدل پذیرفته نشد؛ دوباره با قالب ساده تلاش می‌کنم.",
    }
    assert run.status == "waiting_approval"


async def test_testgen_corrective_retry_emits_retrying_then_activity() -> None:
    bad = [
        {"id": "acc_bad", "title": "x", "source": "acceptance", "requirement_ids": ["R_NOPE"], "steps": []}
    ]
    h = harness(structured={"testgen": [{"scenarios": bad}, {"scenarios": golden_acceptance()}]})
    run = await h.start()
    retries = [p for _, p in sequence(h, run.id, "retrying")]
    assert len(retries) == 1 and retries[0]["phase"] == "testgen" and retries[0]["attempt"] == 2
    types = [e.type for e in h.events(run.id)]
    assert types[types.index("retrying") + 1] == "activity"


class FailingBuildLLM(FakeLLM):
    async def tool_loop(self, **kwargs: Any) -> Any:
        raise LLMError("api_error", "connection refused", usage=Usage(input_tokens=5, llm_calls=1))


async def test_build_llm_error_maps_to_llm_unavailable() -> None:
    h = harness()
    h.orch.llm = FailingBuildLLM(structured={"understand": [understand_out()]})
    run = await h.start()
    assert run.status == "failed" and run.phase == "failed"
    (err,) = [e.payload for e in h.events(run.id) if e.type == "error"]
    assert err == {
        "message": LLM_UNAVAILABLE_TEXT,
        "code": "LLM_UNAVAILABLE",
        "applied": False,
        "retryable": True,
    }
    last = h.events(run.id)[-1]
    assert (last.type, last.payload) == ("run_status", {"status": "failed", "phase": "failed"})


async def test_budget_failure_is_budget_exceeded_and_not_retryable() -> None:
    h = harness(usage_per_call=Usage(input_tokens=10**7, output_tokens=10, llm_calls=1))
    run = await h.start()
    assert run.status == "failed"
    errors = [e.payload for e in h.events(run.id) if e.type == "error"]
    assert errors[0]["code"] == "BUDGET_EXCEEDED" and errors[0]["retryable"] is False
    assert all(e["applied"] is False for e in errors)


async def test_understand_api_error_is_llm_unavailable() -> None:
    h = harness(structured={"understand": [LLMError("api_error", "down")]})
    run = await h.start()
    (err,) = [e.payload for e in h.events(run.id) if e.type == "error"]
    assert err["code"] == "LLM_UNAVAILABLE" and err["retryable"] is True and err["applied"] is False


async def test_terminal_status_is_saved_together_with_its_run_status_event() -> None:
    h = harness()
    saves: list[tuple[str, str | None]] = []
    original = h.repo.save_run

    async def spy(run_id: str, **kwargs: Any) -> Any:
        event = kwargs.get("event")
        saves.append((kwargs["status"], event[1]["status"] if event else None))
        return await original(run_id, **kwargs)

    h.repo.save_run = spy  # type: ignore[method-assign]
    run = await h.start()
    await h.orch.reject(run.id)
    assert ("waiting_approval", "waiting_approval") in saves and ("rejected", "rejected") in saves
    last = h.events(run.id)[-1]
    assert (last.type, last.payload["status"]) == ("run_status", "rejected")
    assert h.events(run.id)[-2].type == "agent_message"
    approved = harness()
    run2 = await approved.start()
    await approved.orch.approve(run2.id)
    assert approved.events(run2.id)[-1].payload == {"status": "done", "phase": "deploy"}


async def test_cancelled_run_is_interrupted_with_an_event() -> None:
    h = harness()
    started = asyncio.Event()

    class Hanging(FakeLLM):
        async def structured(self, **kwargs: Any) -> Any:
            started.set()
            await asyncio.sleep(60)

    h.orch.llm = Hanging()
    record = await h.orch.start_create(h.bot_id, GOLDEN_PROMPT)
    task = h.orch.spawn(record.id)
    await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    tail = [(e.type, e.payload) for e in h.events(record.id)][-2:]
    assert tail == [
        ("run_interrupted", {"reason": "server_restart"}),
        ("run_status", {"status": "interrupted", "phase": "understand"}),
    ]


async def test_retry_creates_a_new_run_from_the_first_owner_message() -> None:
    h = harness(structured={"understand": [LLMError("api_error", "down"), understand_out()]})
    failed = await h.start()
    assert failed.status == "failed"
    new = await h.orch.retry(failed.id)
    assert new.id != failed.id and new.kind == "create" and new.bot_id == failed.bot_id
    assert new.status == "running"
    assert h.of_type(new.id, "owner_message") == [{"text": GOLDEN_PROMPT}]
    await h.orch.advance(new.id)
    assert (await h.repo.load_run(new.id)).status == "waiting_approval"


async def test_retry_refuses_runs_that_are_not_failed_or_interrupted() -> None:
    h = harness()
    run = await h.start()  # waiting_approval
    with pytest.raises(OrchestratorError) as exc:
        await h.orch.retry(run.id)
    assert exc.value.status == 409 and exc.value.code == "run_not_retryable"
    done = await h.orch.approve(run.id)
    with pytest.raises(OrchestratorError):
        await h.orch.retry(done.id)


async def test_retry_while_another_run_is_active_is_refused() -> None:
    h = harness(structured={"understand": [LLMError("api_error", "down")]})
    failed = await h.start()
    await h.orch.start_create(h.bot_id, "یک درخواست دیگر")  # now the bot's active run
    with pytest.raises(ActiveRunExists):
        await h.orch.retry(failed.id)
