"""Live evaluation of the golden CREATE and MODIFY flows (real model, in-memory persistence).

--create: for each run, start a CREATE run for the golden Persian prompt, auto-answer clarification
questions from a small canned map, stop at the approval point, check the result, approve (in
memory), and print spec validity, scenario counts and results, tool calls, tokens, cost, and
PASS/FAIL. PASS means: the run reached approval with can_approve, every scenario passed, the spec
is valid, the booking uses fixed capacity 10 with the waitlist and automatic promotion enabled and
cancellation allowed, at least two acceptance scenarios were kept, and activation succeeded.

--modify: for each run, start from a base revision built from examples/workshop.botspec.json,
workshop.requirements.json and workshop.scenarios.json (as acceptance scenarios), then run the two
golden modification prompts from examples/prompts.fa.md in sequence, approving each. PASS per
modification means: the run reached approval with can_approve; the spec diff against the live
revision is exactly the expected change (capacity value 12; cancellation.deadline_hours 2); every
scenario passed; for the capacity change only ``golden_capacity_10_real`` was superseded (nothing
for the deadline); at least one new acceptance scenario exists; activation succeeded.

Usage (from backend/, needs ANTHROPIC_API_KEY, or LLM_PROVIDER=openai with an endpoint chain as in
README "Environment"; each run costs real money):
    uv run python scripts/eval_golden.py --create [--runs N] [--verbose]
    uv run python scripts/eval_golden.py --modify [--runs N] [--verbose]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.context import Limits
from app.agent.events import EventBus
from app.agent.llm import LLMClient, Usage, make_llm
from app.agent.orchestrator import Orchestrator, OrchestratorError
from app.agent.repository import InMemoryAgentRepository
from app.agent.requirements import Requirements
from app.botspec.diff import diff_specs
from app.botspec.models import BookingCapability, BotSpec
from app.botspec.validate import check_spec, has_errors
from app.testing.scenario import Scenario

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


def prompt_section(title: str) -> str:
    text = (EXAMPLES / "prompts.fa.md").read_text(encoding="utf-8")
    return text.split(f"## {title}", 1)[1].split("##", 1)[0].strip()


def golden_prompt() -> str:
    return prompt_section("Create")


# (name, prompts.fa.md section, expected changed path, expected value, expected superseded ids)
MODIFICATIONS: list[tuple[str, str, list[str], Any, list[str]]] = [
    (
        "capacity_12",
        "Modification 1",
        ["capabilities", "book_workshop", "capacity", "value"],
        12,
        ["golden_capacity_10_real"],
    ),
    (
        "deadline_2h",
        "Modification 2",
        ["capabilities", "book_workshop", "cancellation", "deadline_hours"],
        2,
        [],
    ),
]
MODIFY_DEFAULT_ANSWER = "بله، همین تغییر را برای همهٔ کارگاه‌ها اعمال کن."


def _load(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def seed_base(repo: InMemoryAgentRepository, bot_id: str) -> str:
    """The base revision: the golden spec, its requirements, and every golden scenario."""
    return repo.add_revision(
        bot_id,
        BotSpec.model_validate(_load("workshop.botspec.json")),
        requirements=Requirements.model_validate(_load("workshop.requirements.json")),
        scenarios=[Scenario.model_validate(s) for s in _load("workshop.scenarios.json")],
    )


def _usage_out(u: Usage) -> dict[str, Any]:
    return {
        "llm_calls": u.llm_calls,
        "tool_calls": u.tool_calls,
        "input_tokens": u.input_tokens,
        "cached_tokens": u.cached_tokens,
        "cache_write_tokens": u.cache_write_tokens,
        "output_tokens": u.output_tokens,
        "cost_usd": round(u.cost_usd, 4),
    }


async def one_modification(
    orch: Orchestrator,
    repo: InMemoryAgentRepository,
    bot_id: str,
    spec: tuple[str, str, list[str], Any, list[str]],
    verbose: bool,
) -> dict[str, Any]:
    name, section_title, path, value, expect_superseded = spec
    before = await repo.load_revision_spec(repo.bots[bot_id].active_revision_id or "")
    started = time.perf_counter()
    record = await orch.start_modify(bot_id, prompt_section(section_title))
    await orch.advance(record.id)
    record = await repo.load_run(record.id)
    answers = 0
    while record.status == "waiting_user" and answers < 2:
        asked = [e.payload for e in repo.events_for(record.id) if e.type == "questions"]
        reply = answer_for(asked[-1]["questions"]) if asked else MODIFY_DEFAULT_ANSWER
        answers += 1
        await orch.post_message(record.id, reply)
        await orch.advance(record.id)
        record = await repo.load_run(record.id)
    state = record.state
    out: dict[str, Any] = {
        "modification": name,
        "status": record.status,
        "phase": record.phase,
        "triage": state.triage,
        "clarify_answers": answers,
        "repair_rounds": state.repair_rounds,
        "seconds": round(time.perf_counter() - started, 1),
        **_usage_out(state.usage),
        "error": state.error,
    }
    checks: dict[str, bool] = {}
    changes = diff_specs(before, state.draft_spec) if state.draft_spec is not None else []
    out["changes"] = [c.label_fa for c in changes]
    checks["expected_change_only"] = [c.path for c in changes] == [path] and changes[0].new == value
    report = state.test_report
    checks["all_tests_pass"] = report is not None and report.failed == 0
    if report is not None:
        out["tests"] = {"total": report.total, "passed": report.passed, "failed": report.failed}
        out["failing"] = [r.scenario_id for r in report.results if not r.passed]
    superseded = [s.scenario.id for s in state.superseded]
    out["superseded"] = [{"id": s.scenario.id, "reason": s.reason} for s in state.superseded]
    checks["superseded_as_expected"] = superseded == expect_superseded
    out["new_scenarios"] = list(state.new_scenario_ids)
    checks["new_acceptance"] = len(state.new_scenario_ids) >= 1
    diff = [e.payload for e in repo.events_for(record.id) if e.type == "diff"]
    out["risk"] = diff[-1]["risk"] if diff else None
    approval = [e.payload for e in repo.events_for(record.id) if e.type == "approval_requested"]
    checks["can_approve"] = bool(approval and approval[-1]["can_approve"])
    checks["activated"] = False
    if record.status == "waiting_approval" and checks["can_approve"]:
        try:
            checks["activated"] = (await orch.approve(record.id)).status == "done"
        except OrchestratorError as exc:
            out["approve_error"] = exc.message
    out["checks"] = checks
    out["result"] = "PASS" if all(checks.values()) else "FAIL"
    if verbose:
        out["delta"] = state.delta.model_dump(mode="json") if state.delta else None
        out["events"] = [(e.type, e.payload) for e in repo.events_for(record.id) if e.type != "spec_updated"]
    return out


async def one_modify_run(index: int, llm: LLMClient, verbose: bool) -> dict[str, Any]:
    """Both golden modifications in sequence on one bot; stops at the first that does not activate."""
    repo = InMemoryAgentRepository()
    orch = Orchestrator(repo, llm, limits=Limits.from_settings(), bus=EventBus())
    bot_id = repo.add_bot("ارزیابی")
    seed_base(repo, bot_id)
    mods: list[dict[str, Any]] = []
    for spec in MODIFICATIONS:
        result = await one_modification(orch, repo, bot_id, spec, verbose)
        mods.append(result)
        if not result["checks"]["activated"]:
            break
    passed = len(mods) == len(MODIFICATIONS) and all(m["result"] == "PASS" for m in mods)
    return {
        "run": index,
        "modifications": mods,
        "revisions": len(repo.revisions),
        "tool_calls": sum(m["tool_calls"] for m in mods),
        "input_tokens": sum(m["input_tokens"] for m in mods),
        "output_tokens": sum(m["output_tokens"] for m in mods),
        "cost_usd": round(sum(m["cost_usd"] for m in mods), 4),
        "result": "PASS" if passed else "FAIL",
    }


def answer_for(questions: list[dict[str, Any]]) -> str:
    lines = []
    for q in questions:
        text = q.get("text", "")
        reply = next((a for keys, a in CANNED_ANSWERS if any(k in text for k in keys)), DEFAULT_ANSWER)
        lines.append(reply)
    return " ".join(dict.fromkeys(lines)) or DEFAULT_ANSWER


async def one_run(index: int, llm: LLMClient, verbose: bool) -> dict[str, Any]:
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


def api_key_available() -> bool:
    """The configured provider has credentials: ANTHROPIC_API_KEY, or an LLM_PROVIDER=openai chain."""
    from app.agent.llm_openai import endpoints_from_settings
    from app.config import get_settings

    settings = get_settings()
    if settings.LLM_PROVIDER == "openai":
        return bool(endpoints_from_settings(settings)[0])
    return bool(os.environ.get("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--create", action="store_true", help="evaluate the CREATE flow")
    mode.add_argument(
        "--modify", action="store_true", help="evaluate the two golden modifications in sequence"
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not (args.create or args.modify):
        parser.error("choose a flow to evaluate: --create or --modify")
    if not api_key_available():
        print(
            "ANTHROPIC_API_KEY is not set (environment or backend/.env), or with LLM_PROVIDER=openai "
            "no endpoint has both a BASE_URL and an API_KEY. This script calls the live model and "
            "costs real money; set the credentials and run it again.",
            file=sys.stderr,
        )
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    llm: Any = make_llm()
    print(
        f"mode={'modify' if args.modify else 'create'} provider={type(llm).__name__} "
        f"strong={llm.strong_model} fast={llm.fast_model} runs={args.runs}"
    )
    results = []
    for i in range(1, args.runs + 1):
        if args.modify:
            result = await one_modify_run(i, llm, args.verbose)
        else:
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
