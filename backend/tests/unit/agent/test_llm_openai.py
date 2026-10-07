"""OpenAICompatLLM against httpx.MockTransport (no network): loop and structured semantics, the
retry policy, the endpoint chain (failover, cool-down, ordering), the factory, and secret hygiene."""

import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.agent.llm import (
    LIMIT_TEXT,
    NUDGE_TEXT,
    PROVIDER_OWNER_MESSAGES,
    AnthropicLLM,
    LLMError,
    ToolDef,
    ToolOutcome,
    UnavailableLLM,
    make_llm,
)
from app.agent.llm_openai import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_OPENAI_MODEL,
    Endpoint,
    OpenAICompatLLM,
    endpoints_from_settings,
)
from app.config import Settings

KEY = "sk-test-SECRET-key-123"
KEY_A = "gemini-key-A-secret"
KEY_B = "gemini-key-B-secret"
GW = "gw.test"


def completion(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish: str = "stop",
    prompt: int = 100,
    out: int = 20,
    cached: int = 0,
) -> tuple[int, dict[str, Any]]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return 200, {
        "id": "chatcmpl-1",
        "model": "served-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": out,
            "prompt_tokens_details": {"cached_tokens": cached},
        },
    }


def call(call_id: str, name: str, args: Any) -> dict[str, Any]:
    raw = args if isinstance(args, str) else json.dumps(args)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}


def error(status: int, code: str, *, retryable: bool | None = None, message: str = "x") -> tuple[int, dict]:
    err: dict[str, Any] = {"code": code, "message": message}
    if retryable is not None:
        err["retryable"] = retryable
    return status, {"error": err}


class Gateway:
    """Scripted responses per host, consumed in order; records every request."""

    def __init__(self, script: dict[str, list[Any]]) -> None:
        self.script = {host: list(items) for host, items in script.items()}
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.requests.append((host, json.loads(request.content), dict(request.headers)))
        item = self.script[host].pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body)

    def bodies(self, host: str = GW) -> list[dict[str, Any]]:
        return [b for h, b, _ in self.requests if h == host]

    def hosts(self) -> list[str]:
        return [h for h, _, _ in self.requests]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(
    script: dict[str, list[Any]] | list[Any], endpoints: list[Endpoint] | None = None, **kw: Any
) -> tuple[OpenAICompatLLM, Gateway, list[float]]:
    gateway = Gateway(script if isinstance(script, dict) else {GW: script})
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    chain = endpoints or [Endpoint("LLM", f"https://{GW}/v1", KEY, DEFAULT_OPENAI_MODEL)]
    client = httpx.AsyncClient(transport=httpx.MockTransport(gateway.handler))
    return OpenAICompatLLM(endpoints=chain, http_client=client, sleep=sleep, **kw), gateway, sleeps


def chain() -> list[Endpoint]:
    return [
        Endpoint("LLM_1", "https://a.test/v1", KEY_A, "gemini-a"),
        Endpoint("LLM_2", "https://b.test/v1", KEY_B, "gemini-b"),
        Endpoint("LLM", f"https://{GW}/v1", KEY, DEFAULT_OPENAI_MODEL),
    ]


class Answer(BaseModel):
    answer: str
    n: int


TOOLS = [
    ToolDef("set_spec", "write the spec", {"type": "object", "properties": {"a": {"type": "integer"}}}),
    ToolDef("validate_spec", "validate", {"type": "object", "properties": {}}),
    ToolDef("finish", "done", {"type": "object", "properties": {}}, strict=True),
]


def recorder() -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    seen: list[tuple[str, dict[str, Any]]] = []

    async def handler(name: str, args: dict[str, Any]) -> ToolOutcome:
        seen.append((name, args))
        return ToolOutcome({"ok": True}, stop=name == "finish")

    return seen, handler


async def loop(llm: OpenAICompatLLM, handler: Any, max_tool_calls: int = 10, **kw: Any) -> Any:
    return await llm.tool_loop(
        task="build",
        system="SYS",
        messages=[{"role": "user", "content": "go"}],
        tools=TOOLS,
        handler=handler,
        max_tool_calls=max_tool_calls,
        **kw,
    )


