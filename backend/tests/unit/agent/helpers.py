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
from app.agent.repository import InMemoryAgentRepository, RunRecord

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

    async def start(self, message: str = GOLDEN_PROMPT) -> RunRecord:
        record = await self.orch.start_create(self.bot_id, message)
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
