"""AnthropicLLM request building and loop policy against a stub SDK client; FakeLLM semantics."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.agent.llm import (
    FALLBACK_BETA,
    NUDGE_TEXT,
    AnthropicLLM,
    FakeLLM,
    LLMError,
    ToolCall,
    ToolDef,
    ToolOutcome,
    Usage,
    cost_of,
)


def usage(i: int = 100, o: int = 20, read: int = 0, write: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=i, output_tokens=o, cache_read_input_tokens=read, cache_creation_input_tokens=write
    )


def message(content: list[Any], stop: str = "end_turn", model: str = "claude-opus-5-5", **kw: Any) -> Any:
    return SimpleNamespace(
        content=content,
        stop_reason=stop,
        stop_details=kw.get("stop_details"),
        model=model,
        usage=kw.get("usage", usage()),
        to_json=lambda: "{}",
    )


def text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def thinking() -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking="", signature="sig-1")


def tool_use(i: str, name: str, inp: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=i, name=name, input=inp)


class StubClient:
    """Mimics ``client.beta.messages.stream(**params)`` -> async CM with ``get_final_message``."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @asynccontextmanager
    async def _stream(self, **params: Any):  # type: ignore[no-untyped-def]
        # Snapshot the messages list: the loop appends to its history after the call.
        self.requests.append({**params, "messages": list(params["messages"])})
        response = self.responses.pop(0)

        async def final() -> Any:
            return response

        yield SimpleNamespace(get_final_message=final)


class Answer(BaseModel):
    answer: str
    n: int


TOOLS = [
    ToolDef("set_spec", "write", {"type": "object", "properties": {}, "additionalProperties": False}),
    ToolDef(
        "finish", "done", {"type": "object", "properties": {}, "additionalProperties": False}, strict=True
    ),
]


def llm(responses: list[Any]) -> tuple[AnthropicLLM, StubClient]:
    client = StubClient(responses)
    return AnthropicLLM(
        client, strong_model="claude-opus-5-5", fast_model="claude-haiku-4-5", log_bodies=False
    ), client


