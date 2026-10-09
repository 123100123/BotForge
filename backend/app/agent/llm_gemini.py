"""Google Gemini through its OpenAI-compatible endpoint; one provider snapshot per configured key."""

import httpx
from pydantic import SecretStr

from app.agent.llm_openai_compatible import OpenAICompatibleLLM, ProviderConfig
from app.config import Settings, get_settings, parse_token_prices, validate_gemini_url


def gemini_config(settings: Settings, key: SecretStr | None) -> ProviderConfig:
    return ProviderConfig(
        label="Gemini",
        key=key,
        base_url=validate_gemini_url(settings.GEMINI_BASE_URL),
        strong_model=settings.GEMINI_MODEL_STRONG,
        fast_model=settings.GEMINI_MODEL_FAST,
        max_tokens=settings.GEMINI_MAX_TOKENS,
        timeout_seconds=settings.GEMINI_TIMEOUT_SECONDS,
        max_retries=settings.GEMINI_MAX_RETRIES,
        rates=parse_token_prices(settings.GEMINI_TOKEN_PRICES_JSON),
        hidden_reasoning_in_total=True,
    )


def gemini_configs(settings: Settings) -> list[ProviderConfig]:
    """One snapshot per key, in the order the keys are tried."""
    return [gemini_config(settings, key) for key in settings.gemini_api_keys]


class GeminiLLM(OpenAICompatibleLLM):
    """A single Gemini key (``key_index``). ``make_llm`` wraps every key in a ``ChainLLM`` instead, so
    a rate-limited key falls through to the next one."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        key_index: int = 0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = settings or get_settings()
        keys = settings.gemini_api_keys
        key = keys[key_index] if 0 <= key_index < len(keys) else None
        super().__init__(gemini_config(settings, key), transport=transport)
