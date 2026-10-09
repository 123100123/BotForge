"""Offline wire-level coverage of the Liara trust boundary. Never contacts a real provider."""

import asyncio
import json
import logging
import traceback
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.agent.llm import NUDGE_TEXT, LLMError, ToolDef, ToolOutcome
from app.agent.llm_liara import LiaraLLM
from app.config import Settings

SENTINEL = "test-secret-never-log-me"
URL = "https://ai.liara.ir/api/v1/682833f68c7347b1c1612d00"
STRONG = "google/gemini-3.8-flash"
FAST = "deepseek/deepseek-v4-flash"


class Answer(BaseModel):
    answer: str
    count: int


TOOLS = [
    ToolDef(
        "write",
        "write a value",
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    ),
    ToolDef("finish", "done", {"type": "object", "properties": {}, "additionalProperties": False}),
]


def completion(
    content: Any = '{"answer":"سلام","count":2}',
    *,
    calls: Any = None,
    finish: str = "stop",
    **message_fields: Any,
) -> dict[str, Any]:
    message = {"role": "assistant", "content": content, **message_fields}
    if calls is not None:
        message["tool_calls"] = calls
    return {
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def call(name: str, arguments: Any = "{}", *, call_id: str = "c1", **extra: Any) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}, **extra}


class Wire:
    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)


def model(responses: list[Any], **overrides: Any) -> tuple[LiaraLLM, Wire]:
    settings = Settings(_env_file=None, LIARA_API_KEY=SENTINEL, LIARA_BASE_URL=URL, **overrides)
    wire = Wire(responses)
    return LiaraLLM(settings=settings, transport=httpx.MockTransport(wire.handle)), wire


async def structured(llm: LiaraLLM, **kwargs: Any):
    return await llm.structured(
        task="understand",
        system="SYSTEM",
        messages=[{"role": "user", "content": "hi"}],
        schema=Answer,
        **kwargs,
    )


async def loop(llm: LiaraLLM, *, seen: list[Any] | None = None, handler: Any = None, **kwargs: Any):
    async def handle(name, args):
        if seen is not None:
            seen.append((name, args))
        return ToolOutcome({"ok": True}, stop=name == "finish")

    return await llm.tool_loop(
        task="build",
        system="SYSTEM",
        messages=[],
        tools=TOOLS,
        handler=handler or handle,
        max_tool_calls=kwargs.pop("max_tool_calls", 5),
        **kwargs,
    )


@pytest.mark.parametrize(("tier", "expected"), [("strong", STRONG), ("fast", FAST)])
async def test_structured_wire_shape_and_tiers(tier, expected):
    llm, wire = model([completion()])
    result, usage = await structured(llm, tier=tier)
    assert result == Answer(answer="سلام", count=2)
    assert usage.input_tokens == 100 and usage.output_tokens == 20 and usage.cost_usd == 0
    request = wire.requests[0]
    assert str(request.url) == URL + "/chat/completions"
    assert request.headers["authorization"] == "Bearer " + SENTINEL
    body = wire.bodies[0]
    assert body["model"] == expected and body["max_tokens"] == 32000 and body["stream"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert '"title": "Answer"' in body["messages"][0]["content"]
    assert SENTINEL not in json.dumps(body)


async def test_caching_reasoning_and_configured_prices():
    body = completion()
    body["usage"].update(
        prompt_tokens_details={"cached_tokens": 60}, completion_tokens_details={"reasoning_tokens": 15}
    )
    llm, _ = model(
        [body], LIARA_TOKEN_PRICES_JSON=json.dumps({STRONG: {"input": 2, "output": 10, "cache_read": 1}})
    )
    _, usage = await structured(llm)
    assert (usage.input_tokens, usage.cached_tokens, usage.output_tokens) == (40, 60, 20)
    assert usage.cost_usd == 0.00034 and usage.billable_input == 40


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 2},
        {"prompt_tokens": -1, "completion_tokens": 2},
        {"prompt_tokens": "10", "completion_tokens": 2},
        {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 99},
        {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 11}},
        {"prompt_tokens": 10, "completion_tokens": 2, "completion_tokens_details": {"reasoning_tokens": 3}},
        {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": "invalid"},
        {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "completion_tokens_details": {"reasoning_tokens": False},
        },
    ],
)
async def test_missing_or_invalid_usage_never_dispatches(usage):
    response = completion(calls=[call("finish")], finish="tool_calls")
    response["usage"] = usage
    llm, _ = model([response])
    seen = []
    with pytest.raises(LLMError, match="invalid_output"):
        await loop(llm, seen=seen)
    assert seen == []


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (completion("not JSON " + SENTINEL), "invalid_output"),
        (completion(json.dumps({"answer": SENTINEL, "count": "bad"})), "invalid_output"),
        (completion("{}", finish="length"), "max_tokens"),
        (completion("{}", refusal=SENTINEL), "refusal"),
        (completion("{}", finish="content_filter"), "refusal"),
        (completion('{"answer":"a","count":NaN}'), "invalid_output"),
    ],
)
async def test_structured_failures_keep_usage_and_safe_errors(body, code, caplog):
    llm, _ = model([body], LOG_LLM_BODIES=True)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMError) as caught:
        await structured(llm)
    error = caught.value
    assert error.code == code and error.usage.input_tokens == 100
    assert error.__cause__ is None and error.__context__ is None
    assert SENTINEL not in "".join(traceback.format_exception(error)) + caplog.text