# --------------------------------------------------------------------------- tool loop


async def test_tool_loop_runs_two_calls_then_finish_with_openai_history() -> None:
    turn1 = [call("c1", "set_spec", {"a": 1}), call("c2", "validate_spec", {})]
    llm, gw, _ = make(
        [
            completion("writing", turn1, finish="tool_calls"),
            completion(None, [call("c3", "finish", {})], "tool_calls"),
        ]
    )
    seen, handler = recorder()
    result = await loop(llm, handler)
    assert result.stop_reason == "finished" and result.tool_calls == 3
    assert seen == [("set_spec", {"a": 1}), ("validate_spec", {}), ("finish", {})]
    first, second = gw.bodies()
    assert first["model"] == DEFAULT_OPENAI_MODEL and first["tool_choice"] == "auto"
    assert first["messages"][0] == {"role": "system", "content": "SYS"}
    assert first["tools"][0] == {
        "type": "function",
        "function": {
            "name": "set_spec",
            "description": "write the spec",
            "parameters": TOOLS[0].input_schema,
        },
    }
    for absent in ("response_format", "thinking", "fallbacks", "cache_control", "betas"):
        assert absent not in first
    history = second["messages"]
    assert history[2] == {"role": "assistant", "content": "writing", "tool_calls": turn1}
    assert history[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok":true}'}
    assert history[4] == {"role": "tool", "tool_call_id": "c2", "content": '{"ok":true}'}
    assert result.usage.llm_calls == 2 and result.text == "writing"


async def test_tool_loop_limit_stops_without_running_extra_calls() -> None:
    turn = [call("c1", "set_spec", {"a": 1}), call("c2", "set_spec", {"a": 2})]
    llm, gw, _ = make([completion(None, turn, "tool_calls")])
    seen, handler = recorder()
    result = await loop(llm, handler, max_tool_calls=1)
    assert result.stop_reason == "tool_limit" and result.tool_calls == 1
    assert seen == [("set_spec", {"a": 1})] and len(gw.requests) == 1
    assert "not executed" in LIMIT_TEXT


async def test_invalid_tool_arguments_are_reported_back_not_executed() -> None:
    llm, gw, _ = make(
        [
            completion(None, [call("c1", "set_spec", '{"a": 1,')], "tool_calls"),
            completion(None, [call("c2", "finish", {})], "tool_calls"),
        ]
    )
    seen, handler = recorder()
    result = await loop(llm, handler)
    assert result.stop_reason == "finished" and seen == [("finish", {})]
    tool_message = gw.bodies()[1]["messages"][-1]
    assert tool_message["tool_call_id"] == "c1" and "invalid JSON" in tool_message["content"]
    assert gw.bodies()[1]["messages"][-2]["tool_calls"][0]["function"]["arguments"] == '{"a": 1,'


async def test_tool_loop_nudges_once_then_ends_and_maps_stop_reasons() -> None:
    llm, gw, _ = make([completion("thinking aloud"), completion("done")])
    _, handler = recorder()
    result = await loop(llm, handler)
    assert result.stop_reason == "end_turn" and result.text == "done"
    assert gw.bodies()[1]["messages"][-1] == {"role": "user", "content": NUDGE_TEXT}

    for finish, stop in (("length", "max_tokens"), ("content_filter", "refusal")):
        llm, _, _ = make([completion("partial", [call("c", "set_spec", "{")], finish)])
        result = await loop(llm, handler)
        assert result.stop_reason == stop and result.tool_calls == 0


async def test_usage_accumulates_and_the_hook_stops_the_loop_on_budget() -> None:
    llm, _, _ = make(
        [
            completion(None, [call("c1", "set_spec", {})], "tool_calls", prompt=1000, out=50, cached=400),
            completion(None, [call("c2", "set_spec", {})], "tool_calls", prompt=2000, out=60),
        ],
        price_input_per_m=1.0,
        price_output_per_m=10.0,
    )
    _, handler = recorder()
    seen: list[int] = []

    def hook(usage: Any) -> bool:
        seen.append(usage.input_tokens + usage.cached_tokens)
        return len(seen) < 2

    result = await loop(llm, handler, on_usage=hook)
    assert result.stop_reason == "budget" and seen == [1000, 2000]
    assert result.usage.input_tokens == 600 + 2000 and result.usage.cached_tokens == 400
    assert result.usage.output_tokens == 110 and result.usage.llm_calls == 2
    assert result.usage.cost_usd == pytest.approx((3000 * 1.0 + 110 * 10.0) / 1_000_000)


# --------------------------------------------------------------------------- structured


async def test_structured_uses_response_format_and_validates() -> None:
    llm, gw, _ = make([completion('```json\n{"answer": "سلام", "n": 2}\n```')])
    out, usage = await llm.structured(
        task="understand", system="SYS", messages=[{"role": "user", "content": "hi"}], schema=Answer
    )
    assert out == Answer(answer="سلام", n=2) and usage.input_tokens == 100
    (body,) = gw.bodies()
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is False
    assert fmt["json_schema"]["name"] == "Answer" and "answer" in fmt["json_schema"]["schema"]["properties"]
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}]


