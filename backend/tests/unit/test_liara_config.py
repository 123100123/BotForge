"""Provider selection and fail-closed configuration without credentials or live requests."""

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agent.llm import AnthropicLLM, make_llm
from app.agent.llm_liara import LiaraLLM
from app.api.analysis import get_llm_optional
from app.api.copilot import get_copilot_llm
from app.config import Settings, get_settings, parse_liara_prices

URL = "https://ai.liara.ir/api/v1/682833f68c7347b1c1612d00"
SECRET = "test-secret-never-print"


def test_defaults_and_secret_representation():
    settings = Settings(_env_file=None, LIARA_API_KEY=SECRET)
    assert settings.LLM_PROVIDER == "anthropic"
    assert settings.LIARA_MODEL_STRONG == "google/gemini-3.8-flash"
    assert settings.LIARA_MODEL_FAST == "deepseek/deepseek-v4-flash"
    assert SECRET not in str(settings) + repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "http://ai.liara.ir/api/v1/project",
        "https://evil.test/api/v1/project",
        "https://ai.liara.ir.evil.test/api/v1/project",
        "https://ai.liara.ir@evil.test/api/v1/project",
        "https://evil.test@ai.liara.ir/api/v1/project",
        URL + "?key=" + SECRET,
        URL + "#" + SECRET,
        "https://ai.liara.ir:443/api/v1/project",
        URL + "/../other",
        URL + "%2fextra",
        "https://ai.liara.ir/",
        "https://ai.liara.ir/api/v1/",
        URL + "\n",
    ],
)
def test_url_rejects_credential_exfiltration_and_wrong_paths(url):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, LIARA_BASE_URL=url)
    assert SECRET not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize(
    "prices",
    [
        "bad " + SECRET,
        "[]",
        '{"m":{}}',
        '{"m":{"input":-1,"output":1}}',
        '{"m":{"input":NaN,"output":1}}',
        '{"m":{"input":Infinity,"output":1}}',
        '{"m":{"input":true,"output":1}}',
        '{"m":{"input":"1","output":1}}',
        '{"m":{"input":1,"output":1,"extra":2}}',
        json.dumps({"m": {"input": 10**1000, "output": 1}}),
    ],
)
def test_prices_reject_invalid_rates_with_safe_errors(prices):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, LIARA_TOKEN_PRICES_JSON=prices)
    assert SECRET not in str(caught.value)


def test_prices_defaults_to_input_for_cached_tokens():
    assert parse_liara_prices("") == {}
    assert parse_liara_prices('{"m":{"input":2,"output":5}}') == {
        "m": {"input": 2, "output": 5, "cache_read": 2}
    }
    assert Settings(_env_file=None, LIARA_BASE_URL=URL + "/").LIARA_BASE_URL == URL


@pytest.mark.parametrize(
    "setting,value",
    [
        ("LIARA_MAX_TOKENS", 0),
        ("LIARA_MAX_RETRIES", -1),
        ("LIARA_TIMEOUT_SECONDS", float("inf")),
        ("LIARA_TIMEOUT_SECONDS", 0),
        ("LIARA_API_KEY", "a\nb"),
        ("LIARA_MODEL_STRONG", ""),
        ("LIARA_MODEL_FAST", "bad model"),
    ],
)
def test_bounds(setting, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{setting: value})


@pytest.mark.parametrize("configured", [False, True])
def test_factory_and_feature_readiness(monkeypatch, configured):
    settings = Settings(
        _env_file=None,
        LLM_PROVIDER="liara",
        LIARA_API_KEY=SECRET if configured else None,
        LIARA_BASE_URL=URL if configured else None,
    )
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.analysis.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.copilot.get_settings", lambda: settings)
    assert isinstance(make_llm(), LiaraLLM)
    if configured:
        assert isinstance(get_llm_optional(), LiaraLLM) and isinstance(get_copilot_llm(), LiaraLLM)
    else:
        assert get_llm_optional() is None
        with pytest.raises(HTTPException) as caught:
            get_copilot_llm()
        assert caught.value.status_code == 503 and caught.value.detail["code"] == "llm_unavailable"


def test_existing_provider_selection(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(_env_file=None))
    assert isinstance(make_llm(), AnthropicLLM)
    monkeypatch.setattr(
        "app.config.get_settings", lambda: Settings(_env_file=None, LLM_PROVIDER="claude_cli")
    )
    from app.agent.llm_claude_code import ClaudeCodeLLM

    assert isinstance(make_llm(), ClaudeCodeLLM)
    assert Settings(_env_file=None, LLM_PROVIDER="claude_cli").llm_configured


def test_environment_provider_switch_requires_new_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "liara")
    monkeypatch.setenv("LIARA_BASE_URL", URL)
    monkeypatch.setenv("LIARA_API_KEY", SECRET)
    try:
        assert get_settings().llm_configured
        assert isinstance(make_llm(), LiaraLLM)
    finally:
        get_settings.cache_clear()