async def test_single_response_format_fallback():
    rejected = httpx.Response(
        400,
        json={"error": {"param": "response_format", "code": "unsupported_parameter", "message": SENTINEL}},
    )
    llm, wire = model([rejected, completion()])
    await structured(llm)
    assert "response_format" in wire.bodies[0] and "response_format" not in wire.bodies[1]
    assert wire.bodies[0]["messages"] == wire.bodies[1]["messages"]
    llm, wire = model([rejected, rejected])
    with pytest.raises(LLMError, match="api_error"):
        await structured(llm)
    assert len(wire.requests) == 2


@pytest.mark.parametrize(
    "error",
    [
        {"message": "Invalid schema " + SENTINEL},
        {"param": "other", "message": SENTINEL},
        {"param": "response_format", "code": "payment_required", "message": SENTINEL},
    ],
)
async def test_arbitrary_400_does_not_trigger_fallback(error):
    llm, wire = model([httpx.Response(400, json={"error": error})])
    with pytest.raises(LLMError, match="api_error"):
        await structured(llm)
    assert len(wire.requests) == 1


async def test_multiturn_tools_preserve_ids_reasoning_and_signatures():
    first = completion(
        None,
        calls=[call("write", '{"value":1}', extra_content={"google": {"thought_signature": "s"}})],
        finish="tool_calls",
        reasoning_content="thinking",
        reasoning_details=[{"text": "opaque"}],
    )
    llm, wire = model([first, completion(None, calls=[call("finish", call_id="c2")], finish="tool_calls")])
    seen = []
    result = await loop(llm, seen=seen)
    assert result.stop_reason == "finished" and result.tool_calls == 2
    assert result.usage.llm_calls == 2 and result.usage.input_tokens == 200
    assert seen == [("write", {"value": 1}), ("finish", {})]
    second = wire.bodies[1]["messages"]
    assert second[1] == first["choices"][0]["message"]
    assert second[2] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'}
    assert wire.bodies[0]["tools"][0]["function"]["parameters"] == TOOLS[0].input_schema


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("unknown", "{}"),
        ("write", "[]"),
        ("write", "null"),
        ("write", "bad JSON"),
        ("write", "{}"),
        ("write", '{"value":true}'),
        ("write", '{"value":1,"extra":2}'),
        ("write", '{"value":1,"value":2}'),
        ("write", '{"value":NaN}'),
        ("write", {"value": 1}),
    ],
)
async def test_invalid_tool_arguments_are_not_executed_and_consume_attempt(name, args):
    llm, wire = model(
        [
            completion(None, calls=[call(name, args)], finish="tool_calls"),
            completion(None, calls=[call("finish", call_id="c2")], finish="tool_calls"),
        ]
    )
    seen = []
    result = await loop(llm, seen=seen)
    assert result.tool_calls == 2 and seen == [("finish", {})]
    assert json.loads(wire.bodies[1]["messages"][-1]["content"])["ok"] is False


async def test_terminal_finish_stops_batch_and_limit_prevents_next_request():
    llm, _ = model(
        [
            completion(
                None, calls=[call("finish"), call("write", '{"value":5}', call_id="c2")], finish="tool_calls"
            )
        ]
    )
    seen = []
    result = await loop(llm, seen=seen)
    assert result.tool_calls == 1 and seen == [("finish", {})]
    llm, wire = model(
        [
            completion(
                None, calls=[call("write", "{}", call_id=f"c{i}") for i in range(50)], finish="tool_calls"
            )
        ]
    )
    result = await loop(llm, max_tool_calls=1)
    assert result.stop_reason == "tool_limit" and result.tool_calls == 1 and len(wire.requests) == 1
    llm, wire = model([])
    assert (await loop(llm, max_tool_calls=0)).stop_reason == "tool_limit"
    assert wire.requests == []