async def test_structured_retries_once_with_the_validation_error() -> None:
    llm, gw, _ = make([completion('{"answer": "x"}'), completion('{"answer": "x", "n": 3}')])
    out, usage = await llm.structured(task="testgen", system="S", messages=[], schema=Answer)
    assert out.n == 3 and usage.llm_calls == 2
    retry = gw.bodies()[1]["messages"]
    assert retry[-2] == {"role": "assistant", "content": '{"answer": "x"}'}
    assert "n" in retry[-1]["content"] and "not valid JSON" in retry[-1]["content"]


async def test_structured_invalid_twice_raises_invalid_output_with_usage() -> None:
    llm, _, _ = make([completion("no json"), completion("still none")])
    with pytest.raises(LLMError) as exc:
        await llm.structured(task="testgen", system="S", messages=[], schema=Answer)
    assert exc.value.code == "invalid_output" and exc.value.usage.llm_calls == 2


async def test_rejected_response_format_falls_back_to_a_forced_tool_call() -> None:
    llm, gw, _ = make(
        [
            error(400, "invalid_request_error", message="response_format json_schema is not supported"),
            completion(None, [call("c1", "Answer", {"answer": "ok", "n": 1})], "tool_calls"),
        ]
    )
    out, _ = await llm.structured(task="understand", system="S", messages=[], schema=Answer)
    assert out == Answer(answer="ok", n=1)
    first, second = gw.bodies()
    assert "response_format" in first and "response_format" not in second
    assert second["tool_choice"] == {"type": "function", "function": {"name": "Answer"}}
    assert second["tools"][0]["function"]["parameters"]["properties"]["n"]["type"] == "integer"


async def test_structured_refusal_and_length_raise_without_failover() -> None:
    for finish, code in (("content_filter", "refusal"), ("length", "max_tokens")):
        llm, gw, _ = make({"a.test": [completion("{", finish=finish)]}, endpoints=chain()[:1] + chain()[2:])
        with pytest.raises(LLMError) as exc:
            await llm.structured(task="t", system="S", messages=[], schema=Answer)
        assert exc.value.code == code and gw.hosts() == ["a.test"]


# --------------------------------------------------------------------------- retry policy


async def test_retryable_502_is_retried_then_succeeds() -> None:
    llm, gw, sleeps = make(
        [
            error(502, "incomplete_response", retryable=True),
            error(502, "provider_empty_response", retryable=True),
            completion('{"answer": "a", "n": 1}'),
        ]
    )
    out, usage = await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert out.n == 1 and len(gw.requests) == 3 and len(sleeps) == 2
    assert usage.llm_calls == 1
    assert 1.0 <= sleeps[0] <= 2.0 and 2.0 <= sleeps[1] <= 4.0  # exponential backoff with jitter


