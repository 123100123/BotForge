"""Top Tools wrapper isolation, endpoint and shared protocol regression checks. Offline only."""

import asyncio
import json
import logging
import traceback
from dataclasses import FrozenInstanceError
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.agent.llm import LLMError, ToolOutcome
from app.agent.llm_liara import LiaraLLM
from app.agent.llm_top_tools import TopToolsLLM
from app.config import Settings
from tests.unit.agent.test_llm_liara import (
    FAST,
    SENTINEL,
    TOOLS,
    URL,
    Answer,
    Wire,
    call,
    completion,
)

TOP_URL = "https://top-tools-ai.com/api/v1"
TOP_KEY = "top-tools-test-secret-never-log"
# Deliberately test-only slugs; real availability must be checked with the provider.
TOP_STRONG = "test/top-strong"
TOP_FAST = "test/top-fast"


def top_model(responses: list[Any], **overrides: Any) -> tuple[TopToolsLLM, Wire]:
    options = {
        "LLM_PROVIDER": "top_tools",
        "TOP_TOOLS_API_KEY": TOP_KEY,
        "TOP_TOOLS_MODEL_STRONG": TOP_STRONG,
        "TOP_TOOLS_MODEL_FAST": TOP_FAST,
        **overrides,
    }
    settings = Settings(_env_file=None, **options)
    wire = Wire(responses)
    return TopToolsLLM(settings=settings, transport=httpx.MockTransport(wire.handle)), wire


async def structured(llm, **kwargs):
    return await llm.structured(task="understand", system="s", messages=[], schema=Answer, **kwargs)


async def loop(llm, handler, **kwargs):
    return await llm.tool_loop(
        task="build", system="s", messages=[], tools=TOOLS, handler=handler, max_tool_calls=3, **kwargs
    )


@pytest.mark.parametrize("tier,expected", [("strong", TOP_STRONG), ("fast", TOP_FAST)])
@pytest.mark.parametrize("endpoint", [TOP_URL, "https://top-tools-ai.com/v1"])
async def test_top_tools_structured_targets_its_own_key_models_and_endpoint(tier, expected, endpoint):
    llm, wire = top_model([completion()], TOP_TOOLS_BASE_URL=endpoint + "/")
    out, usage = await structured(llm, tier=tier)
    assert out == Answer(answer="سلام", count=2) and usage.input_tokens == 100
    assert wire.bodies[0]["model"] == expected
    assert wire.requests[0].headers["authorization"] == "Bearer " + TOP_KEY
    assert str(wire.requests[0].url) == endpoint + "/chat/completions"


async def test_provider_snapshots_are_immutable_and_isolated_under_concurrent_calls():
    common_model = "test/shared-model"
    settings = Settings(
        _env_file=None,
        LIARA_API_KEY=SENTINEL,
        LIARA_BASE_URL=URL,
        LIARA_MODEL_STRONG=common_model,
        LIARA_TOKEN_PRICES_JSON=json.dumps({common_model: {"input": 1, "output": 2}}),
        TOP_TOOLS_API_KEY=TOP_KEY,
        TOP_TOOLS_MODEL_STRONG=common_model,
        TOP_TOOLS_MODEL_FAST=TOP_FAST,
        TOP_TOOLS_TOKEN_PRICES_JSON=json.dumps({common_model: {"input": 10, "output": 20}}),
        LIARA_MAX_TOKENS=111,
        TOP_TOOLS_MAX_TOKENS=222,
    )
    liara_wire, top_wire = Wire([completion(), completion()]), Wire([completion(), completion()])
    liara = LiaraLLM(settings=settings, transport=httpx.MockTransport(liara_wire.handle))
    top = TopToolsLLM(settings=settings, transport=httpx.MockTransport(top_wire.handle))
    # Later changes to Settings cannot alter an already-created provider.
    settings.TOP_TOOLS_API_KEY = SecretStr("different-key")
    settings.TOP_TOOLS_MODEL_STRONG = "different-model"
    settings.TOP_TOOLS_BASE_URL = "https://example.invalid"
    settings.LIARA_TOKEN_PRICES_JSON = ""
    settings.LIARA_MAX_TOKENS = 999
    with pytest.raises(FrozenInstanceError):
        top._config.base_url = URL
    with pytest.raises(TypeError):
        top._config.rates[common_model]["input"] = 0
    assert TOP_KEY not in repr(top._config) and SENTINEL not in repr(liara._config)
    results = await asyncio.gather(
        structured(liara), structured(top), structured(liara, tier="fast"), structured(top, tier="fast")
    )
    assert results[0][1].cost_usd == 0.00014 and results[1][1].cost_usd == 0.0014
    assert results[2][1].cost_usd == results[3][1].cost_usd == 0
    assert [body["model"] for body in liara_wire.bodies] == [common_model, FAST]
    assert [body["model"] for body in top_wire.bodies] == [common_model, TOP_FAST]
    for wire, base, key, max_tokens in [(liara_wire, URL, SENTINEL, 111), (top_wire, TOP_URL, TOP_KEY, 222)]:
        assert all(str(req.url) == base + "/chat/completions" for req in wire.requests)
        assert all(req.headers["authorization"] == "Bearer " + key for req in wire.requests)
        assert all(body["max_tokens"] == max_tokens for body in wire.bodies)


