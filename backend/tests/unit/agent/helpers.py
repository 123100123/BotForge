"""Scripted building blocks for agent tests: golden examples, FakeLLM scripts, a run harness."""

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agent.context import Limits
from app.agent.events import EventBus, EventEnvelope
from app.agent.llm import FakeLLM, FakeTurn, ToolCall, Usage
from app.agent.orchestrator import Orchestrator
from app.agent.repository import InMemoryAgentRepository, LiveStats, RunRecord
from app.agent.requirements import Requirements
from app.botspec.models import BotSpec
from app.testing.scenario import Scenario, SeedRecord

EXAMPLES = Path(__file__).resolve().parents[4] / "examples"
GOLDEN_PROMPT = (
    "من یک آموزشگاه دارم و کارگاه‌های آموزشی برگزار می‌کنم. می‌خواهم مشتری‌ها در ربات تلگرام لیست "
    "کارگاه‌ها را ببینند و ثبت‌نام کنند. ظرفیت هر کارگاه ۱۰ نفر است. اگر ظرفیت پر شد وارد لیست انتظار "
    "شوند و اگر کسی انصراف داد، نفر اول لیست انتظار خودکار جایگزین شود. امکان لغو ثبت‌نام هم باشد."
)
# A subset of the golden acceptance scenarios: short ones, covering R1-R7.
ACCEPTANCE_IDS = (
    "golden_basic_book",
    "golden_capacity_waitlist",
    "golden_duplicate_rejected",
    "golden_cancel_frees_seat",
    "golden_promotion_order",
    "golden_promotion_notifies",
)