async def test_timeouts_and_connection_errors_are_retried() -> None:
    llm, _, sleeps = make(
        [httpx.ReadTimeout("slow"), httpx.ConnectError("refused"), completion('{"answer": "a", "n": 1}')]
    )
    out, _ = await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert out.n == 1 and len(sleeps) == 2


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (402, "insufficient_quota", "llm_quota"),
        (401, "invalid_api_key", "llm_auth"),
        (403, "forbidden", "llm_auth"),
        (404, "model_not_found", "llm_not_found"),
        (429, "insufficient_quota", "llm_quota"),
    ],
)
async def test_non_retryable_errors_raise_at_once(status: int, code: str, expected: str) -> None:
    llm, gw, sleeps = make([error(status, code)])
    with pytest.raises(LLMError) as exc:
        await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert exc.value.code == expected and len(gw.requests) == 1 and sleeps == []
    assert exc.value.owner_message == PROVIDER_OWNER_MESSAGES[expected]


async def test_exhausted_retries_raise_unavailable_or_rate_limited() -> None:
    llm, gw, _ = make([error(503, "overloaded")] * 3, max_retries=2)
    with pytest.raises(LLMError) as exc:
        await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert exc.value.code == "llm_unavailable" and len(gw.requests) == 3

    llm, _, _ = make([error(429, "rate_limit")] * 2, max_retries=1)
    with pytest.raises(LLMError) as exc:
        await loop(llm, recorder()[1])
    assert exc.value.code == "llm_rate_limited"


async def test_empty_assistant_message_is_retried_once() -> None:
    llm, gw, _ = make([completion(""), completion('{"answer": "a", "n": 1}')])
    out, usage = await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert out.n == 1 and len(gw.requests) == 2 and usage.llm_calls == 2

    llm, gw, _ = make([completion(None), completion(None, [call("c", "finish", {})], "tool_calls")])
    result = await loop(llm, recorder()[1])
    assert result.stop_reason == "finished" and len(gw.requests) == 2


async def test_secrets_never_reach_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    llm, gw, _ = make(
        [error(401, "invalid_api_key", message=f"Incorrect API key provided: {KEY}")], log_bodies=True
    )
    with pytest.raises(LLMError) as exc:
        await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert gw.requests[0][2]["authorization"] == f"Bearer {KEY}"  # sent only as the header
    assert KEY not in str(exc.value) and KEY not in exc.value.message and "***" in exc.value.message
    assert KEY not in caplog.text and KEY not in repr(llm) and KEY not in repr(llm.endpoints)


# --------------------------------------------------------------------------- endpoint chain


async def test_failover_to_the_next_endpoint_on_quota_and_rate_limit() -> None:
    llm, gw, _ = make(
        {
            "a.test": [error(402, "insufficient_quota")],
            "b.test": [error(429, "RESOURCE_EXHAUSTED")] * 2,
            GW: [completion('{"answer": "a", "n": 1}', prompt=10)],
        },
        endpoints=chain(),
        max_retries=1,
    )
    out, usage = await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert out.n == 1 and gw.hosts() == ["a.test", "b.test", "b.test", GW]
    assert [b["model"] for _, b, _ in gw.requests] == [
        "gemini-a",
        "gemini-b",
        "gemini-b",
        DEFAULT_OPENAI_MODEL,
    ]
    assert usage.input_tokens == 10
    assert gw.requests[0][2]["authorization"] == f"Bearer {KEY_A}"
    assert gw.requests[3][2]["authorization"] == f"Bearer {KEY}"


