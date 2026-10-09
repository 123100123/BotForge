"""Top Tools settings wrapper; model IDs must be supplied explicitly by the operator."""

import httpx

from app.agent.llm_openai_compatible import OpenAICompatibleLLM, ProviderConfig
from app.config import Settings, get_settings, parse_token_prices, validate_top_tools_url


class TopToolsLLM(OpenAICompatibleLLM):
    """Use only TOP_TOOLS settings and the pinned Top Tools API endpoint."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            ProviderConfig(
                label="Top Tools",
                key=settings.TOP_TOOLS_API_KEY,
                base_url=validate_top_tools_url(settings.TOP_TOOLS_BASE_URL),
                strong_model=settings.TOP_TOOLS_MODEL_STRONG,
                fast_model=settings.TOP_TOOLS_MODEL_FAST,
                max_tokens=settings.TOP_TOOLS_MAX_TOKENS,
                timeout_seconds=settings.TOP_TOOLS_TIMEOUT_SECONDS,
                max_retries=settings.TOP_TOOLS_MAX_RETRIES,
                rates=parse_token_prices(settings.TOP_TOOLS_TOKEN_PRICES_JSON),
            ),
            transport=transport,
        )
