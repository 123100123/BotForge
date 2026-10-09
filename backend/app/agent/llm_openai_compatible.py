"""Shared OpenAI-compatible chat completions boundary for explicitly configured providers.

Only this module handles provider responses. Never log bodies or exception details here: callers
persist LLMError text and may log its traceback. Model output is untrusted until usage, message
shape and (for tool calls) the advertised JSON schema have all been checked.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import httpx
from jsonschema.validators import validator_for
from pydantic import BaseModel, SecretStr
from referencing import Registry

from app.agent.llm import (
    NUDGE_TEXT,
    LLMError,
    LoopResult,
    RetryHook,
    Tier,
    ToolDef,
    ToolHandler,
    TurnHook,
    Usage,
    UsageHook,
)

_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_ERRORS = {
    "api_error": "AI provider request failed; check provider configuration and availability.",
    "invalid_output": "AI provider returned an invalid response.",
    "max_tokens": "AI provider output was cut off at the token limit.",
    "refusal": "AI provider declined the request.",
}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Private per-instance snapshot made by a provider's validated settings wrapper.

    The adapter never retains mutable application Settings. Nested rate maps are copied and frozen,
    so concurrent providers cannot accidentally share modified credentials, endpoints or prices.
    """

    label: str
    key: SecretStr | None = field(repr=False)
    base_url: str | None
    strong_model: str
    fast_model: str
    max_tokens: int
    timeout_seconds: float
    max_retries: int
    rates: Mapping[str, Mapping[str, float]]

    def __post_init__(self) -> None:
        if self.key is not None:
            object.__setattr__(self, "key", SecretStr(self.key.get_secret_value()))
        object.__setattr__(
            self,
            "rates",
            MappingProxyType({model: MappingProxyType(dict(rate)) for model, rate in self.rates.items()}),
        )

    @property
    def configured(self) -> bool:
        return bool(self.key and self.base_url and self.strong_model and self.fast_model)


def _error(code: str, usage: Usage | None = None) -> LLMError:
    return LLMError(code, _ERRORS[code], usage=usage)


def _reject_constant(value: str) -> None:
    raise ValueError("Nonfinite JSON number")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Nonfinite JSON number")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _json(value: str | bytes) -> Any:
    # Python accepts NaN/Infinity and duplicate members by default; tool arguments must not.
    valid = False
    result = None
    try:
        result = json.loads(
            value,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            object_pairs_hook=_unique_object,
        )
        valid = True
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    if not valid:
        raise _error("invalid_output")
    return result


def _integer(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise _error("invalid_output")
    return value


def _token_usage(body: dict[str, Any], rates: Mapping[str, float] | None) -> Usage:
    data = body.get("usage")
    if not isinstance(data, dict):
        raise _error("invalid_output")
    prompt = _integer(data.get("prompt_tokens"))
    output = _integer(data.get("completion_tokens"))
    if "total_tokens" in data and _integer(data["total_tokens"]) != prompt + output:
        raise _error("invalid_output")
    prompt_details = data.get("prompt_tokens_details")
    completion_details = data.get("completion_tokens_details")
    if prompt_details is not None and not isinstance(prompt_details, dict):
        raise _error("invalid_output")
    if completion_details is not None and not isinstance(completion_details, dict):
        raise _error("invalid_output")
    cached = _integer((prompt_details or {}).get("cached_tokens", 0))
    reasoning = _integer((completion_details or {}).get("reasoning_tokens", 0))
    if cached > prompt or reasoning > output:
        raise _error("invalid_output")
    # OpenAI totals INCLUDE cached input and reasoning output. Usage input excludes cache reads.
    usage = Usage(input_tokens=prompt - cached, output_tokens=output, cached_tokens=cached, llm_calls=1)
    if rates is not None:
        cost = (
            usage.input_tokens * rates["input"] + output * rates["output"] + cached * rates["cache_read"]
        ) / 1_000_000
        if not math.isfinite(cost):
            raise _error("invalid_output")
        usage.cost_usd = round(cost, 6)
    return usage


def _format_rejected(response: httpx.Response) -> bool:
    """The only compatibility retry: an explicit 400 rejection of response_format itself."""
    if response.status_code != 400:
        return False
    try:
        body = _json(response.content)
    except LLMError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    if error.get("param") == "response_format" and code in {
        "unsupported_parameter",
        "unsupported_value",
        "invalid_parameter",
        "unknown_parameter",
    }:
        return True
    message = error.get("message")
    if not isinstance(message, str):
        return False
    return bool(
        re.search(
            r"(?:response_format.{0,60}(?:not supported|unsupported|not available|unrecognized)|"
            r"(?:unsupported|unrecognized|unknown) (?:parameter[: ]+)?[\"']?response_format)",
            message,
            flags=re.IGNORECASE,
        )
    )


def _choice(body: dict[str, Any]) -> tuple[dict[str, Any], str]:
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise _error("invalid_output")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise _error("invalid_output")
    finish = choice.get("finish_reason")
    if message.get("refusal") or finish in {"content_filter", "refusal"}:
        return message, "refusal"
    if finish == "length":
        return message, "max_tokens"
    if finish not in {"stop", "tool_calls"}:
        raise _error("invalid_output")
    if message.get("content") is not None and not isinstance(message["content"], str):
        raise _error("invalid_output")
    return message, finish


def _messages(system: str, messages: list[Any]) -> list[dict[str, Any]]:
    """Application callers use plain text. Also accept Anthropic-style text/tool history."""
    history: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "tool"}:
            raise _error("invalid_output")
        role, content = message["role"], message.get("content")
        if isinstance(content, str) or (content is None and role == "assistant"):
            history.append(copy.deepcopy(message))
            continue
        if not isinstance(content, list):
            raise _error("invalid_output")
        text: list[str] = []
        calls: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                raise _error("invalid_output")
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                text.append(block["text"])
            elif kind == "tool_use" and role == "assistant":
                calls.append(
                    {
                        "type": "function",
                        "id": block.get("id"),
                        "function": {"name": block.get("name"), "arguments": json.dumps(block.get("input"))},
                    }
                )
            elif kind == "tool_result" and role == "user":
                result = block.get("content")
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id"),
                        "content": result if isinstance(result, str) else json.dumps(result),
                    }
                )
            else:
                raise _error("invalid_output")
        if text or calls:
            turn: dict[str, Any] = {"role": role, "content": "\n".join(text) or None}
            if calls:
                turn["tool_calls"] = calls
            history.append(turn)
        history.extend(results)
    return history