def load_json(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def golden_spec() -> dict[str, Any]:
    return load_json("workshop.botspec.json")


def golden_requirements() -> dict[str, Any]:
    return load_json("workshop.requirements.json")


def golden_acceptance(ids: tuple[str, ...] = ACCEPTANCE_IDS) -> list[dict[str, Any]]:
    by_id = {s["id"]: s for s in load_json("workshop.scenarios.json")}
    return [copy.deepcopy(by_id[i]) for i in ids]


def understand_out(
    *,
    questions: list[dict[str, Any]] | None = None,
    unsupported: list[dict[str, Any]] | None = None,
    message: str = "یک ربات ثبت‌نام کارگاه با لیست انتظار می‌سازم.",
) -> dict[str, Any]:
    req = golden_requirements()
    req["open_questions"] = questions or []
    req["unsupported"] = unsupported or []
    return {"requirements": req, "message": message}


def blocking_question(qid: str = "Q1", text: str = "آیا مشتری‌ها هنگام ثبت‌نام شماره تماس وارد کنند؟") -> dict:
    return {
        "id": qid,
        "text": text,
        "why": "changes form fields",
        "severity": "blocking",
        "options": ["بله", "خیر"],
    }


def sample_out() -> dict[str, Any]:
    return {
        "records": [
            {
                "ref": "s1",
                "collection": "workshop",
                "values": [
                    {"key": "title", "value": "کارگاه سفالگری"},
                    {"key": "description", "value": "آشنایی با چرخ سفال"},
                    {"key": "teacher", "value": "مریم"},
                    {"key": "starts_at", "value": "+72h"},
                    {"key": "price", "value": "900000"},
                ],
            },
            {
                "ref": "s2",
                "collection": "workshop",
                "values": [
                    {"key": "title", "value": "کارگاه عکاسی"},
                    {"key": "description", "value": "نور و ترکیب‌بندی"},
                    {"key": "teacher", "value": "علی"},
                    {"key": "starts_at", "value": "+5d"},
                ],
            },
            {"ref": "bad", "collection": "nope", "values": []},  # dropped by validation
        ]
    }


def set_spec(spec: dict[str, Any] | None = None) -> ToolCall:
    return ToolCall("set_spec", {"spec": spec if spec is not None else golden_spec()})


def finish(summary: str = "done") -> ToolCall:
    return ToolCall("finish", {"summary": summary})


def patch(*ops: dict[str, Any]) -> ToolCall:
    return ToolCall("apply_spec_patch", {"ops": list(ops)})


def build_ok() -> list[FakeTurn]:
    return [[set_spec()], [finish()]]


def happy_scripts(**overrides: Any) -> dict[str, Any]:
    structured: dict[str, list[Any]] = {
        "understand": [understand_out()],
        "testgen": [{"scenarios": golden_acceptance()}],
        "sample_data": [sample_out()],
    }
    loops: dict[str, list[list[FakeTurn]]] = {"build": [build_ok()]}
    structured.update(overrides.pop("structured", {}))
    loops.update(overrides.pop("loops", {}))
    return {"structured": structured, "loops": loops, **overrides}


@dataclass
class Harness:
    repo: InMemoryAgentRepository
    llm: FakeLLM
    orch: Orchestrator
    bot_id: str
    base_id: str | None = None  # modify harness: the seeded active revision

    async def start(self, message: str = GOLDEN_PROMPT) -> RunRecord:
        record = await self.orch.start_create(self.bot_id, message)
        await self.orch.advance(record.id)
        return await self.repo.load_run(record.id)

    async def start_change(self, message: str = "ظرفیت هر کارگاه را ۱۲ نفر کن.") -> RunRecord:
        record = await self.orch.start_modify(self.bot_id, message)
        await self.orch.advance(record.id)
        return await self.repo.load_run(record.id)

    async def answer(self, run_id: str, message: str) -> RunRecord:
        await self.orch.post_message(run_id, message)
        await self.orch.advance(run_id)
        return await self.repo.load_run(run_id)

    def events(self, run_id: str) -> list[EventEnvelope]:
        return self.repo.events_for(run_id)

    def types(self, run_id: str) -> list[str]:
        return [e.type for e in self.events(run_id)]

    def of_type(self, run_id: str, type_: str) -> list[dict[str, Any]]:
        return [e.payload for e in self.events(run_id) if e.type == type_]

    def tool_results(self, name: str) -> list[Any]:
        return [r.content for r in self.llm.tool_results if r.name == name]


def harness(limits: Limits | None = None, usage_per_call: Usage | None = None, **scripts: Any) -> Harness:
    repo = InMemoryAgentRepository()
    llm = FakeLLM(usage_per_call=usage_per_call, **happy_scripts(**scripts))
    orch = Orchestrator(repo, llm, limits=limits or Limits(), bus=EventBus())
    return Harness(repo, llm, orch, repo.add_bot("کارگاه‌ها"))


# --------------------------------------------------------------------------- modify (WP7)

MOD_CAPACITY = "ظرفیت هر کارگاه را ۱۲ نفر کن."
MOD_DEADLINE = "لغو ثبت‌نام فقط تا ۲ ساعت قبل از شروع کارگاه ممکن باشد."
CAPACITY_VALUE = ["capabilities", "book_workshop", "capacity", "value"]
DEADLINE_HOURS = ["capabilities", "book_workshop", "cancellation", "deadline_hours"]


def all_golden_scenarios() -> list[dict[str, Any]]:
    return load_json("workshop.scenarios.json")


def golden_sample() -> list[SeedRecord]:
    return [SeedRecord.model_validate(r) for r in sample_out()["records"][:2]]


def triage_out(intent: str = "change", reply: str = "این تغییر را آماده می‌کنم.") -> dict[str, Any]:
    return {"intent": intent, "reply": reply}


def change_out(
    *,
    changed: list[dict[str, Any]] | None = None,
    added: list[dict[str, Any]] | None = None,
    removed: list[str] | None = None,
    questions: list[dict[str, Any]] | None = None,
    unsupported: list[dict[str, Any]] | None = None,
    message: str = "ربات را مطابق درخواست تغییر می‌دهم.",
) -> dict[str, Any]:
    return {
        "delta": {
            "added": added or [],
            "changed": changed or [],
            "removed": removed or [],
            "unsupported": unsupported or [],
            "open_questions": questions or [],
        },
        "message": message,
    }


def capacity_requirement(n: int, rid: str = "R2") -> dict[str, Any]:
    return {"id": rid, "kind": "rule", "statement": f"ظرفیت هر کارگاه {n} نفر است.", "status": "confirmed"}


def deadline_requirement(rid: str = "R1") -> dict[str, Any]:
    return {
        "id": rid,
        "kind": "rule",
        "statement": "لغو ثبت‌نام فقط تا ۲ ساعت قبل از شروع کارگاه ممکن است.",
        "status": "confirmed",
    }


def workshop_seed(ref: str = "w1", starts_at: str = "+48h") -> dict[str, Any]:
    return {
        "ref": ref,
        "collection": "workshop",
        "values": [
            {"key": "title", "value": "کارگاه سفال"},
            {"key": "description", "value": "آشنایی با چرخ سفال"},
            {"key": "teacher", "value": "مریم"},
            {"key": "starts_at", "value": starts_at},
        ],
    }


def capacity_scenario(n: int, rid: str = "R2", sid: str = "acc_capacity_n") -> dict[str, Any]:
    steps = [
        {"do": "book", "actor": f"u{i}", "capability": "book_workshop", "item": "w1", "expect": "confirmed"}
        for i in range(1, n + 1)
    ]
    steps.append(
        {
            "do": "book",
            "actor": f"u{n + 1}",
            "capability": "book_workshop",
            "item": "w1",
            "expect": "waitlisted",
        }
    )
    steps.append(
        {"do": "expect_counts", "capability": "book_workshop", "item": "w1", "confirmed": n, "waitlisted": 1}
    )
    return {
        "id": sid,
        "title": f"ظرفیت واقعی {n} نفر: {n} نفر تأیید و نفر بعدی در لیست انتظار",
        "source": "acceptance",
        "requirement_ids": [rid],
        "capability_keys": ["book_workshop"],
        "capacity_override": None,
        "seed": [workshop_seed()],
        "steps": steps,
    }


def deadline_scenarios(rid: str = "R8") -> list[dict[str, Any]]:
    late = {
        "id": "acc_cancel_too_late",
        "title": "یک ساعت مانده به شروع، علی نمی‌تواند لغو کند",
        "source": "acceptance",
        "requirement_ids": [rid],
        "capability_keys": ["book_workshop"],
        "capacity_override": 2,
        "seed": [workshop_seed(starts_at="+3h")],
        "steps": [
            {
                "do": "book",
                "actor": "ali",
                "capability": "book_workshop",
                "item": "w1",
                "expect": "confirmed",
            },
            {"do": "advance_time", "hours": 2},
            {
                "do": "cancel",
                "actor": "ali",
                "capability": "book_workshop",
                "item": "w1",
                "expect": "rejected",
                "reason": "cancel_deadline_passed",
            },
            {
                "do": "expect_booking",
                "actor": "ali",
                "capability": "book_workshop",
                "item": "w1",
                "expect": "confirmed",
            },
        ],
    }
    early = {
        "id": "acc_cancel_in_time",
        "title": "سه ساعت مانده به شروع، سارا لغو می‌کند",
        "source": "acceptance",
        "requirement_ids": [rid],
        "capability_keys": ["book_workshop"],
        "capacity_override": 2,
        "seed": [workshop_seed(starts_at="+4h")],
        "steps": [
            {
                "do": "book",
                "actor": "sara",
                "capability": "book_workshop",
                "item": "w1",
                "expect": "confirmed",
            },
            {"do": "advance_time", "hours": 1},
            {
                "do": "cancel",
                "actor": "sara",
                "capability": "book_workshop",
                "item": "w1",
                "expect": "cancelled",
            },
        ],
    }
    return [late, early]


def supersede(sid: str, reason: str = "ظرفیت از ۱۰ به ۱۲ تغییر کرد.") -> ToolCall:
    return ToolCall("supersede_scenario", {"scenario_id": sid, "reason": reason})


def run_tests() -> ToolCall:
    return ToolCall("run_tests", {})


def capacity_scripts(n: int = 12) -> dict[str, Any]:
    """The golden modification 1, scripted: R2 changes; the 10-seat scenario is superseded."""
    return {
        "structured": {
            "triage": [triage_out()],
            "understand": [change_out(changed=[capacity_requirement(n)])],
            "testgen": [{"scenarios": [capacity_scenario(n)]}],
        },
        "loops": {
            "build": [[[patch({"op": "set", "path": CAPACITY_VALUE, "value": n})], [finish()]]],
            "repair": [[[supersede("golden_capacity_10_real")], [run_tests()], [finish()]]],
        },
    }


def deadline_scripts(rid: str = "R8") -> dict[str, Any]:
    """The golden modification 2, scripted: a new requirement; nothing superseded."""
    return {
        "structured": {
            "triage": [triage_out()],
            "understand": [change_out(added=[deadline_requirement("R99")])],
            "testgen": [{"scenarios": deadline_scenarios(rid)}],
        },
        "loops": {"build": [[[patch({"op": "set", "path": DEADLINE_HOURS, "value": 2})], [finish()]]]},
    }


def modify_harness(
    scripts: dict[str, Any] | None = None,
    *,
    live: LiveStats | None = None,
    limits: Limits | None = None,
    scenarios: list[dict[str, Any]] | None = None,
) -> Harness:
    """A bot whose active revision is the golden workshop (spec, requirements, all 9 scenarios)."""
    repo = InMemoryAgentRepository()
    scripts = scripts if scripts is not None else capacity_scripts()
    llm = FakeLLM(structured=scripts.get("structured"), loops=scripts.get("loops"))
    orch = Orchestrator(repo, llm, limits=limits or Limits(), bus=EventBus())
    bot_id = repo.add_bot("کارگاه‌ها")
    base_id = repo.add_revision(
        bot_id,
        BotSpec.model_validate(golden_spec()),
        requirements=Requirements.model_validate(golden_requirements()),
        scenarios=[Scenario.model_validate(s) for s in (scenarios or all_golden_scenarios())],
        sample_data=golden_sample(),
    )
    if live is not None:
        repo.live[bot_id] = live
    return Harness(repo, llm, orch, bot_id, base_id)