async def test_structured_request_shape_and_parse() -> None:
    model, client = llm(
        [message([thinking(), text('{"answer": "سلام", "n": 2}')], usage=usage(50, 10, 400, 30))]
    )
    out, used = await model.structured(
        task="understand", system="SYS", messages=[{"role": "user", "content": "hi"}], schema=Answer
    )
    assert out == Answer(answer="سلام", n=2)
    (req,) = client.requests
    assert req["model"] == "claude-opus-5-5"
    assert req["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert req["thinking"] == {"type": "adaptive"}
    assert req["output_config"]["effort"] == "medium"
    fmt = req["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert req["betas"] == [FALLBACK_BETA] and req["fallbacks"] == "default"
    assert "tool_choice" not in req
    assert used.input_tokens == 50 and used.cached_tokens == 400 and used.cache_write_tokens == 30
    assert used.cost_usd == cost_of("claude-opus-5-5", used) > 0


async def test_fast_tier_sends_no_effort_thinking_or_fallback() -> None:
    model, client = llm([message([text('{"answer": "x", "n": 1}')], model="claude-haiku-4-5")])
    await model.structured(task="sample_data", system="S", messages=[], schema=Answer, tier="fast")
    (req,) = client.requests
    assert req["model"] == "claude-haiku-4-5"
    assert "thinking" not in req and "betas" not in req and "fallbacks" not in req
    assert set(req["output_config"]) == {"format"}


@pytest.mark.parametrize(
    ("stop", "code"), [("refusal", "refusal"), ("max_tokens", "max_tokens"), ("end_turn", "invalid_output")]
)
async def test_structured_failures_raise_llm_error(stop: str, code: str) -> None:
    details = SimpleNamespace(category="cyber") if stop == "refusal" else None
    model, _ = llm([message([text("not json")], stop=stop, stop_details=details)])
    with pytest.raises(LLMError) as exc:
        await model.structured(task="testgen", system="S", messages=[], schema=Answer)
    assert exc.value.code == code
    assert exc.value.usage.input_tokens == 100  # usage is still accounted


async def test_tool_loop_passes_assistant_turns_back_unchanged() -> None:
    turn1 = [thinking(), text("writing"), tool_use("t1", "set_spec", {"spec": {}})]
    turn2 = [thinking(), tool_use("t2", "finish", {})]
    model, client = llm([message(turn1, stop="tool_use"), message(turn2, stop="tool_use")])
    seen: list[str] = []

    async def handler(name: str, args: dict[str, Any]) -> ToolOutcome:
        seen.append(name)
        return ToolOutcome({"ok": True}, stop=name == "finish")

    result = await model.tool_loop(
        task="repair",
        system="S",
        messages=[{"role": "user", "content": "go"}],
        tools=TOOLS,
        handler=handler,
        max_tool_calls=5,
    )
    assert result.stop_reason == "finished" and result.tool_calls == 2 and seen == ["set_spec", "finish"]
    first, second = client.requests
    assert first["tools"][1]["strict"] is True and "strict" not in first["tools"][0]
    assert first["output_config"] == {"effort": "high"}
    assert first["cache_control"] == {"type": "ephemeral"}
    history = second["messages"]
    assert history[1] == {"role": "assistant", "content": turn1}  # same blocks, thinking included
    assert history[1]["content"][0] is turn1[0]
    results = history[2]["content"]
    assert results == [
        {"type": "tool_result", "tool_use_id": "t1", "content": '{"ok":true}', "is_error": False}
    ]
    assert result.usage.llm_calls == 2 and result.usage.tool_calls == 2


async def test_tool_loop_stop_reasons() -> None:
    async def handler(name: str, args: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome({"ok": True})

    for stop in ("refusal", "max_tokens"):
        model, _ = llm([message([tool_use("t", "set_spec", {})], stop=stop)])
        result = await model.tool_loop(
            task="build", system="S", messages=[], tools=TOOLS, handler=handler, max_tool_calls=5
        )
        assert result.stop_reason == stop and result.tool_calls == 0

    model, client = llm([message([text("ok")]), message([text("really done")])])
    result = await model.tool_loop(
        task="build", system="S", messages=[], tools=TOOLS, handler=handler, max_tool_calls=5
    )
    assert result.stop_reason == "end_turn" and result.text == "really done"
    assert client.requests[1]["messages"][-1] == {"role": "user", "content": NUDGE_TEXT}

    calls = [message([tool_use(f"t{i}", "set_spec", {})], stop="tool_use") for i in range(5)]
    model, _ = llm(calls)
    result = await model.tool_loop(
        task="build", system="S", messages=[], tools=TOOLS, handler=handler, max_tool_calls=3
    )
    assert result.stop_reason == "tool_limit" and result.tool_calls == 3

    model, _ = llm([message([tool_use("t", "set_spec", {})], stop="tool_use")] * 3)
    result = await model.tool_loop(
        task="build",
        system="S",
        messages=[],
        tools=TOOLS,
        handler=handler,
        max_tool_calls=9,
        on_usage=lambda u: False,
    )
    assert result.stop_reason == "budget"


async def test_fake_llm_scripts_limits_and_handler_errors() -> None:
    fake = FakeLLM(
        structured={"t": [{"answer": "a", "n": 1}, {"answer": 5}]},
        loops={"build": [[[ToolCall("boom"), ToolCall("finish")]]]},
        usage_per_call=Usage(input_tokens=7, output_tokens=1, llm_calls=1),
    )
    out, used = await fake.structured(task="t", system="S", messages=[], schema=Answer)
    assert out == Answer(answer="a", n=1) and used.input_tokens == 7
    with pytest.raises(LLMError):
        await fake.structured(task="t", system="S", messages=[], schema=Answer)
    with pytest.raises(AssertionError):
        await fake.structured(task="t", system="S", messages=[], schema=Answer)

    async def handler(name: str, args: dict[str, Any]) -> ToolOutcome:
        if name == "boom":
            raise ValueError("bad")
        return ToolOutcome({"ok": True}, stop=True)

    tools = [ToolDef("boom", "", {}), ToolDef("finish", "", {})]
    result = await fake.tool_loop(
        task="build", system="S", messages=[], tools=tools, handler=handler, max_tool_calls=5
    )
    assert result.stop_reason == "finished" and result.tool_calls == 2
    assert fake.tool_results[0].is_error and "bad" in json.dumps(fake.tool_results[0].content)


def test_usage_addition_and_budget_input() -> None:
    total = Usage(
        input_tokens=1, output_tokens=2, cached_tokens=3, cache_write_tokens=4, tool_calls=1
    ) + Usage(input_tokens=10, cost_usd=0.5)
    assert total.input_tokens == 11 and total.billable_input == 15 and total.cost_usd == 0.5
    assert cost_of("unknown-model", total) == 0.0
