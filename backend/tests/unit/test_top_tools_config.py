"""Top Tools independent readiness and secure configuration; no provider access."""

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agent.llm import make_llm
from app.agent.llm_top_tools import TopToolsLLM
from app.api.analysis import get_llm_optional
from app.api.copilot import get_copilot_llm
from app.config import Settings
from tests.unit.agent.test_llm_top_tools import TOP_FAST, TOP_KEY, TOP_STRONG, TOP_URL


def test_top_tools_defaults_require_explicit_model_ids_and_hide_secret():
    settings = Settings(_env_file=None, LLM_PROVIDER="top_tools", TOP_TOOLS_API_KEY=TOP_KEY)
    assert settings.TOP_TOOLS_BASE_URL == TOP_URL
    assert settings.TOP_TOOLS_MODEL_STRONG == settings.TOP_TOOLS_MODEL_FAST == ""
    assert not settings.llm_configured
    assert settings.TOP_TOOLS_MAX_TOKENS == 32000 and settings.TOP_TOOLS_TIMEOUT_SECONDS == 180
    assert settings.TOP_TOOLS_MAX_RETRIES == 2 and settings.TOP_TOOLS_TOKEN_PRICES_JSON == ""
    assert TOP_KEY not in str(settings) + repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "http://top-tools-ai.com/api/v1",
        "https://top-tools-ai.com.evil.test/api/v1",
        "https://evil.test@top-tools-ai.com/api/v1",
        "https://top-tools-ai.com@evil.test/api/v1",
        "https://top-tools-ai.com:443/api/v1",
        "https://top-tools-ai.com:8443/api/v1",
        TOP_URL + "?key=" + TOP_KEY,
        TOP_URL + "#" + TOP_KEY,
        TOP_URL + "/chat/completions",
        TOP_URL + "/../v1",
        TOP_URL + "%2f",
        TOP_URL + "\n",
        "https://top-tools-ai.com/",
        "https://ai.liara.ir/api/v1/project",
        "https://www.top-tools-ai.com/api/v1",
    ],
)
def test_endpoint_rejects_other_origins_and_ambiguous_paths(url):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, TOP_TOOLS_BASE_URL=url)
    assert TOP_KEY not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize(
    "setting,value",
    [
        ("TOP_TOOLS_API_KEY", "a\nb"),
        ("TOP_TOOLS_MODEL_STRONG", "bad model"),
        ("TOP_TOOLS_MAX_TOKENS", 0),
        ("TOP_TOOLS_MAX_RETRIES", -1),
        ("TOP_TOOLS_MAX_RETRIES", 11),
        ("TOP_TOOLS_TIMEOUT_SECONDS", 0),
        ("TOP_TOOLS_TIMEOUT_SECONDS", float("inf")),
        ("TOP_TOOLS_TOKEN_PRICES_JSON", "[]"),
        ("TOP_TOOLS_TOKEN_PRICES_JSON", '{"m":{"input":-1,"output":2}}'),
        ("TOP_TOOLS_TOKEN_PRICES_JSON", '{"m":{"input":true,"output":2}}'),
        ("TOP_TOOLS_TOKEN_PRICES_JSON", '{"m":{"input":NaN,"output":2}}'),
        ("TOP_TOOLS_TOKEN_PRICES_JSON", json.dumps({"m": {"input": 10**1000, "output": 1}})),
    ],
)
def test_top_tools_uses_shared_safe_bounds_and_price_validation(setting, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{setting: value})


@pytest.mark.parametrize(
    "missing",
    [None, "TOP_TOOLS_API_KEY", "TOP_TOOLS_BASE_URL", "TOP_TOOLS_MODEL_STRONG", "TOP_TOOLS_MODEL_FAST"],
)
def test_factory_and_both_feature_dependencies_require_all_top_tools_fields(monkeypatch, missing):
    values = {
        "LLM_PROVIDER": "top_tools",
        "TOP_TOOLS_API_KEY": TOP_KEY,
        "TOP_TOOLS_MODEL_STRONG": TOP_STRONG,
        "TOP_TOOLS_MODEL_FAST": TOP_FAST,
    }
    if missing:
        values[missing] = ""
    settings = Settings(_env_file=None, **values)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.analysis.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.copilot.get_settings", lambda: settings)
    assert isinstance(make_llm(), TopToolsLLM)
    if missing:
        assert not settings.llm_configured and get_llm_optional() is None
        with pytest.raises(HTTPException) as caught:
            get_copilot_llm()
        assert caught.value.status_code == 503 and caught.value.detail["code"] == "llm_unavailable"
    else:
        assert settings.llm_configured and isinstance(get_llm_optional(), TopToolsLLM)
        assert isinstance(get_copilot_llm(), TopToolsLLM)


@pytest.mark.parametrize("missing", ["TOP_TOOLS_MODEL_STRONG", "TOP_TOOLS_MODEL_FAST"])
async def test_eval_cli_rejects_missing_model_before_provider_construction(monkeypatch, capsys, missing):
    from scripts import eval_golden

    settings = Settings(
        _env_file=None,
        TOP_TOOLS_API_KEY=TOP_KEY,
        TOP_TOOLS_MODEL_STRONG=TOP_STRONG,
        TOP_TOOLS_MODEL_FAST=TOP_FAST,
    )
    setattr(settings, missing, "")
    monkeypatch.setattr(eval_golden, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.argv", ["eval_golden.py", "--create", "--provider", "top_tools"])
    assert await eval_golden.main() == 2
    stderr = capsys.readouterr().err
    assert "TOP_TOOLS_MODEL" in stderr and TOP_KEY not in stderr
