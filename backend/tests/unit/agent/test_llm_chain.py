"""Gemini provider, provider fallback chain and their settings. Offline: httpx.MockTransport only."""

import logging
import traceback
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.agent import llm_chain
from app.agent.llm import LLMError, ToolOutcome, UnavailableLLM, make_llm
from app.agent.llm_chain import ChainLLM, make_chain
from app.agent.llm_gemini import GeminiLLM
from app.config import Settings
from tests.unit.agent.test_llm_liara import TOOLS, Answer, Wire, call, completion

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
KEYS = ["gemini-key-one-never-log", "gemini-key-two-never-log", "gemini-key-three-never-log"]
TOP_KEY = "top-tools-key-never-log"
TOP_MODEL = "Qwen-3.8-Max"


@pytest.fixture(autouse=True)
def _no_cooldowns(monkeypatch):
    # A developer's real keys in the environment must never reach these offline tests.
    for name in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "LLM_CHAIN"):
        monkeypatch.delenv(name, raising=False)
    llm_chain._cooldowns.clear()
    yield
    llm_chain._cooldowns.clear()


def settings(**overrides: Any) -> Settings:
    options = {
        "LLM_PROVIDER": "chain",
        "GEMINI_API_KEYS": ",".join(KEYS[:2]),
        "GEMINI_MAX_RETRIES": 0,
        "TOP_TOOLS_API_KEY": TOP_KEY,
        "TOP_TOOLS_MODEL_STRONG": TOP_MODEL,
        "TOP_TOOLS_MODEL_FAST": TOP_MODEL,
        "TOP_TOOLS_MAX_RETRIES": 0,
        **overrides,
    }
    return Settings(_env_file=None, **options)


def chain(responses: list[Any], providers=("gemini", "top_tools"), **overrides: Any) -> tuple[ChainLLM, Wire]:
    wire = Wire(responses)
    llm = make_chain(
        list(providers), settings=settings(**overrides), transport=httpx.MockTransport(wire.handle)
    )
    return llm, wire


def keys_used(wire: Wire) -> list[str]:
    return [request.headers["authorization"].removeprefix("Bearer ") for request in wire.requests]


async def structured(llm, **kwargs):
    return await llm.structured(task="understand", system="s", messages=[], schema=Answer, **kwargs)


def status(code: int) -> httpx.Response:
    return httpx.Response(code, json={"error": {"code": code, "message": "nope"}})


async def test_gemini_success_uses_its_endpoint_model_and_counts_hidden_thinking_tokens():
    wire = Wire([completion()])
    body = wire.responses[0]
    body["usage"]["total_tokens"] = 150  # Gemini counts thinking tokens only in the total
    llm = GeminiLLM(settings=settings(), transport=httpx.MockTransport(wire.handle))
    out, usage = await structured(llm)
    assert out == Answer(answer="سلام", count=2)
    assert usage.input_tokens == 100 and usage.output_tokens == 50
    assert str(wire.requests[0].url) == GEMINI_URL + "/chat/completions"
    assert wire.bodies[0]["model"] == "gemini-flash-latest"
    assert keys_used(wire) == [KEYS[0]]


async def test_rate_limited_key_falls_through_to_the_next_key_without_retrying(caplog):
    caplog.set_level(logging.INFO)
    llm, wire = chain([status(429), completion()], GEMINI_MAX_RETRIES=2)
    out, usage = await structured(llm)
    assert out.count == 2 and usage.llm_calls == 1
    assert keys_used(wire) == KEYS[:2]
    assert "served by gemini#2 (model gemini-flash-latest)" in caplog.text


async def test_all_gemini_keys_fail_then_top_tools_serves(caplog):
    caplog.set_level(logging.INFO)
    llm, wire = chain([status(503), status(503), status(429), completion()], GEMINI_MAX_RETRIES=1)
    out, _ = await structured(llm, tier="fast")
    assert out.count == 2
    assert keys_used(wire) == [KEYS[0], KEYS[0], KEYS[1], TOP_KEY]  # 5xx retried in place first
    assert str(wire.requests[-1].url).startswith("https://top-tools-ai.com/api/v1")
    assert wire.bodies[-1]["model"] == TOP_MODEL
    assert "served by top_tools" in caplog.text


@pytest.mark.parametrize(
    "bad",
    [
        completion(content=""),
        completion(content=None, calls=[call("write", call_id="")], finish="tool_calls"),
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        httpx.Response(200, content=b"not json"),
        httpx.TimeoutException("slow"),
        status(404),
        status(400),
    ],
)
async def test_empty_invalid_or_failed_responses_fall_through(bad):
    llm, wire = chain([bad, completion()], providers=("gemini",))
    out, _ = await structured(llm)
    assert out.count == 2 and keys_used(wire) == KEYS[:2]


async def test_all_fail_raises_llm_error_listing_codes_per_target_never_keys(caplog):
    caplog.set_level(logging.DEBUG)
    llm, _ = chain([status(429), status(401), status(500)], providers=("gemini", "top_tools", "nope"))
    with pytest.raises(LLMError) as info:
        await structured(llm)
    exc = info.value
    assert exc.code == "api_error"
    assert exc.message == (
        "All AI providers failed: gemini#1: api_error (HTTP 429); gemini#2: api_error (HTTP 401); "
        "top_tools: api_error (HTTP 500); nope: unsupported."
    )
    text = caplog.text + str(exc) + "".join(traceback.format_exception(exc))
    assert not [secret for secret in [*KEYS, TOP_KEY] if secret in text]
    assert "failed (api_error (HTTP 429))" in caplog.text