async def test_both_wrappers_revalidate_endpoint_after_settings_mutation():
    settings = Settings(_env_file=None)
    settings.TOP_TOOLS_BASE_URL = URL
    with pytest.raises(ValueError, match="TOP_TOOLS_BASE_URL"):
        TopToolsLLM(settings=settings)
    settings.LIARA_BASE_URL = TOP_URL
    with pytest.raises(ValueError, match="LIARA_BASE_URL"):
        LiaraLLM(settings=settings)


@pytest.mark.parametrize(
    "missing", ["TOP_TOOLS_API_KEY", "TOP_TOOLS_BASE_URL", "TOP_TOOLS_MODEL_STRONG", "TOP_TOOLS_MODEL_FAST"]
)
async def test_missing_configuration_never_requests_or_falls_back(missing):
    llm, wire = top_model(
        [],
        **{missing: ""},
        LIARA_API_KEY=SENTINEL,
        LIARA_BASE_URL=URL,
        ANTHROPIC_API_KEY="unused-anthropic-test-key",
    )
    with pytest.raises(LLMError, match="api_error"):
        await structured(llm)
    with pytest.raises(LLMError, match="api_error"):
        await loop(llm, None)
    assert wire.requests == []


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 402, 403])
async def test_html_errors_and_redirects_are_safe_and_never_retried(status, caplog):
    llm, wire = top_model(
        [
            httpx.Response(
                status,
                text="<html>" + TOP_KEY + "</html>",
                headers={"Location": "https://example.invalid/?key=" + TOP_KEY},
            )
        ],
        LOG_LLM_BODIES=True,
    )
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LLMError) as caught:
        await structured(llm)
    assert len(wire.requests) == 1
    error = caught.value
    assert error.__cause__ is None and error.__context__ is None
    assert TOP_KEY not in caplog.text + str(error) + "".join(traceback.format_exception(error))


async def test_top_tools_tool_loop_keeps_usage_signatures_and_terminal_behavior():
    first = completion(
        None,
        calls=[call("write", '{"value":1}', extra_content={"signature": "opaque"})],
        finish="tool_calls",
        reasoning_content="thought",
    )
    first["usage"].update(
        prompt_tokens_details={"cached_tokens": 25}, completion_tokens_details={"reasoning_tokens": 10}
    )
    llm, wire = top_model(
        [
            first,
            completion(
                None,
                calls=[call("finish", call_id="c2"), call("write", '{"value":2}', call_id="c3")],
                finish="tool_calls",
            ),
        ]
    )
    seen = []

    async def handler(name, args):
        seen.append((name, args))
        return ToolOutcome({"ok": True}, stop=name == "finish")

    result = await loop(llm, handler)
    assert result.stop_reason == "finished" and result.usage.tool_calls == 2
    assert result.usage.input_tokens == 175 and result.usage.cached_tokens == 25
    assert result.usage.output_tokens == 40 and result.usage.llm_calls == 2
    assert seen == [("write", {"value": 1}), ("finish", {})]
    assert wire.bodies[1]["messages"][1] == first["choices"][0]["message"]


async def test_top_tools_usage_hook_stops_before_tools():
    llm, _ = top_model([completion(None, calls=[call("finish")], finish="tool_calls")])
    charged = []

    async def handler(*args):
        raise AssertionError("Must not dispatch")

    result = await loop(llm, handler, on_usage=lambda u: charged.append(u) or False)
    assert result.stop_reason == "budget" and charged[0].input_tokens == 100
    assert result.usage.tool_calls == 0


async def test_top_tools_cancellation_closes_transport_without_retry():
    class Transport(httpx.AsyncBaseTransport):
        closed = False
        calls = 0

        async def handle_async_request(self, request):
            self.calls += 1
            raise asyncio.CancelledError()

        async def aclose(self):
            self.closed = True

    transport = Transport()
    settings = Settings(
        _env_file=None,
        TOP_TOOLS_API_KEY=TOP_KEY,
        TOP_TOOLS_MODEL_STRONG=TOP_STRONG,
        TOP_TOOLS_MODEL_FAST=TOP_FAST,
    )
    llm = TopToolsLLM(settings=settings, transport=transport)
    with pytest.raises(asyncio.CancelledError):
        await structured(llm)
    assert transport.closed and transport.calls == 1