async def test_tool_loop_turns_fail_over_per_call() -> None:
    llm, gw, _ = make(
        {
            "a.test": [completion(None, [call("c1", "set_spec", {})], "tool_calls"), error(500, "boom")],
            "b.test": [completion(None, [call("c2", "finish", {})], "tool_calls")],
        },
        endpoints=chain()[:2],
        max_retries=0,
    )
    result = await loop(llm, recorder()[1])
    assert result.stop_reason == "finished" and gw.hosts() == ["a.test", "a.test", "b.test"]
    assert gw.bodies("b.test")[0]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": '{"ok":true}',
    }


async def test_invalid_or_empty_output_and_rejected_requests_fail_over() -> None:
    llm, gw, _ = make(
        {
            "a.test": [completion("nope"), completion("nope again")],
            "b.test": [error(400, "bad")] * 3,
            GW: [completion('{"answer": "a", "n": 1}')],
        },
        endpoints=chain(),
    )
    out, usage = await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert out.n == 1 and gw.hosts() == ["a.test", "a.test", "b.test", "b.test", "b.test", GW]
    assert usage.llm_calls == 3  # the two invalid answers are paid for too

    llm, gw, _ = make(
        {"a.test": [completion(""), completion("")], "b.test": [completion(None, [call("c", "finish", {})])]},
        endpoints=chain()[:2],
    )
    result = await loop(llm, recorder()[1])
    assert result.stop_reason == "finished" and gw.hosts() == ["a.test", "a.test", "b.test"]


async def test_every_endpoint_failing_raises_with_per_endpoint_codes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    llm, _, _ = make(
        {
            "a.test": [error(401, "invalid_api_key", message=f"bad key {KEY_A}")],
            "b.test": [error(402, "insufficient_quota")],
            GW: [error(502, "incomplete_response", retryable=True)] * 2,
        },
        endpoints=chain(),
        max_retries=1,
    )
    with pytest.raises(LLMError) as exc:
        await loop(llm, recorder()[1])
    message = exc.value.message
    assert exc.value.code == "llm_unavailable" and "all 3 LLM endpoints failed" in message
    assert "LLM_1 (a.test): llm_auth" in message and "LLM_2 (b.test): llm_quota" in message
    assert f"LLM ({GW}): llm_unavailable" in message
    for secret in (KEY, KEY_A, KEY_B):
        assert secret not in str(exc.value) and secret not in caplog.text


async def test_failed_endpoints_cool_down_then_come_back() -> None:
    clock = Clock()
    ok = completion('{"answer": "a", "n": 1}')
    llm, gw, _ = make(
        {"a.test": [error(402, "insufficient_quota"), ok], "b.test": [ok, ok]},
        endpoints=chain()[:2],
        clock=clock,
        cooldown_seconds=60,
    )
    await llm.structured(task="t", system="S", messages=[], schema=Answer)
    await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert gw.hosts() == ["a.test", "b.test", "b.test"]  # the second call skipped LLM_1
    clock.now += 61
    await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert gw.hosts()[-1] == "a.test"


async def test_cooling_endpoints_are_still_tried_when_nothing_else_is_left() -> None:
    clock = Clock()
    llm, gw, _ = make(
        {"a.test": [error(402, "q"), completion('{"answer": "a", "n": 1}')], "b.test": [error(401, "k")]},
        endpoints=chain()[:2],
        clock=clock,
    )
    with pytest.raises(LLMError):
        await llm.structured(task="t", system="S", messages=[], schema=Answer)
    out, _ = await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert out.n == 1 and gw.hosts() == ["a.test", "b.test", "a.test"]