class OpenAICompatibleLLM:
    """Concurrent-safe LLMClient with a closed, ephemeral HTTP client per model request.

    ``transport`` is an offline test seam. All production credentials and endpoints come from
    a provider-specific wrapper; API keys never enter the prompt, logs, or public exception text.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    @property
    def strong_model(self) -> str:
        return self._config.strong_model

    @property
    def fast_model(self) -> str:
        return self._config.fast_model

    def model_for(self, tier: Tier) -> str:
        return self.strong_model if tier == "strong" else self.fast_model

    async def _request(
        self,
        params: dict[str, Any],
        total: Usage,
        *,
        format_fallback: bool = False,
        on_usage: UsageHook | None = None,
    ) -> dict[str, Any] | None:
        config = self._config
        if not config.configured:
            raise _error("api_error")
        assert config.key is not None and config.base_url is not None
        # No redirect, implicit proxy or ambient credentials can change the destination.
        error_code = None
        body = None
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
                timeout=config.timeout_seconds,
                headers={"Authorization": f"Bearer {config.key.get_secret_value()}"},
            ) as client:
                retries = 0
                while True:
                    async with asyncio.timeout(config.timeout_seconds):
                        response = await client.post(
                            config.base_url + "/chat/completions",
                            json=params,
                        )
                    # Successful completions must have valid usage. Error responses often have no
                    # usage; if present, validate and charge it before any retry or compatibility call.
                    body = None
                    try:
                        body = _json(response.content)
                    except LLMError:
                        if response.status_code == 200:
                            raise
                    if response.status_code == 200 or (isinstance(body, dict) and "usage" in body):
                        if not isinstance(body, dict):
                            raise _error("invalid_output")
                        usage = _token_usage(body, config.rates.get(params["model"]))
                        charged = total + usage
                        for key, value in charged.model_dump().items():
                            setattr(total, key, value)
                        if on_usage is not None and not on_usage(usage):
                            return None
                    if format_fallback and _format_rejected(response):
                        params = {k: v for k, v in params.items() if k != "response_format"}
                        format_fallback = False
                        continue
                    if response.status_code not in _RETRYABLE or retries >= config.max_retries:
                        if response.status_code != 200:
                            raise _error("api_error")
                        break
                    await asyncio.sleep(min(0.5 * 2**retries, 4.0))
                    retries += 1
        except LLMError as exc:
            error_code = exc.code
        except Exception:
            # Raise outside the exception handler: no raw provider exception remains in the chain.
            error_code = "api_error"
        if error_code is not None:
            raise _error(error_code, total)
        assert isinstance(body, dict)
        return body

    def _params(self, tier: Tier, history: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": self.model_for(tier),
            "messages": history,
            "max_tokens": self._config.max_tokens,
            "stream": False,
        }

    async def structured(
        self,
        *,
        task: str,
        system: str,
        messages: list[Any],
        schema: type[BaseModel],
        tier: Tier = "strong",
        on_retry: RetryHook | None = None,  # the format fallback retries inside _request: never called
    ) -> tuple[BaseModel, Usage]:
        instruction = "Return only one JSON object, without prose or fences, matching this JSON schema:\n"
        history = _messages(system + "\n\n" + instruction + json.dumps(schema.model_json_schema()), messages)
        usage = Usage()
        body = await self._request(
            {**self._params(tier, history), "response_format": {"type": "json_object"}},
            usage,
            format_fallback=True,
        )
        assert body is not None
        code = "invalid_output"
        result = None
        try:
            message, finish = _choice(body)
            if finish in {"refusal", "max_tokens"}:
                code = finish
            elif not message.get("tool_calls"):
                value = _json(message.get("content"))
                if isinstance(value, dict):
                    result = schema.model_validate(value)
        except Exception:
            pass
        if result is None:
            raise _error(code, usage)
        return result, usage

    async def tool_loop(
        self,
        *,
        task: str,
        system: str,
        messages: list[Any],
        tools: list[ToolDef],
        handler: ToolHandler,
        max_tool_calls: int,
        tier: Tier = "strong",
        on_usage: UsageHook | None = None,
        on_turn: TurnHook | None = None,
    ) -> LoopResult:
        total = Usage()
        error_code = None
        try:
            return await self._tool_loop(
                system,
                messages,
                tools,
                handler,
                max_tool_calls,
                tier,
                on_usage,
                on_turn,
                total,
            )
        except LLMError as exc:
            error_code = exc.code
        except Exception:
            error_code = "invalid_output"
        # The cumulative object is updated in place before parsing or dispatching each response.
        raise _error(error_code, total)

    async def _tool_loop(
        self,
        system: str,
        messages: list[Any],
        tools: list[ToolDef],
        handler: ToolHandler,
        max_tool_calls: int,
        tier: Tier,
        on_usage: UsageHook | None,
        on_turn: TurnHook | None,
        total: Usage,
    ) -> LoopResult:
        if type(max_tool_calls) is not int or max_tool_calls < 0:
            raise _error("invalid_output")
        history = _messages(system, messages)
        validators = {}
        definitions = []
        for tool in tools:
            if tool.name in validators:
                raise _error("invalid_output")
            validator = validator_for(tool.input_schema)
            validator.check_schema(tool.input_schema)
            validators[tool.name] = validator(tool.input_schema, registry=Registry())
            # Local validation is authoritative; don't opt into vendor-specific strict-schema subsets.
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        params = self._params(tier, history)
        if definitions:
            params.update(tools=definitions, tool_choice="auto")
        nudged = False
        last_text = None
        seen_ids: set[str] = set()
        for turn_no in range(1, max_tool_calls + 3):
            if total.tool_calls >= max_tool_calls:
                return LoopResult("tool_limit", total.tool_calls, total, last_text)
            if on_turn is not None:
                await on_turn(turn_no)
            body = await self._request(params, total, on_usage=on_usage)
            if body is None:
                return LoopResult("budget", total.tool_calls, total, last_text)
            message, finish = _choice(body)
            if finish in {"refusal", "max_tokens"}:
                return LoopResult(finish, total.tool_calls, total, last_text)
            last_text = message.get("content") or last_text
            calls = message.get("tool_calls")
            if calls is not None and not isinstance(calls, list):
                raise _error("invalid_output")
            if finish == "tool_calls" and not calls:
                raise _error("invalid_output")
            # Preserve reasoning_content, reasoning_details and tool-call extra_content signatures.
            history.append(copy.deepcopy(message))
            if not calls:
                if nudged:
                    return LoopResult("end_turn", total.tool_calls, total, last_text)
                nudged = True
                history.append({"role": "user", "content": NUDGE_TEXT})
                continue
            # IDs and envelopes must be unambiguous across the entire batch BEFORE any mutation.
            # Bad JSON arguments/unknown names can get a safe tool error; a malformed envelope cannot.
            batch_ids: set[str] = set()
            for call in calls:
                if (
                    not isinstance(call, dict)
                    or call.get("type") != "function"
                    or not isinstance(call.get("id"), str)
                    or not call["id"]
                    or call["id"] in seen_ids
                    or call["id"] in batch_ids
                    or not isinstance(call.get("function"), dict)
                ):
                    total.tool_calls += 1
                    raise _error("invalid_output")
                batch_ids.add(call["id"])
            seen_ids.update(batch_ids)
            for call in calls:
                if total.tool_calls >= max_tool_calls:
                    return LoopResult("tool_limit", total.tool_calls, total, last_text)
                total.tool_calls += 1  # invalid attempts consume the same finite budget
                call_id = call["id"]
                function = call["function"]
                name = function.get("name")
                args = None
                valid = False
                try:
                    args = _json(function.get("arguments"))
                    valid = (
                        isinstance(name, str)
                        and name in validators
                        and isinstance(args, dict)
                        and validators[name].is_valid(args)
                    )
                except Exception:
                    pass
                stopped = False
                content = '{"ok":false,"error":"Invalid tool name or arguments."}'
                if valid:
                    try:
                        outcome = await handler(name, args)
                        stopped = outcome.stop
                        content = (
                            outcome.content
                            if isinstance(outcome.content, str)
                            else json.dumps(outcome.content, ensure_ascii=False, allow_nan=False)
                        )
                    except Exception:
                        # Handlers may fail with sensitive inputs; send only static errors to the model.
                        content = '{"ok":false,"error":"Internal tool error."}'
                if stopped:
                    return LoopResult("finished", total.tool_calls, total, last_text)
                history.append({"role": "tool", "tool_call_id": call_id, "content": content})
        return LoopResult("tool_limit", total.tool_calls, total, last_text)
