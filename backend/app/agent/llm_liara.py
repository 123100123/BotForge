"""Liara's project-scoped wrapper around the shared chat completions boundary."""

import httpx

from app.agent.llm_openai_compatible import OpenAICompatibleLLM, ProviderConfig
from app.config import Settings, get_settings, parse_token_prices, validate_liara_url


class LiaraLLM(OpenAICompatibleLLM):
    """Keep Liara settings and endpoint validation independent from every other provider."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            ProviderConfig(
                label="Liara",
                key=settings.LIARA_API_KEY,
                base_url=validate_liara_url(settings.LIARA_BASE_URL),
                strong_model=settings.LIARA_MODEL_STRONG,
                fast_model=settings.LIARA_MODEL_FAST,
                max_tokens=settings.LIARA_MAX_TOKENS,
                timeout_seconds=settings.LIARA_TIMEOUT_SECONDS,
                max_retries=settings.LIARA_MAX_RETRIES,
                rates=parse_token_prices(settings.LIARA_TOKEN_PRICES_JSON),
            ),
            transport=transport,
        )