async def test_repeated_call_ids_do_not_replay_handler():
    llm, _ = model([completion(None, calls=[call("write", '{"value":1}')], finish="tool_calls")] * 2)
    seen = []
    with pytest.raises(LLMError) as caught:
        await loop(llm, seen=seen)
    assert len(seen) == 1 and caught.value.usage.tool_calls == 2 and caught.value.usage.llm_calls == 2


async def test_nudge_once_and_model_turns_bounded():
    llm, wire = model([completion("first"), completion("last")])
    result = await loop(llm)
    assert result.stop_reason == "end_turn" and result.text == "last"
    assert wire.bodies[1]["messages"][-1] == {"role": "user", "content": NUDGE_TEXT}
    responses = [completion("nudge")]
    responses += [
        completion(None, calls=[call("write", "{}", call_id=f"c{i}")], finish="tool_calls") for i in range(4)
    ]
    llm, wire = model(responses)
    result = await loop(llm, max_tool_calls=4)
    assert result.stop_reason == "tool_limit" and len(wire.requests) <= 6


async def test_budget_and_malformed_choices_are_charged_before_dispatch():
    llm, _ = model([completion(None, calls=[call("finish")], finish="tool_calls")])
    seen, charged = [], []
    result = await loop(llm, seen=seen, on_usage=lambda u: charged.append(u) or False)
    assert result.stop_reason == "budget" and not seen and charged[0].input_tokens == 100
    body = completion()
    body["choices"] = []
    llm, _ = model([body])
    with pytest.raises(LLMError) as caught:
        await loop(llm, on_usage=lambda u: charged.append(u) or True)
    assert caught.value.usage.input_tokens == 100 and len(charged) == 2


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_explicit_transient_errors_only_are_retried(status, monkeypatch):
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("app.agent.llm_openai_compatible.asyncio.sleep", sleep)
    llm, wire = model([httpx.Response(status, text=SENTINEL)] * 2 + [completion()])
    await structured(llm)
    assert len(wire.requests) == 3 and delays == [0.5, 1]
    assert wire.bodies[0] == wire.bodies[1] == wire.bodies[2]
    llm, wire = model([httpx.Response(status, text=SENTINEL)] * 3)
    with pytest.raises(LLMError):
        await structured(llm)
    assert len(wire.requests) == 3


@pytest.mark.parametrize(
    "response",
    [httpx.Response(s, text=SENTINEL) for s in [301, 302, 400, 401, 402, 403, 404, 422]]
    + [httpx.ReadTimeout(SENTINEL), httpx.ConnectError(SENTINEL), RuntimeError(SENTINEL)],
)
async def test_no_retry_or_raw_exception_leak(response, caplog):
    llm, wire = model([response])
    with pytest.raises(LLMError) as caught:
        await structured(llm)
    assert len(wire.requests) == 1
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert SENTINEL not in "".join(traceback.format_exception(caught.value)) + caplog.text


async def test_late_failure_keeps_cumulative_usage_without_replaying_tools():
    llm, wire = model(
        [
            completion(None, calls=[call("write", '{"value":1}')], finish="tool_calls"),
            httpx.Response(402, text=SENTINEL),
        ]
    )
    seen = []
    with pytest.raises(LLMError) as caught:
        await loop(llm, seen=seen)
    assert len(seen) == 1 and len(wire.requests) == 2
    assert caught.value.usage.input_tokens == 100 and caught.value.usage.tool_calls == 1