# --------------------------------------------------------------------------- settings and factory


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_chain_order_indexed_entries_then_the_plain_endpoint() -> None:
    s = settings(
        LLM_PROVIDER="OpenAI",
        LLM_1_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/",
        LLM_1_API_KEY=KEY_A,
        LLM_2_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai",
        LLM_2_API_KEY=KEY_B,
        LLM_2_MODEL_STRONG="gemini-x",
        LLM_2_MODEL_FAST="gemini-x-lite",
        LLM_4_BASE_URL="https://ignored.test/v1",  # after a gap: not part of the chain
        LLM_4_API_KEY="k4",
        LLM_BASE_URL="https://top-tools-ai.com/v1",
        LLM_API_KEY=KEY,
        LLM_MODEL_STRONG="Qwen-3.8-Max",
        LLM_MODEL_FAST="Qwen-3.8-Max",
    )
    assert s.LLM_PROVIDER == "openai"
    endpoints, problems = endpoints_from_settings(s)
    assert problems == []
    assert [e.name for e in endpoints] == ["LLM_1", "LLM_2", "LLM"]
    first, second, last = endpoints
    assert first.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert first.strong_model == DEFAULT_GEMINI_MODEL and first.model_for("fast") == DEFAULT_GEMINI_MODEL
    assert second.model_for("strong") == "gemini-x" and second.model_for("fast") == "gemini-x-lite"
    assert last.host == "top-tools-ai.com" and last.strong_model == "Qwen-3.8-Max"
    llm = make_llm(s)
    assert isinstance(llm, OpenAICompatLLM) and [e.name for e in llm.endpoints] == ["LLM_1", "LLM_2", "LLM"]
    assert KEY not in repr(llm) and KEY_A not in llm.describe()


def test_single_plain_endpoint_and_defaults() -> None:
    s = settings(LLM_PROVIDER="openai", LLM_BASE_URL="https://top-tools-ai.com/v1", LLM_API_KEY=KEY)
    llm = make_llm(s)
    assert isinstance(llm, OpenAICompatLLM)
    (endpoint,) = llm.endpoints
    assert endpoint.name == "LLM" and endpoint.base_url == "https://top-tools-ai.com/v1"
    assert llm.strong_model == llm.fast_model == DEFAULT_OPENAI_MODEL
    assert llm.max_retries == 4 and llm.cooldown_seconds == 60
    assert KEY not in repr(s)  # SecretStr


def test_entries_with_problems_are_skipped_and_reported() -> None:
    s = settings(
        LLM_PROVIDER="openai",
        LLM_1_BASE_URL="https://a.test/v1",  # no key
        LLM_2_BASE_URL="b.test/v1",  # no scheme
        LLM_2_API_KEY="k",
        LLM_3_BASE_URL="https://c.test/v1",
        LLM_3_API_KEY="k3",
        LLM_API_KEY=KEY,  # no LLM_BASE_URL
    )
    endpoints, problems = endpoints_from_settings(s)
    assert [e.name for e in endpoints] == ["LLM_3"]
    assert any("LLM_1_API_KEY" in p for p in problems) and any("LLM_2_BASE_URL" in p for p in problems)
    assert any("LLM_BASE_URL" in p for p in problems)
    assert all(KEY not in p and "k3" not in p for p in problems)


async def test_missing_openai_config_fails_runs_not_boot() -> None:
    llm = make_llm(settings(LLM_PROVIDER="openai", LLM_BASE_URL="https://top-tools-ai.com/v1"))
    assert isinstance(llm, UnavailableLLM) and "LLM_API_KEY" in llm.reason
    with pytest.raises(LLMError) as exc:
        await llm.structured(task="t", system="S", messages=[], schema=Answer)
    assert exc.value.code == "llm_config" and exc.value.owner_message == PROVIDER_OWNER_MESSAGES["llm_config"]
    with pytest.raises(LLMError):
        await llm.tool_loop(
            task="b", system="S", messages=[], tools=[], handler=recorder()[1], max_tool_calls=1
        )

    unknown = make_llm(settings(LLM_PROVIDER="mistral"))
    assert isinstance(unknown, UnavailableLLM) and "mistral" in unknown.reason


def test_anthropic_stays_the_default_and_empty_numbers_mean_defaults() -> None:
    s = settings(LLM_PROVIDER="", LLM_TIMEOUT_SECONDS="", LLM_MAX_RETRIES=" ")
    assert s.LLM_PROVIDER == "anthropic" and s.LLM_TIMEOUT_SECONDS == 180.0 and s.LLM_MAX_RETRIES == 4
    assert isinstance(make_llm(s), AnthropicLLM)
