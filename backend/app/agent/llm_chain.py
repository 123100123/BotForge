"""Ordered fallback across OpenAI-compatible providers (``LLM_PROVIDER=chain`` or ``gemini``).

Every model request tries the targets in order: each Gemini key in turn, then the next provider of
``LLM_CHAIN``. A target is left behind after any failure: an HTTP error (rate limit, quota, auth,
unknown model, other 4xx), a 5xx or timeout once that provider's own retries are spent, or an empty
or malformed response. 429/401/403 also put the target in a process-wide cooldown for
``LLM_COOLDOWN_SECONDS``. Only when every target fails is an ``LLMError`` raised, listing a code per
target. Targets are named ``gemini#2`` or ``top_tools``; keys never reach logs or error text.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.agent.llm import LLMError, Tier, Usage, UsageHook
from app.agent.llm_gemini import gemini_configs
from app.agent.llm_openai_compatible import (
    OpenAICompatibleLLM,
    ProviderConfig,
    ProviderError,
    _choice,
    _error,
)
from app.config import CHAIN_PROVIDERS, Settings, get_settings

logger = logging.getLogger(__name__)

_RETRY_IN_PLACE = frozenset({500, 502, 503, 504})  # a 429 moves on to the next key at once
_COOLDOWN_STATUSES = frozenset({401, 403, 429})
# Target name -> time.monotonic() until which it is skipped. Shared by every ChainLLM in the process.
_cooldowns: dict[str, float] = {}


@dataclass(frozen=True, slots=True)
class ChainTarget:
    name: str
    config: ProviderConfig | None = field(repr=False)  # None: not a chainable provider


def chain_targets(settings: Settings, providers: Sequence[str]) -> list[ChainTarget]:
    from app.agent.llm_liara import LiaraLLM
    from app.agent.llm_top_tools import TopToolsLLM

    targets: list[ChainTarget] = []
    for provider in providers:
        if provider not in CHAIN_PROVIDERS:
            targets.append(ChainTarget(provider[:40], None))
        elif provider == "gemini":
            configs = gemini_configs(settings)
            targets += [ChainTarget(f"gemini#{n}", c) for n, c in enumerate(configs, 1)]
            if not configs:
                targets.append(ChainTarget("gemini", None))
        elif provider == "top_tools":
            targets.append(ChainTarget("top_tools", TopToolsLLM(settings=settings)._config))
        else:
            targets.append(ChainTarget("liara", LiaraLLM(settings=settings)._config))
    return targets


def make_chain(
    providers: Sequence[str],
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ChainLLM:
    settings = settings or get_settings()
    return ChainLLM(
        chain_targets(settings, providers),
        cooldown_seconds=settings.LLM_COOLDOWN_SECONDS,
        transport=transport,
    )


def _check_response(body: dict[str, Any]) -> None:
    """Reject what no caller could use, so the next target gets a chance."""
    message, finish = _choice(body)
    if finish in {"refusal", "max_tokens"}:
        return
    calls = message.get("tool_calls")
    if calls:
        if not isinstance(calls, list) or not all(
            isinstance(call, dict)
            and call.get("type") == "function"
            and isinstance(call.get("id"), str)
            and call["id"]
            and isinstance(call.get("function"), dict)
            for call in calls
        ):
            raise _error("invalid_output")
    elif not (message.get("content") or "").strip():
        raise _error("invalid_output")


class ChainLLM(OpenAICompatibleLLM):
    """The shared structured/tool-loop logic, with each model request routed through the targets."""

    def __init__(
        self,
        targets: Sequence[ChainTarget],
        *,
        cooldown_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._targets = tuple(targets)
        self._cooldown_seconds = cooldown_seconds
        self._transport = transport

    def _models(self, tier: Tier) -> str:
        names = []
        for target in self._targets:
            config = target.config
            if config is not None:
                name = f"{config.label}={config.strong_model if tier == 'strong' else config.fast_model}"
                if name not in names:
                    names.append(name)
        return ", ".join(names) or "none"

    @property
    def strong_model(self) -> str:
        return self._models("strong")

    @property
    def fast_model(self) -> str:
        return self._models("fast")

    def _params(self, tier: Tier, history: list[dict[str, Any]]) -> dict[str, Any]:
        # "model" carries the tier until a target is chosen; max_tokens is per target too.
        return {"model": tier, "messages": history, "stream": False}

    async def _request(
        self,
        params: dict[str, Any],
        total: Usage,
        *,
        format_fallback: bool = False,
        on_usage: UsageHook | None = None,
    ) -> dict[str, Any] | None:
        tier = params["model"]
        failures: list[str] = []
        for target in self._targets:
            config = target.config
            if config is None or not config.configured:
                failures.append(f"{target.name}: {'unsupported' if config is None else 'not configured'}")
                continue
            if _cooldowns.get(target.name, 0.0) > time.monotonic():
                failures.append(f"{target.name}: cooldown")
                continue
            model = config.strong_model if tier == "strong" else config.fast_model
            try:
                body = await self._send(
                    config,
                    {**params, "model": model, "max_tokens": config.max_tokens},
                    total,
                    format_fallback=format_fallback,
                    on_usage=on_usage,
                    retry_statuses=_RETRY_IN_PLACE,
                )
                if body is not None:
                    _check_response(body)
            except ProviderError as exc:
                failure = f"{exc.code} (HTTP {exc.status})" if exc.status else exc.code
                if exc.status in _COOLDOWN_STATUSES and self._cooldown_seconds > 0:
                    _cooldowns[target.name] = time.monotonic() + self._cooldown_seconds
            except LLMError as exc:
                failure = exc.code
            else:
                logger.info("LLM request served by %s (model %s)", target.name, model)
                return body
            failures.append(f"{target.name}: {failure}")
            logger.warning("LLM provider %s failed (%s); trying the next one", target.name, failure)
        raise LLMError(
            "api_error",
            "All AI providers failed: " + ("; ".join(failures) or "LLM_CHAIN is empty") + ".",
            usage=total,
        )