async def test_handler_exception_safe_and_cancellation_propagates(caplog):
    async def bad(name, args):
        raise RuntimeError(SENTINEL)

    llm, wire = model(
        [
            completion(None, calls=[call("write", '{"value":1}')], finish="tool_calls"),
            completion(None, calls=[call("finish", call_id="c2")], finish="tool_calls"),
        ]
    )
    await loop(llm, handler=bad, max_tool_calls=2)
    assert SENTINEL not in json.dumps(wire.bodies) + caplog.text
    llm, _ = model([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await structured(llm)


async def test_wall_clock_timeout_and_client_cleanup():
    class Transport(httpx.AsyncBaseTransport):
        closed = False
        calls = 0

        async def handle_async_request(self, request):
            self.calls += 1
            await asyncio.sleep(1)
            return httpx.Response(200, json=completion())

        async def aclose(self):
            self.closed = True

    transport = Transport()
    settings = Settings(
        _env_file=None, LIARA_API_KEY=SENTINEL, LIARA_BASE_URL=URL, LIARA_TIMEOUT_SECONDS=0.01
    )
    llm = LiaraLLM(settings=settings, transport=transport)
    with pytest.raises(LLMError, match="api_error"):
        await structured(llm)
    assert transport.closed and transport.calls == 1


async def test_cancellation_closes_client():
    class Transport(httpx.AsyncBaseTransport):
        closed = False

        async def handle_async_request(self, request):
            raise asyncio.CancelledError()

        async def aclose(self):
            self.closed = True

    transport = Transport()
    settings = Settings(_env_file=None, LIARA_API_KEY=SENTINEL, LIARA_BASE_URL=URL)
    llm = LiaraLLM(settings=settings, transport=transport)
    with pytest.raises(asyncio.CancelledError):
        await structured(llm)
    assert transport.closed


@pytest.mark.parametrize("status", [400, 503])
async def test_account_for_usage_on_fallback_and_retry_attempts(status, monkeypatch):
    async def sleep(delay):
        return None

    monkeypatch.setattr("app.agent.llm_openai_compatible.asyncio.sleep", sleep)
    rejected = {
        "error": {"param": "response_format", "code": "unsupported_parameter"},
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    llm, _ = model([httpx.Response(status, json=rejected), completion()])
    _, usage = await structured(llm)
    assert usage.input_tokens == 107 and usage.output_tokens == 23 and usage.llm_calls == 2
    llm, _ = model([httpx.Response(status, json=rejected), httpx.Response(402, text=SENTINEL)])
    with pytest.raises(LLMError) as caught:
        await structured(llm)
    assert caught.value.usage.input_tokens == 7 and caught.value.usage.llm_calls == 1


async def test_retry_usage_budget_stops_before_next_attempt():
    llm, wire = model([httpx.Response(503, json={"usage": {"prompt_tokens": 7, "completion_tokens": 3}})])
    charged, seen = [], []
    result = await loop(llm, seen=seen, on_usage=lambda u: charged.append(u) or False)
    assert result.stop_reason == "budget" and len(wire.requests) == 1 and not seen
    assert charged[0].input_tokens == result.usage.input_tokens == 7


async def test_invalid_usage_on_error_prevents_retry_and_preserves_previous_usage():
    llm, wire = model(
        [
            completion(None, calls=[call("write", '{"value":1}')], finish="tool_calls"),
            httpx.Response(503, json={"usage": {"prompt_tokens": True, "completion_tokens": 3}}),
        ]
    )
    with pytest.raises(LLMError) as caught:
        await loop(llm)
    assert caught.value.code == "invalid_output" and caught.value.usage.input_tokens == 100
    assert len(wire.requests) == 2


@pytest.mark.parametrize("bad_call", [call("write", '{"value":2}'), {"id": "c2"}, None])
async def test_entire_tool_batch_envelope_validated_before_dispatch(bad_call):
    llm, _ = model([completion(None, calls=[call("write", '{"value":1}'), bad_call], finish="tool_calls")])
    seen = []
    with pytest.raises(LLMError) as caught:
        await loop(llm, seen=seen)
    assert seen == [] and caught.value.usage.tool_calls == 1 and caught.value.usage.input_tokens == 100


async def test_overflow_float_in_free_form_argument_is_rejected():
    llm, _ = model([completion(None, calls=[call("write", '{"value":1e999}')], finish="tool_calls")])
    seen = []

    async def handler(name, args):
        seen.append(args)
        return ToolOutcome({"ok": True})

    result = await llm.tool_loop(
        task="build",
        system="s",
        messages=[],
        tools=[ToolDef("write", "", {"type": "object"})],
        handler=handler,
        max_tool_calls=1,
    )
    assert result.stop_reason == "tool_limit" and not seen


async def test_anthropic_text_and_tool_history_translation():
    llm, wire = model([completion()])
    await llm.structured(
        task="understand",
        system="s",
        schema=Answer,
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "prior", "name": "read", "input": {}}],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "prior", "content": "ok"}]},
        ],
    )
    history = wire.bodies[0]["messages"]
    assert history[1] == {"role": "user", "content": "hi"}
    assert history[2]["tool_calls"] == [call("read", call_id="prior")]
    assert history[3] == {"role": "tool", "tool_call_id": "prior", "content": "ok"}
