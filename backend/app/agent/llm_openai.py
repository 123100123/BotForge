"""``LLMClient`` over an ordered chain of OpenAI chat-completions compatible endpoints.

Selected with ``LLM_PROVIDER=openai`` (``app.agent.llm.make_llm``). Built for endpoints that speak
only ``POST {base_url}/chat/completions`` (a gateway such as https://top-tools-ai.com/v1, Gemini's
compatibility endpoint), over plain ``httpx``. The phases see the same semantics as with
``AnthropicLLM``:

- ``tool_loop``: tools are sent as ``{"type": "function", ...}`` with ``tool_choice="auto"``; the
  assistant message (with its ``tool_calls``) is appended to the history and every call gets one
  ``role: tool`` message with its ``tool_call_id``. Several calls per turn run in order through the
  shared ``_run_tool_turn`` (tool-call limit and ``LIMIT_TEXT`` included). Tool arguments arrive as
  JSON strings: invalid JSON is not executed, the error goes back to the model as that call's
  result (it still counts toward the limit). ``finish_reason="length"`` -> ``max_tokens``;
  ``content_filter`` or a ``refusal`` field -> ``refusal``; a turn without tool calls is nudged once
  (``NUDGE_TEXT``), then ``end_turn``. The usage hook runs after every response (``budget``).
- ``structured``: ``response_format`` json_schema (``strict: false``: the BotSpec schema is too
  complex for strict mode), validated with the Pydantic model; invalid or missing JSON is retried
  once with the validation error appended. An endpoint that rejects the request shape (HTTP 400 or
  422) gets a forced single tool call whose parameters are the schema, then a plain JSON
  instruction. JSON is always read with ``_extract_json`` (tolerates prose or code fences).
- No prompt caching, no ``fallbacks``, no thinking or effort parameters.

Reliability, per model call:

1. On one endpoint, HTTP 429 / 5xx / 408 / 409 / 425, a body with ``"retryable": true``, timeouts and
   connection errors are retried up to ``max_retries`` times (exponential backoff with jitter,
   ``Retry-After`` honored up to the cap). 400/401/402/403/404/422 and quota errors are never retried.
   An empty assistant message (no content, no tool calls) is retried once.
2. If the endpoint still fails (auth, quota, unknown model, retries exhausted, request rejected in
   every structured mode, empty or invalid output after its retry), the call moves to the next
   endpoint. History is plain chat format, so a run may switch endpoints between calls. Refusals and
   ``max_tokens`` are model outcomes, not endpoint failures, and do not fail over.
3. An endpoint that failed with auth / quota / unknown-model / rate-limit errors is skipped for
   ``cooldown_seconds`` (in process) while another endpoint is available.
4. ``LLMError`` is raised only when every endpoint failed; its code is the last endpoint's, its
   message lists each endpoint's failure (never a key). Usage accumulates across endpoints.

API keys go only into the ``Authorization`` header; logs and errors name endpoints by settings
prefix and host.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from app.agent.llm import (
    NUDGE_TEXT,
    PROVIDER_OWNER_MESSAGES,
    LLMError,
    LoopResult,
    Tier,
    ToolDef,
    ToolHandler,
    ToolOutcome,
    Usage,
    UsageHook,
    _extract_json,
    _run_tool_turn,
    _ToolUse,
)

log = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "Qwen-3.8-Max"  # the only top-tools-ai model that passed the tool-calling probe
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"  # used for a Gemini endpoint without LLM_n_MODEL_STRONG
GEMINI_HOST = "generativelanguage.googleapis.com"
MAX_INDEXED_ENDPOINTS = 5

# Never retried on the same endpoint: the same request would fail the same way.
NO_RETRY_STATUSES = frozenset({400, 401, 402, 403, 404, 422})
RETRY_STATUSES = frozenset({408, 409, 425, 429})
QUOTA_ERROR_CODES = frozenset({"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached"})
COOLDOWN_CODES = frozenset({"llm_auth", "llm_quota", "llm_not_found", "llm_rate_limited"})
MODEL_OUTCOMES = frozenset({"refusal", "max_tokens"})  # final: no failover
STRUCTURED_MODES = ("response_format", "tool", "text")
EMPTY_RESPONSE = "empty_response"

STRUCTURED_RETRY_TEXT = (
    "Your previous answer was not valid JSON for the required schema:\n{error}\n"
    "Return only the corrected JSON object (no prose, no code fences)."
)
TEXT_MODE_INSTRUCTION = (
    "Return only one JSON object (no prose, no code fences) that validates against this JSON schema:\n"
)


def provider_error(code: str, message: str, usage: Usage | None = None) -> LLMError:
    return LLMError(code, message, usage=usage, owner_message=PROVIDER_OWNER_MESSAGES.get(code))


@dataclass(frozen=True)
class Endpoint:
    """One OpenAI-compatible endpoint. ``name`` is its settings prefix (``LLM_1``, ``LLM``)."""

    name: str
    base_url: str
    api_key: str = field(repr=False)
    strong_model: str = DEFAULT_OPENAI_MODEL
    fast_model: str | None = None

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or self.base_url

    @property
    def label(self) -> str:
        return f"{self.name} ({self.host})"

    def model_for(self, tier: Tier) -> str:
        return self.strong_model if tier == "strong" else (self.fast_model or self.strong_model)


def endpoints_from_settings(settings: Any) -> tuple[list[Endpoint], list[str]]:
    """The endpoint chain from settings: ``LLM_1_*`` .. ``LLM_5_*`` (stopping at the first index
    without a BASE_URL), then the plain ``LLM_*`` endpoint last. Returns (endpoints, problems);
    an entry with a problem is left out of the chain."""

    def text(name: str) -> str:
        value = getattr(settings, name, None)
        if value is not None and hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        return (value or "").strip()

    entries: list[tuple[str, str, str, str, str]] = []
    for n in range(1, MAX_INDEXED_ENDPOINTS + 1):
        p = f"LLM_{n}"
        if not text(f"{p}_BASE_URL"):
            break
        entries.append(
            (
                p,
                text(f"{p}_BASE_URL"),
                text(f"{p}_API_KEY"),
                text(f"{p}_MODEL_STRONG"),
                text(f"{p}_MODEL_FAST"),
            )
        )
    if text("LLM_BASE_URL") or text("LLM_API_KEY"):
        entries.append(
            (
                "LLM",
                text("LLM_BASE_URL"),
                text("LLM_API_KEY"),
                text("LLM_MODEL_STRONG"),
                text("LLM_MODEL_FAST"),
            )
        )

    endpoints: list[Endpoint] = []
    problems: list[str] = []
    for prefix, base_url, key, strong, fast in entries:
        if not base_url:
            problems.append(f"{prefix}_API_KEY is set but {prefix}_BASE_URL is not")
            continue
        if not base_url.lower().startswith(("https://", "http://")):
            problems.append(f"{prefix}_BASE_URL must start with https:// (got a value without a scheme)")
            continue
        if not key:
            problems.append(f"{prefix}_API_KEY is not set")
            continue
        if not strong:
            gemini = (urlsplit(base_url).hostname or "") == GEMINI_HOST
            strong = DEFAULT_GEMINI_MODEL if gemini else DEFAULT_OPENAI_MODEL
            log.warning("%s_MODEL_STRONG is not set; using %s", prefix, strong)
        endpoints.append(Endpoint(prefix, base_url.rstrip("/"), key, strong, fast or None))
    return endpoints, problems


class _BadArguments(dict[str, Any]):
    """Tool arguments that could not be parsed; the handler is not called, the error is returned."""

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _content_text(content: Any) -> str:
    """Text of a message content: a string, or a list of text parts (either API's shape)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type", "text") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            elif getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return "\n".join(parts)
    return str(content)


def _to_openai(system: str, messages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        out.append(
            {"role": role if role in ("user", "assistant") else "user", "content": _content_text(content)}
        )
    return out


def _tool_to_openai(tool: ToolDef) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": tool.input_schema},
    }


def _schema_name(schema: type[BaseModel]) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", schema.__name__)[:64] or "result"


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if not isinstance(raw, str):
        return _BadArguments(f"tool arguments must be a JSON object, got {type(raw).__name__}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _BadArguments(
            f"invalid JSON in tool arguments ({exc.msg} at position {exc.pos}); "
            "call the tool again with one valid JSON object"
        )
    if not isinstance(value, dict):
        return _BadArguments("tool arguments must be a JSON object")
    return value


def _stop_of(message: dict[str, Any], finish: str | None) -> str | None:
    if finish == "content_filter" or message.get("refusal"):
        return "refusal"
    if finish == "length":
        return "max_tokens"
    return None


def _is_empty(message: dict[str, Any]) -> bool:
    return not (_content_text(message.get("content")).strip() or message.get("tool_calls"))


def _error_of(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:  # some endpoints wrap the error object in a list
        data = data[0]
    if not isinstance(data, dict):
        return {}
    err = data.get("error")
    if isinstance(err, dict):
        return err
    if isinstance(err, str):
        return {"message": err}
    return {}


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


@dataclass
class _Failure:
    endpoint: Endpoint
    code: str
    detail: str


class OpenAICompatLLM:
    """``LLMClient`` over an endpoint chain. One instance serves many concurrent runs."""

    def __init__(
        self,
        *,
        endpoints: Sequence[Endpoint] | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        strong_model: str | None = None,
        fast_model: str | None = None,
        timeout: float = 180.0,
        max_retries: int = 4,
        max_tokens: int = 16384,
        price_input_per_m: float = 0.0,
        price_output_per_m: float = 0.0,
        cooldown_seconds: float = 60.0,
        log_bodies: bool = False,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        backoff_base: float = 2.0,
        backoff_cap: float = 30.0,
    ) -> None:
        chain = list(endpoints or [])
        if base_url or api_key:  # a single endpoint given directly
            if not base_url or not api_key:
                raise ValueError("OpenAICompatLLM needs both base_url and api_key")
            chain.append(
                Endpoint(
                    "LLM",
                    base_url.strip().rstrip("/"),
                    api_key,
                    strong_model or DEFAULT_OPENAI_MODEL,
                    fast_model,
                )
            )
        if not chain:
            raise ValueError("OpenAICompatLLM needs at least one endpoint")
        self.endpoints = chain
        self.max_retries = max(max_retries, 0)
        self.max_tokens = max_tokens
        self.price_input_per_m = price_input_per_m
        self.price_output_per_m = price_output_per_m
        self.cooldown_seconds = cooldown_seconds
        self.log_bodies = log_bodies
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 15.0))
        self._client = http_client  # created lazily
        self._sleep = sleep
        self._clock = clock
        self._cooling: dict[str, float] = {}  # endpoint name -> monotonic time it may be used again
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    def __repr__(self) -> str:  # never a key
        return f"OpenAICompatLLM({self.describe()})"

    def describe(self) -> str:
        return ", ".join(f"{e.label} model={e.strong_model}" for e in self.endpoints)

    # Shown by scripts (eval_golden, spike) like AnthropicLLM's attributes.
    @property
    def strong_model(self) -> str:
        return self.endpoints[0].strong_model

    @property
    def fast_model(self) -> str:
        return self.endpoints[0].model_for("fast")

    # ------------------------------------------------------------------ endpoint chain

    def _order(self) -> list[Endpoint]:
        """The chain without endpoints in cool-down; the whole chain if every one is cooling down."""
        now = self._clock()
        ready = [e for e in self.endpoints if self._cooling.get(e.name, 0.0) <= now]
        return ready or list(self.endpoints)

    def _failed(self, failures: list[_Failure], endpoint: Endpoint, code: str, detail: str) -> None:
        failures.append(_Failure(endpoint, code, detail))
        if code in COOLDOWN_CODES and len(self.endpoints) > 1:
            self._cooling[endpoint.name] = self._clock() + self.cooldown_seconds
        if len(self.endpoints) > 1:
            log.warning("llm endpoint %s failed with %s; trying the next endpoint", endpoint.label, code)

    def _all_failed(self, failures: list[_Failure], usage: Usage) -> LLMError:
        last = failures[-1].code
        code = "invalid_output" if last == EMPTY_RESPONSE else last
        summary = "; ".join(f"{f.endpoint.label}: {f.code} {f.detail}".strip() for f in failures)
        message = summary if len(failures) == 1 else f"all {len(failures)} LLM endpoints failed: {summary}"
        return LLMError(code, message[:2000], usage=usage, owner_message=PROVIDER_OWNER_MESSAGES.get(code))

    # ------------------------------------------------------------------ HTTP, one endpoint

    def _scrub(self, text: str) -> str:
        for endpoint in self.endpoints:
            text = text.replace(endpoint.api_key, "***")
        return text

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        ceiling = min(self.backoff_cap, self.backoff_base * (2**attempt))
        delay = ceiling / 2 + random.uniform(0, ceiling / 2)
        if retry_after is not None:
            delay = max(delay, min(retry_after, self.backoff_cap))
        return delay

    async def _post(self, task: str, endpoint: Endpoint, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """POST with the retry policy; returns the response JSON (with ``choices``) and attempts used."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        url = f"{endpoint.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {endpoint.api_key}", "Content-Type": "application/json"}
        attempts = self.max_retries + 1
        reason = "no attempt"
        rate_limited = False
        for attempt in range(attempts):
            retry_after: float | None = None
            try:
                response = await self._client.post(url, json=body, headers=headers, timeout=self._timeout)
            except httpx.TimeoutException as exc:
                reason, rate_limited = f"timeout ({type(exc).__name__})", False
            except httpx.TransportError as exc:
                reason, rate_limited = f"connection error ({type(exc).__name__})", False
            else:
                status = response.status_code
                try:
                    data: Any = response.json()
                except ValueError:
                    data = None
                if 200 <= status < 300 and isinstance(data, dict) and data.get("choices"):
                    return data, attempt + 1
                err = _error_of(data)
                err_code = str(err.get("code") or err.get("type") or err.get("status") or "")
                detail = self._scrub(str(err.get("message") or (response.text if data is None else ""))[:300])
                if status in NO_RETRY_STATUSES or err_code.lower() in QUOTA_ERROR_CODES:
                    if status == 402 or err_code.lower() in QUOTA_ERROR_CODES:
                        code = "llm_quota"
                    elif status in (401, 403):
                        code = "llm_auth"
                    elif status == 404:
                        code = "llm_not_found"
                    else:
                        code = "llm_bad_request"
                    log.warning(
                        "llm call failed task=%s endpoint=%s model=%s status=%d error_code=%s (not retried)",
                        task,
                        endpoint.label,
                        body.get("model"),
                        status,
                        err_code or "-",
                    )
                    raise provider_error(code, f"HTTP {status} {err_code}: {detail}".strip())
                if 200 <= status < 300 or status in RETRY_STATUSES or status >= 500 or err.get("retryable"):
                    reason = f"HTTP {status} {err_code or ('no choices' if status < 300 else '')}".strip()
                    rate_limited = status == 429
                    retry_after = _retry_after(response)
                else:  # e.g. 405 or 413: a request problem, not a transient one
                    raise provider_error("llm_bad_request", f"HTTP {status} {err_code}: {detail}".strip())
            if attempt + 1 < attempts:
                delay = self._delay(attempt, retry_after)
                log.warning(
                    "llm call retry task=%s endpoint=%s attempt=%d/%d reason=%s wait_s=%.1f",
                    task,
                    endpoint.label,
                    attempt + 1,
                    attempts,
                    reason,
                    delay,
                )
                await self._sleep(delay)
        log.warning(
            "llm call gave up task=%s endpoint=%s attempts=%d reason=%s",
            task,
            endpoint.label,
            attempts,
            reason,
        )
        code = "llm_rate_limited" if rate_limited else "llm_unavailable"
        raise provider_error(code, f"gave up after {attempts} attempts: {reason}")

    def _usage(self, data: dict[str, Any]) -> Usage:
        u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        prompt = _int(u.get("prompt_tokens"))
        details = u.get("prompt_tokens_details")
        cached = min(_int(details.get("cached_tokens")), prompt) if isinstance(details, dict) else 0
        completion = _int(u.get("completion_tokens"))
        usage = Usage(
            input_tokens=prompt - cached, output_tokens=completion, cached_tokens=cached, llm_calls=1
        )
        usage.cost_usd = round(
            (prompt * self.price_input_per_m + completion * self.price_output_per_m) / 1_000_000, 6
        )
        return usage

    async def _chat(
        self, task: str, endpoint: Endpoint, tier: Tier, body: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None, Usage]:
        """One completion on one endpoint: (assistant message, finish_reason, usage). An empty
        answer is retried once; a second empty answer is returned as is (callers decide)."""
        body = {**body, "model": endpoint.model_for(tier)}
        total = Usage()
        for retry in (False, True):
            if self.log_bodies:
                log.info(
                    "llm request task=%s body=%s", task, json.dumps(body, ensure_ascii=False, default=str)
                )
            started = time.perf_counter()
            try:
                data, attempts = await self._post(task, endpoint, body)
            except LLMError as exc:
                exc.usage = total + exc.usage
                raise
            usage = self._usage(data)
            total = total + usage
            choice = data["choices"][0] if isinstance(data["choices"], list) else {}
            choice = choice if isinstance(choice, dict) else {}
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            finish = choice.get("finish_reason")
            log.info(
                "llm call task=%s endpoint=%s model=%s served_by=%s in=%d out=%d cache_read=%d "
                "duration_ms=%d attempts=%d stop=%s",
                task,
                endpoint.label,
                body["model"],
                data.get("model"),
                usage.input_tokens,
                usage.output_tokens,
                usage.cached_tokens,
                int((time.perf_counter() - started) * 1000),
                attempts,
                finish,
            )
            if self.log_bodies:
                log.info("llm response task=%s body=%s", task, json.dumps(data, ensure_ascii=False))
            if _is_empty(message) and _stop_of(message, finish) is None and not retry:
                log.warning(
                    "llm empty assistant message task=%s endpoint=%s; retrying once", task, endpoint.label
                )
                continue
            return message, finish, total
        raise AssertionError("unreachable")

    async def complete(
        self, task: str, tier: Tier, body: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None, Usage, Endpoint]:
        """One completion over the chain (body without ``model``): message, finish, usage, endpoint."""
        total = Usage()
        failures: list[_Failure] = []
        order = self._order()
        for i, endpoint in enumerate(order):
            try:
                message, finish, usage = await self._chat(task, endpoint, tier, body)
            except LLMError as exc:
                total = total + exc.usage
                self._failed(failures, endpoint, exc.code, exc.message)
                continue
            total = total + usage
            if _is_empty(message) and _stop_of(message, finish) is None and i + 1 < len(order):
                self._failed(failures, endpoint, EMPTY_RESPONSE, "")
                continue
            return message, finish, total, endpoint
        raise self._all_failed(failures, total)

    # ------------------------------------------------------------------ structured

    async def structured(
        self,
        *,
        task: str,
        system: str,
        messages: list[Any],
        schema: type[BaseModel],
        tier: Tier = "strong",
    ) -> tuple[BaseModel, Usage]:
        base = _to_openai(system, messages)
        total = Usage()
        failures: list[_Failure] = []
        for endpoint in self._order():
            try:
                result, used = await self._structured_on(task, endpoint, tier, base, schema)
            except LLMError as exc:
                total = total + exc.usage
                if exc.code in MODEL_OUTCOMES:
                    exc.usage = total
                    raise
                self._failed(failures, endpoint, exc.code, exc.message)
                continue
            return result, total + used
        raise self._all_failed(failures, total)

    async def _structured_on(
        self, task: str, endpoint: Endpoint, tier: Tier, base: list[dict[str, Any]], schema: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        """Every structured mode on one endpoint; the next mode only when the request is rejected."""
        total = Usage()
        for mode in STRUCTURED_MODES:
            try:
                result, used = await self._structured_mode(task, endpoint, tier, mode, base, schema)
            except LLMError as exc:
                total = total + exc.usage
                if exc.code == "llm_bad_request" and mode != STRUCTURED_MODES[-1]:
                    log.warning(
                        "structured mode %s rejected task=%s endpoint=%s; trying the next mode",
                        mode,
                        task,
                        endpoint.label,
                    )
                    continue
                exc.usage = total
                raise
            return result, total + used
        raise AssertionError("unreachable")

    async def _structured_mode(
        self,
        task: str,
        endpoint: Endpoint,
        tier: Tier,
        mode: str,
        base: list[dict[str, Any]],
        schema: type[BaseModel],
    ) -> tuple[BaseModel, Usage]:
        json_schema = schema.model_json_schema()
        name = _schema_name(schema)
        history = list(base)
        if mode == "text":
            history.append(
                {
                    "role": "user",
                    "content": TEXT_MODE_INSTRUCTION + json.dumps(json_schema, ensure_ascii=False),
                }
            )
        total = Usage()
        error = ""
        for attempt in range(2):
            body: dict[str, Any] = {"messages": history, "max_tokens": self.max_tokens}
            if mode == "response_format":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": json_schema, "strict": False},
                }
            elif mode == "tool":
                body["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": "Return the result as this function's arguments.",
                            "parameters": json_schema,
                        },
                    }
                ]
                body["tool_choice"] = {"type": "function", "function": {"name": name}}
            try:
                message, finish, usage = await self._chat(task, endpoint, tier, body)
            except LLMError as exc:
                exc.usage = total + exc.usage
                raise
            total = total + usage
            stop = _stop_of(message, finish)
            if stop == "refusal":
                raise LLMError("refusal", f"model declined (finish_reason={finish})", usage=total)
            if stop == "max_tokens":
                raise LLMError("max_tokens", "output was cut off at max_tokens", usage=total)
            raw = _content_text(message.get("content"))
            calls = message.get("tool_calls") or []
            if mode == "tool" and calls and isinstance(calls[0], dict):
                args = (calls[0].get("function") or {}).get("arguments")
                raw = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            try:
                return schema.model_validate(_extract_json(raw)), total
            except (json.JSONDecodeError, ValidationError) as exc:
                error = str(exc)[:2000]
            if attempt == 0:
                log.warning(
                    "structured output invalid task=%s endpoint=%s mode=%s; retrying once",
                    task,
                    endpoint.label,
                    mode,
                )
                history = [
                    *history,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": STRUCTURED_RETRY_TEXT.format(error=error[:1500])},
                ]
        raise LLMError("invalid_output", error, usage=total)

    # ------------------------------------------------------------------ tool loop

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
    ) -> LoopResult:
        history = _to_openai(system, messages)
        api_tools = [_tool_to_openai(t) for t in tools]
        total = Usage()
        state = {"calls": 0}
        nudged = False
        last_text: str | None = None
        counter = 0

        async def guarded(name: str, args: dict[str, Any]) -> ToolOutcome:
            if isinstance(args, _BadArguments):
                return ToolOutcome({"ok": False, "error": args.error}, is_error=True)
            return await handler(name, args)

        while True:
            body = {
                "messages": history,
                "max_tokens": self.max_tokens,
                "tools": api_tools,
                "tool_choice": "auto",
            }
            message, finish, usage, _ = await self.complete(task, tier, body)
            total = total + usage
            if on_usage is not None and not on_usage(usage):
                return LoopResult("budget", state["calls"], total, last_text)
            stop = _stop_of(message, finish)
            if stop == "refusal":
                return LoopResult("refusal", state["calls"], total, last_text)
            if stop == "max_tokens":
                return LoopResult("max_tokens", state["calls"], total, last_text)
            text = _content_text(message.get("content"))
            last_text = text or last_text
            uses: list[_ToolUse] = []
            replay: list[dict[str, Any]] = []
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                counter += 1
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                call_id = str(call.get("id") or f"call_{counter}")
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments")
                uses.append(_ToolUse(call_id, name, _parse_arguments(raw_args)))
                replay.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": raw_args
                            if isinstance(raw_args, str)
                            else json.dumps(raw_args or {}),
                        },
                    }
                )
            assistant: dict[str, Any] = {"role": "assistant", "content": text}
            if replay:
                assistant["tool_calls"] = replay
                assistant["content"] = text or None
            history.append(assistant)
            if not uses:
                if nudged:
                    return LoopResult("end_turn", state["calls"], total, last_text)
                nudged = True
                history.append({"role": "user", "content": NUDGE_TEXT})
                continue
            turn = await _run_tool_turn(uses, guarded, state, max_tool_calls)
            total.tool_calls = state["calls"]
            if turn.finished:
                return LoopResult("finished", state["calls"], total, last_text)
            if turn.limit_hit:
                return LoopResult("tool_limit", state["calls"], total, last_text)
            history.extend(
                {"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]}
                for r in turn.results
            )
