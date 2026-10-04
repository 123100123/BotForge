"""Live evaluation of the CREATE flow on the golden prompt (real model, in-memory persistence).

For each run: start a CREATE run for the golden Persian prompt, auto-answer clarification questions
from a small canned map, stop at the approval point, check the result, approve (in memory), and
print spec validity, scenario counts and results, tool calls, tokens, cost, and PASS/FAIL.

PASS means: the run reached approval with can_approve, every scenario passed, the spec is valid,
the booking uses fixed capacity 10 with the waitlist and automatic promotion enabled and
cancellation allowed, at least two acceptance scenarios were kept, and activation succeeded.

Usage (from backend/, needs ANTHROPIC_API_KEY; each run costs real money):
    uv run python scripts/eval_golden.py --create [--runs N] [--verbose]
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.context import Limits
from app.agent.events import EventBus
from app.agent.llm import AnthropicLLM
from app.agent.orchestrator import Orchestrator, OrchestratorError
from app.agent.repository import InMemoryAgentRepository
from app.botspec.models import BookingCapability
from app.botspec.validate import check_spec, has_errors

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

# Canned owner answers: the first entry whose keyword appears in the question text wins.
CANNED_ANSWERS: list[tuple[tuple[str, ...], str]] = [
    (("شماره", "تلفن", "تماس"), "نه، شماره تماس لازم نیست."),
    (("ظرفیت",), "ظرفیت همهٔ کارگاه‌ها ۱۰ نفر است."),
    (("لغو", "انصراف"), "لغو تا هر زمانی قبل از شروع کارگاه آزاد است."),
    (("انتظار",), "بله، با لیست انتظار و جایگزینی خودکار."),
    (("پرداخت", "هزینه", "قیمت"), "پرداخت آنلاین لازم نیست؛ فقط قیمت نمایش داده شود."),
    (("اطلاع", "پیام", "خبر"), "بله، من از هر ثبت‌نام و لغو مطلع شوم."),
]
DEFAULT_ANSWER = "هر طور که خودتان پیشنهاد می‌کنید."


def golden_prompt() -> str:
    text = (EXAMPLES / "prompts.fa.md").read_text(encoding="utf-8")
    return text.split("## Create", 1)[1].split("##", 1)[0].strip()


def answer_for(questions: list[dict[str, Any]]) -> str:
    lines = []
    for q in questions:
        text = q.get("text", "")
        reply = next((a for keys, a in CANNED_ANSWERS if any(k in text for k in keys)), DEFAULT_ANSWER)
        lines.append(reply)
    return " ".join(dict.fromkeys(lines)) or DEFAULT_ANSWER


async def one_run(index: int, llm: AnthropicLLM, verbose: bool) -> dict[str, Any]:
    repo = InMemoryAgentRepository()
    orch = Orchestrator(repo, llm, limits=Limits.from_settings(), bus=EventBus())
    bot_id = repo.add_bot("ارزیابی")
    started = time.perf_counter()
    record = await orch.start_create(bot_id, golden_prompt())
    await orch.advance(record.id)
    record = await repo.load_run(record.id)
    answers = 0
    while record.status == "waiting_user" and answers < 3:
        asked = [e.payload for e in repo.events_for(record.id) if e.type == "questions"]
        reply = answer_for(asked[-1]["questions"] if asked else [])
        answers += 1
        await orch.post_message(record.id, reply)
        await orch.advance(record.id)
        record = await repo.load_run(record.id)

    state = record.state
    out: dict[str, Any] = {
        "run": index,
        "status": record.status,
        "phase": record.phase,
        "clarify_answers": answers,
        "seconds": round(time.perf_counter() - started, 1),
        "tool_calls": state.usage.tool_calls,
        "llm_calls": state.usage.llm_calls,
        "input_tokens": state.usage.input_tokens,
        "cached_tokens": state.usage.cached_tokens,
        "cache_write_tokens": state.usage.cache_write_tokens,
        "output_tokens": state.usage.output_tokens,
        "cost_usd": round(state.usage.cost_usd, 4),
        "error": state.error,
    }
    checks: dict[str, bool] = {}
    if state.draft_spec is not None:
        issues = check_spec(state.draft_spec.model_dump(mode="json"))
        checks["spec_valid"] = not has_errors(issues)
        booking = next((c for c in state.draft_spec.capabilities if isinstance(c, BookingCapability)), None)
        checks["booking"] = booking is not None
        if booking is not None:
            checks["fixed_capacity_10"] = booking.capacity.mode == "fixed" and booking.capacity.value == 10
            checks["waitlist_auto_promote"] = booking.waitlist.enabled and booking.waitlist.auto_promote
            checks["cancellation_enabled"] = booking.cancellation.enabled
    else:
        checks["spec_valid"] = False
    report = state.test_report
    out["scenarios"] = {"derived": len(state.derived), "acceptance": len(state.scenarios)}
    if report is not None:
        out["tests"] = {"total": report.total, "passed": report.passed, "failed": report.failed}
        out["failing"] = [r.scenario_id for r in report.results if not r.passed]
        checks["all_tests_pass"] = report.failed == 0
    else:
        checks["all_tests_pass"] = False
    checks["acceptance_at_least_2"] = len(state.scenarios) >= 2
    approval = [e.payload for e in repo.events_for(record.id) if e.type == "approval_requested"]
    checks["can_approve"] = bool(approval and approval[-1]["can_approve"])
    if record.status == "waiting_approval" and checks["can_approve"]:
        try:
            done = await orch.approve(record.id)
            checks["activated"] = done.status == "done"
        except OrchestratorError as exc:
            out["approve_error"] = exc.message
            checks["activated"] = False
    else:
        checks["activated"] = False
    out["repair_rounds"] = state.repair_rounds
    out["checks"] = checks
    out["result"] = "PASS" if all(checks.values()) else "FAIL"
    if verbose:
        out["requirements"] = state.requirements.model_dump(mode="json") if state.requirements else None
        out["events"] = [(e.type, e.payload) for e in repo.events_for(record.id) if e.type != "spec_updated"]
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--create", action="store_true", help="evaluate the CREATE flow (the only mode so far)"
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not args.create:
        parser.error("choose a flow to evaluate: --create")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    llm = AnthropicLLM()
    print(f"strong={llm.strong_model} fast={llm.fast_model} runs={args.runs}")
    results = []
    for i in range(1, args.runs + 1):
        result = await one_run(i, llm, args.verbose)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    passed = sum(1 for r in results if r["result"] == "PASS")
    cost = sum(r["cost_usd"] for r in results)
    print(
        f"\nSUMMARY: {passed}/{len(results)} PASS, total cost ${cost:.4f}, "
        f"mean tool calls {sum(r['tool_calls'] for r in results) / len(results):.1f}"
    )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
