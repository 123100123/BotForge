"""Offline smoke tests of the live scripts: the same code paths with FakeLLM / a stub SDK client."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from app.agent.llm import AnthropicLLM, FakeLLM
from tests.unit.agent.helpers import (
    CAPACITY_VALUE,
    blocking_question,
    capacity_scripts,
    deadline_scripts,
    finish,
    golden_spec,
    happy_scripts,
    patch,
    understand_out,
)
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


async def test_eval_golden_modify_runs_both_modifications_with_a_scripted_model() -> None:
    script = load_script("eval_golden")
    capacity, deadline = capacity_scripts(12), deadline_scripts("R8")
    structured = {
        k: capacity["structured"].get(k, []) + deadline["structured"].get(k, [])
        for k in ("triage", "understand", "testgen")
    }
    loops = {
        "build": capacity["loops"]["build"] + deadline["loops"]["build"],
        "repair": capacity["loops"]["repair"],
    }
    llm = FakeLLM(structured=structured, loops=loops)
    result = await script.one_modify_run(1, llm, verbose=False)  # type: ignore[arg-type]
    assert result["result"] == "PASS", result
    first, second = result["modifications"]
    assert first["superseded"][0]["id"] == "golden_capacity_10_real" and first["risk"] == "low"
    assert second["superseded"] == [] and second["new_scenarios"]
    assert result["revisions"] == 3 and result["output_tokens"] > 0


async def test_eval_golden_modify_fails_when_the_wrong_scenario_is_superseded() -> None:
    script = load_script("eval_golden")
    scripts = capacity_scripts(12)
    scripts["loops"]["build"] = [
        [
            [
                patch(
                    {"op": "set", "path": CAPACITY_VALUE, "value": 12},
                    {"op": "set", "path": ["bot", "name"], "value": "x"},
                )
            ],
            [finish()],
        ]
    ]
    llm = FakeLLM(**scripts)
    result = await script.one_modify_run(1, llm, verbose=False)  # type: ignore[arg-type]
    (only,) = result["modifications"][:1]
    assert only["checks"]["expected_change_only"] is False  # an unrelated change is caught
    assert result["result"] == "FAIL"


def test_eval_golden_exits_without_an_api_key(monkeypatch, capsys) -> None:
    script = load_script("eval_golden")
    monkeypatch.setattr(script, "api_key_available", lambda: False)
    monkeypatch.setattr(sys, "argv", ["eval_golden.py", "--modify"])
    import asyncio

    assert asyncio.run(script.main()) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


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
