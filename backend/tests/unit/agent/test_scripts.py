"""Offline smoke tests of the live scripts: the same code paths with FakeLLM / a stub SDK client."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from app.agent.llm import AnthropicLLM, FakeLLM
from tests.unit.agent.helpers import blocking_question, golden_spec, happy_scripts, understand_out
from tests.unit.agent.test_llm import StubClient, message, text, tool_use

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"script_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_eval_golden_one_run_passes_with_a_scripted_model() -> None:
    script = load_script("eval_golden")
    llm = FakeLLM(
        **happy_scripts(
            structured={"understand": [understand_out(questions=[blocking_question()]), understand_out()]}
        )
    )
    result = await script.one_run(1, llm, verbose=False)  # type: ignore[arg-type]
    assert result["result"] == "PASS", result
    assert result["clarify_answers"] == 1 and result["checks"]["fixed_capacity_10"]
    assert "شماره تماس لازم نیست" in llm.calls[1].messages[0]["content"]


async def test_spike_modes_evaluate_the_returned_spec() -> None:
    script = load_script("spike_structured_output")
    import json

    stub = StubClient(
        [
            message([text(json.dumps(golden_spec(), ensure_ascii=False))]),
            message([tool_use("t1", "set_spec", {"spec": golden_spec()})], stop="tool_use"),
        ]
    )
    llm = AnthropicLLM(stub, strong_model="claude-opus-5-5", log_bodies=False)
    structured = await script.run_mode(llm, "structured")
    assert structured["valid"] is True and structured["capacity"]["value"] == 10
    assert stub.requests[0]["output_config"]["format"]["type"] == "json_schema"
    tool = await script.run_mode(llm, "tool")
    assert tool["valid"] is True and tool["tool_called"] is True
    assert stub.requests[1]["tools"][0]["name"] == "set_spec" and "strict" not in stub.requests[1]["tools"][0]