async def test_quota_and_auth_errors_put_a_key_in_cooldown():
    llm, wire = chain([status(429), completion(), completion()], providers=("gemini",))
    await structured(llm)
    out, _ = await structured(llm)  # key 1 is skipped: one request, straight to key 2
    assert out.count == 2 and keys_used(wire) == [KEYS[0], KEYS[1], KEYS[1]]
    llm_chain._cooldowns.clear()
    wire.responses.append(completion())
    await structured(llm)
    assert keys_used(wire)[-1] == KEYS[0]


async def test_cooldown_lists_skipped_targets_and_zero_disables_it():
    llm, _ = chain([status(429), status(429)], providers=("gemini",))
    with pytest.raises(LLMError):
        await structured(llm)
    with pytest.raises(LLMError, match="gemini#1: cooldown; gemini#2: cooldown"):
        await structured(llm)
    llm_chain._cooldowns.clear()
    llm, wire = chain(
        [status(429), completion(), completion()], providers=("gemini",), LLM_COOLDOWN_SECONDS=0
    )
    await structured(llm)
    await structured(llm)
    assert keys_used(wire)[-1] == KEYS[0]


async def test_tool_loop_falls_back_mid_loop_and_keeps_the_per_provider_error():
    seen: list[int] = []

    async def handler(name, args):
        if name == "finish":
            return ToolOutcome({"ok": True}, stop=True)
        seen.append(args["value"])
        return ToolOutcome({"ok": True})

    first = completion(content=None, calls=[call("write", '{"value":1}')], finish="tool_calls")
    second = completion(content=None, calls=[call("finish", call_id="c2")], finish="tool_calls")
    llm, wire = chain([first, status(429), status(429), second])
    result = await llm.tool_loop(
        task="build", system="s", messages=[], tools=TOOLS, handler=handler, max_tool_calls=3
    )
    assert result.stop_reason == "finished" and seen == [1]
    assert keys_used(wire) == [KEYS[0], KEYS[0], KEYS[1], TOP_KEY]

    llm_chain._cooldowns.clear()
    llm, _ = chain([status(500), status(500), status(500)])
    with pytest.raises(LLMError, match="gemini#1: api_error \\(HTTP 500\\)"):
        await llm.tool_loop(task="b", system="s", messages=[], tools=TOOLS, handler=handler, max_tool_calls=3)


def test_gemini_settings_parse_the_key_list_and_hide_secrets():
    s = Settings(
        _env_file=None,
        GEMINI_API_KEYS=" a1 , b2 ,,a1 ",
        GEMINI_API_KEY="c3",
        GEMINI_API_KEY_2="b2",
        GEMINI_API_KEY_3="d4",
    )
    assert [key.get_secret_value() for key in s.gemini_api_keys] == ["a1", "b2", "c3", "d4"]
    assert all(isinstance(key, SecretStr) for key in s.gemini_api_keys)
    assert "a1" not in repr(s) + str(s) + s.model_dump_json()
    many = Settings(_env_file=None, GEMINI_API_KEYS="k1,k2,k3,k4,k5,k6", GEMINI_API_KEY="k7")
    assert [key.get_secret_value() for key in many.gemini_api_keys] == ["k1", "k2", "k3", "k4", "k5"]
    single = Settings(_env_file=None, GEMINI_API_KEY="only")
    assert [key.get_secret_value() for key in single.gemini_api_keys] == ["only"]
    assert Settings(_env_file=None, GEMINI_API_KEYS=" , ").gemini_api_keys == []
    with pytest.raises(ValidationError):
        Settings(_env_file=None, GEMINI_API_KEYS="good,bad key")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, GEMINI_BASE_URL="https://evil.test/v1beta/openai")


def test_gemini_and_chain_defaults_and_readiness():
    s = Settings(_env_file=None)
    assert s.GEMINI_BASE_URL == GEMINI_URL
    assert s.GEMINI_MODEL_STRONG == s.GEMINI_MODEL_FAST == "gemini-flash-latest"
    assert s.GEMINI_TIMEOUT_SECONDS == 90 and s.GEMINI_MAX_RETRIES == 1
    assert s.llm_chain == ["gemini", "top_tools"] and s.LLM_COOLDOWN_SECONDS == 60
    assert not Settings(_env_file=None, LLM_PROVIDER="gemini").llm_configured
    assert Settings(_env_file=None, LLM_PROVIDER=" Gemini ", GEMINI_API_KEY="k").llm_configured
    assert not Settings(_env_file=None, LLM_PROVIDER="chain", LLM_CHAIN="nope, top_tools").llm_configured
    assert settings(LLM_CHAIN=" nope , TOP_TOOLS ").llm_configured
    assert settings(LLM_CHAIN="nope").llm_configured is False


@pytest.mark.parametrize("provider", ["gemini", "chain"])
def test_factory_builds_the_chain(monkeypatch, provider):
    s = settings(LLM_PROVIDER=provider)
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    llm = make_llm()
    assert isinstance(llm, ChainLLM)
    expected = "Gemini=gemini-flash-latest" + (f", Top Tools={TOP_MODEL}" if provider == "chain" else "")
    assert llm.strong_model == expected


async def test_unknown_provider_does_not_stop_startup_and_fails_runs_clearly(monkeypatch):
    s = Settings(_env_file=None, LLM_PROVIDER="gpt-9000")
    assert s.LLM_PROVIDER == "gpt-9000" and not s.llm_configured
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    llm = make_llm()
    assert isinstance(llm, UnavailableLLM)
    with pytest.raises(LLMError, match="LLM_PROVIDER='gpt-9000' is not supported"):
        await structured(llm)
    with pytest.raises(LLMError, match="not supported"):
        await llm.tool_loop(task="b", system="s", messages=[], tools=[], handler=None, max_tool_calls=1)
