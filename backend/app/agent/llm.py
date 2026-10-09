"""LLM boundary for the agent (roadmap: "LLM Strategy").

``LLMClient`` is the only way phases reach a model. Three implementations:

- ``AnthropicLLM``: the official async ``anthropic`` SDK. Streaming requests (``get_final_message``),
  a cached system prefix, adaptive thinking with per-task effort, structured output through
  ``output_config.format`` (schema prepared with ``anthropic.transform_schema``), tools with
  ``tool_choice`` left at ``auto`` (forced tool use is rejected by current models), server-side
  refusal fallback (``fallbacks="default"``), and ``stop_reason`` checked before content is read.
- ``ClaudeCodeLLM`` (``llm_claude_code.py``): headless Claude Code through ``claude-agent-sdk`` with the
  developer's Claude Code login, for local development and live evals (``LLM_PROVIDER=claude_cli``).
- ``FakeLLM``: scripted structured results and scripted tool-call turns. Every automated test uses it.

``make_llm()`` returns the client selected by ``LLM_PROVIDER``.

The tool loop is append-only: assistant turns (thinking blocks included) go back unchanged, tool
results are appended as one user message per turn. ``tool_loop`` enforces ``max_tool_calls`` and
returns why it stopped; it never raises for a model that misbehaves inside the loop.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

Tier = Literal["strong", "fast"]
StopReason = Literal["finished", "tool_limit", "end_turn", "max_tokens", "refusal", "budget"]

DEFAULT_STRONG_MODEL = "claude-opus-5-5"
DEFAULT_FAST_MODEL = "claude-haiku-4-5"

# Effort per task (roadmap: medium for build and understand, high for repair). Models that do not
# accept ``effort`` (Haiku 4.5) get none.
TASK_EFFORT: dict[str, str] = {
    "understand": "medium",
    "build": "medium",
    "testgen": "medium",
    "repair": "high",
    "sample_data": "low",
    "triage": "low",
    "spike": "medium",
}

# Models that accept the server-side refusal fallback (``fallbacks="default"``).
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: input, output, cache read, cache write (5-minute TTL).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-8": (5.0, 25.0, 0.50, 6.25),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
}

NUDGE_TEXT = "Continue with the tools. When the work is complete, call the finish tool."
LIMIT_TEXT = "Tool call limit reached for this phase; the call was not executed."


class Usage(BaseModel):
    """Token and call accounting. ``cached_tokens`` are cache reads; ``cache_write_tokens`` writes."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            tool_calls=self.tool_calls + other.tool_calls,
            llm_calls=self.llm_calls + other.llm_calls,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
        )

    @property
    def billable_input(self) -> int:
        """Input counted against the run budget: uncached input plus cache writes (reads are ~0.1x)."""
        return self.input_tokens + self.cache_write_tokens


def cost_of(model: str, usage: Usage) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    p_in, p_out, p_read, p_write = price
    return round(
        (
            usage.input_tokens * p_in
            + usage.output_tokens * p_out
            + usage.cached_tokens * p_read
            + usage.cache_write_tokens * p_write
        )
        / 1_000_000,
        6,
    )


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    strict: bool = False  # only where the schema is strict-compatible (no free-form values)

    def to_api(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        if self.strict:
            out["strict"] = True
        return out


@dataclass
class ToolOutcome:
    """What a tool handler returns: a JSON-serializable result; ``stop`` ends the loop (finish)."""

    content: Any
    is_error: bool = False
    stop: bool = False


ToolHandler = Callable[[str, dict[str, Any]], Awaitable[ToolOutcome]]
UsageHook = Callable[[Usage], bool]  # called after every model response; False stops the loop
TurnHook = Callable[[int], Awaitable[None]]  # awaited before each model call of a loop; 1-based turn
RetryHook = Callable[[str], Awaitable[None]]  # awaited before the client retries a call; Persian reason

PLAIN_JSON_RETRY_REASON = "ساختار خروجی مدل پذیرفته نشد؛ دوباره با قالب ساده تلاش می‌کنم."


@dataclass
class LoopResult:
    stop_reason: StopReason
    tool_calls: int
    usage: Usage
    text: str | None = None  # last assistant text, if any


class LLMError(Exception):
    """A model call that produced no usable result.

    code: refusal | max_tokens | invalid_output | api_error
    """

    def __init__(self, code: str, message: str, *, usage: Usage | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.usage = usage or Usage()


class LLMClient(Protocol):
    async def structured(
        self,
        *,
        task: str,
        system: str,
        messages: list[Any],
        schema: type[BaseModel],
        tier: Tier = "strong",
        on_retry: RetryHook | None = None,
    ) -> tuple[BaseModel, Usage]: ...

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
    ) -> LoopResult: ...


# --------------------------------------------------------------------------- shared loop logic


@dataclass
class _ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class _TurnResult:
    results: list[dict[str, Any]]
    finished: bool
    limit_hit: bool


def _dumps(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _run_tool_turn(
    uses: list[_ToolUse], handler: ToolHandler, state: dict[str, int], limit: int
) -> _TurnResult:
    """Execute one assistant turn's tool calls in order, honoring the tool-call limit."""
    results: list[dict[str, Any]] = []
    finished = limit_hit = False
    for use in uses:
        if state["calls"] >= limit:
            limit_hit = True
            results.append(
                {"type": "tool_result", "tool_use_id": use.id, "content": LIMIT_TEXT, "is_error": True}
            )
            continue
        state["calls"] += 1
        try:
            outcome = await handler(use.name, use.input)
        except Exception as exc:  # a handler bug must not kill the loop silently
            log.exception("tool handler failed: %s", use.name)
            outcome = ToolOutcome({"ok": False, "error": f"internal tool error: {type(exc).__name__}"}, True)
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": use.id,
                "content": _dumps(outcome.content),
                "is_error": outcome.is_error,
            }
        )
        finished = finished or outcome.stop
    return _TurnResult(results, finished, limit_hit)


# --------------------------------------------------------------------------- Anthropic


def _block_text(content: list[Any]) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")


def _extract_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


class AnthropicLLM:
    """``LLMClient`` over the official async SDK. One instance can serve many concurrent runs."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        strong_model: str | None = None,
        fast_model: str | None = None,
        log_bodies: bool | None = None,
        max_tokens: int = 32000,
    ) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._client = client  # created lazily, so the app boots without an API key
        self._api_key = settings.ANTHROPIC_API_KEY or None
        self.strong_model = strong_model or settings.LLM_MODEL_STRONG or DEFAULT_STRONG_MODEL
        self.fast_model = fast_model or settings.LLM_MODEL_FAST or DEFAULT_FAST_MODEL
        self.log_bodies = settings.LOG_LLM_BODIES if log_bodies is None else log_bodies
        self.max_tokens = max_tokens

    def model_for(self, tier: Tier) -> str:
        return self.strong_model if tier == "strong" else self.fast_model

    def _params(self, task: str, tier: Tier, system: str, messages: list[Any]) -> dict[str, Any]:
        model = self.model_for(tier)
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            # Identical across calls, so the tools + system prefix is cached.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
        }
        output_config: dict[str, Any] = {}
        if not model.startswith("claude-haiku"):  # Haiku 4.5 rejects effort; thinking stays default
            params["thinking"] = {"type": "adaptive"}
            effort = TASK_EFFORT.get(task)
            if effort:
                output_config["effort"] = effort
        if output_config:
            params["output_config"] = output_config
        if model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def _call(self, task: str, params: dict[str, Any]) -> tuple[Any, Usage]:
        import anthropic

        if self.log_bodies:
            log.info("llm request task=%s body=%s", task, json.dumps(params, ensure_ascii=False, default=str))
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key, max_retries=3)
        started = time.perf_counter()
        try:
            async with self._client.beta.messages.stream(**params) as stream:
                message = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            log.warning(
                "llm call failed task=%s status=%s request_id=%s",
                task,
                exc.status_code,
                getattr(exc, "request_id", None),
            )
            raise
        except anthropic.APIConnectionError:
            log.warning("llm connection error task=%s", task)
            raise
        u = message.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cached_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
            llm_calls=1,
        )
        usage.cost_usd = cost_of(message.model, usage)
        log.info(
            "llm call task=%s model=%s served_by=%s in=%d out=%d cache_read=%d cache_write=%d "
            "duration_ms=%d stop=%s",
            task,
            params["model"],
            message.model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cached_tokens,
            usage.cache_write_tokens,
            int((time.perf_counter() - started) * 1000),
            message.stop_reason,
        )
        if self.log_bodies:
            log.info("llm response task=%s body=%s", task, message.to_json())
        return message, usage

    async def structured(
        self,
        *,
        task: str,
        system: str,
        messages: list[Any],
        schema: type[BaseModel],
        tier: Tier = "strong",
        on_retry: RetryHook | None = None,
    ) -> tuple[BaseModel, Usage]:
        import anthropic

        params = self._params(task, tier, system, messages)
        json_schema = anthropic.transform_schema(schema.model_json_schema())
        params["output_config"] = {
            **params.get("output_config", {}),
            "format": {"type": "json_schema", "schema": json_schema},
        }
        try:
            message, usage = await self._call(task, params)
        except anthropic.BadRequestError as exc:
            # A schema the structured-output compiler rejects (too complex): ask for JSON in text.
            if "schema" not in str(exc).lower():
                raise
            log.warning("structured output rejected for task=%s; retrying with a JSON instruction", task)
            if on_retry is not None:
                await on_retry(PLAIN_JSON_RETRY_REASON)
            params["output_config"].pop("format", None)
            if not params["output_config"]:
                params.pop("output_config")
            params["messages"] = [
                *messages,
                {
                    "role": "user",
                    "content": "Return only one JSON object (no prose, no code fences) that validates "
                    "against this JSON schema:\n" + json.dumps(json_schema, ensure_ascii=False),
                },
            ]
            message, usage = await self._call(task, params)
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None)
            raise LLMError("refusal", f"model declined (category={category})", usage=usage)
        if message.stop_reason == "max_tokens":
            raise LLMError("max_tokens", "output was cut off at max_tokens", usage=usage)
        text = _block_text(message.content)
        try:
            return schema.model_validate(_extract_json(text)), usage
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError("invalid_output", str(exc)[:2000], usage=usage) from None

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
        history: list[Any] = list(messages)
        params = self._params(task, tier, system, history)
        params["tools"] = [t.to_api() for t in tools]  # deterministic order: part of the cached prefix
        # Automatic caching of the growing loop history (the system block carries its own breakpoint).
        params["cache_control"] = {"type": "ephemeral"}
        total = Usage()
        state = {"calls": 0}
        nudged = False
        last_text: str | None = None
        turn_no = 0
        while True:
            turn_no += 1
            if on_turn is not None:
                await on_turn(turn_no)
            message, usage = await self._call(task, {**params, "messages": history})
            total = total + usage
            if on_usage is not None and not on_usage(usage):
                return LoopResult("budget", state["calls"], total, last_text)
            if message.stop_reason == "refusal":
                return LoopResult("refusal", state["calls"], total, last_text)
            if message.stop_reason == "max_tokens":
                return LoopResult("max_tokens", state["calls"], total, last_text)
            text = _block_text(message.content)
            last_text = text or last_text
            history.append({"role": "assistant", "content": message.content})  # unchanged, thinking incl.
            if message.stop_reason == "pause_turn":
                continue
            uses = [
                _ToolUse(b.id, b.name, b.input if isinstance(b.input, dict) else {})
                for b in message.content
                if getattr(b, "type", None) == "tool_use"
            ]
            if not uses:
                if nudged:
                    return LoopResult("end_turn", state["calls"], total, last_text)
                nudged = True
                history.append({"role": "user", "content": NUDGE_TEXT})
                continue
            turn = await _run_tool_turn(uses, handler, state, max_tool_calls)
            total.tool_calls = state["calls"]
            if turn.finished:
                return LoopResult("finished", state["calls"], total, last_text)
            if turn.limit_hit:
                return LoopResult("tool_limit", state["calls"], total, last_text)
            history.append({"role": "user", "content": turn.results})


class UnavailableLLM:
    """Stands in for a provider that cannot be built, so the app still starts; every call fails
    with the configuration problem as its message."""

    strong_model = fast_model = "unavailable"

    def __init__(self, message: str) -> None:
        self.message = message

    def model_for(self, tier: Tier) -> str:
        return self.strong_model

    async def structured(self, **kwargs: Any) -> tuple[BaseModel, Usage]:
        raise LLMError("api_error", self.message)

    async def tool_loop(self, **kwargs: Any) -> LoopResult:
        raise LLMError("api_error", self.message)


def make_llm() -> LLMClient:
    """The selected provider; every phase uses this same boundary."""
    from app.config import LLM_PROVIDERS, get_settings

    settings = get_settings()
    provider = settings.LLM_PROVIDER
    if provider == "claude_cli":
        from app.agent.llm_claude_code import ClaudeCodeLLM

        return ClaudeCodeLLM()
    if provider == "liara":
        from app.agent.llm_liara import LiaraLLM

        return LiaraLLM()
    if provider == "top_tools":
        from app.agent.llm_top_tools import TopToolsLLM

        return TopToolsLLM()
    if provider in ("gemini", "chain"):
        from app.agent.llm_chain import make_chain

        # Gemini alone is a chain of its keys, so a rate-limited key falls through to the next.
        return make_chain(settings.llm_chain if provider == "chain" else ["gemini"], settings=settings)
    if provider == "anthropic":
        return AnthropicLLM()
    return UnavailableLLM(
        f"LLM_PROVIDER={provider[:40]!r} is not supported; use one of: {', '.join(LLM_PROVIDERS)}."
    )


# --------------------------------------------------------------------------- fake


@dataclass
class ToolCall:
    """One scripted tool call inside a FakeLLM turn."""

    name: str
    input: dict[str, Any] = field(default_factory=dict)


# A scripted turn: a list of tool calls, or plain text (a turn with no tool call).
FakeTurn = list[ToolCall] | str


@dataclass
class PlainJsonRetry:
    """A scripted structured result that arrives only after the client's plain-JSON retry."""

    result: Any


StructuredScript = BaseModel | dict[str, Any] | Exception | PlainJsonRetry | Callable[[list[Any]], Any]


@dataclass
class FakeCall:
    kind: Literal["structured", "tool_loop"]
    task: str
    tier: Tier
    system: str
    messages: list[Any]
    tools: list[str] = field(default_factory=list)


@dataclass
class FakeToolResult:
    task: str
    name: str
    input: dict[str, Any]
    content: Any
    is_error: bool


class FakeLLM:
    """Scripted ``LLMClient``. Scripts are consumed in order, per task.

    ``structured[task]``: a list of results; each is a model instance, a dict (validated against the
    requested schema), an exception to raise, or a callable receiving the messages.
    ``loops[task]``: a list of loop scripts; each script is a list of turns.
    ``usage_per_call`` is charged for every structured call and every loop turn.
    """

    def __init__(
        self,
        *,
        structured: dict[str, list[StructuredScript]] | None = None,
        loops: dict[str, list[list[FakeTurn]]] | None = None,
        usage_per_call: Usage | None = None,
    ) -> None:
        self.structured_scripts = {k: list(v) for k, v in (structured or {}).items()}
        self.loop_scripts = {k: list(v) for k, v in (loops or {}).items()}
        self.usage_per_call = usage_per_call or Usage(input_tokens=1000, output_tokens=200, llm_calls=1)
        self.calls: list[FakeCall] = []
        self.tool_results: list[FakeToolResult] = []

    def _charge(self) -> Usage:
        return self.usage_per_call.model_copy()

    async def structured(
        self,
        *,
        task: str,
        system: str,
        messages: list[Any],
        schema: type[BaseModel],
        tier: Tier = "strong",
        on_retry: RetryHook | None = None,
    ) -> tuple[BaseModel, Usage]:
        self.calls.append(FakeCall("structured", task, tier, system, list(messages)))
        queue = self.structured_scripts.get(task) or []
        if not queue:
            raise AssertionError(f"FakeLLM: no scripted structured result left for task '{task}'")
        item = queue.pop(0)
        if callable(item) and not isinstance(item, BaseModel):
            item = item(messages)
        if isinstance(item, PlainJsonRetry):
            # Simulates the real client's plain-JSON fallback: the retry hook fires, then the call succeeds.
            if on_retry is not None:
                await on_retry(PLAIN_JSON_RETRY_REASON)
            item = item.result
        if isinstance(item, Exception):
            raise item
        usage = self._charge()
        if isinstance(item, BaseModel):
            item = item.model_dump(mode="json")
        try:
            return schema.model_validate(item), usage
        except ValidationError as exc:
            raise LLMError("invalid_output", str(exc)[:2000], usage=usage) from None

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
        self.calls.append(FakeCall("tool_loop", task, tier, system, list(messages), [t.name for t in tools]))
        queue = self.loop_scripts.get(task) or []
        if not queue:
            raise AssertionError(f"FakeLLM: no scripted tool loop left for task '{task}'")
        turns = list(queue.pop(0))
        known = {t.name for t in tools}
        total = Usage()
        state = {"calls": 0}
        nudged = False
        last_text: str | None = None
        counter = 0
        turn_no = 0

        async def recording_handler(name: str, args: dict[str, Any]) -> ToolOutcome:
            if name not in known:
                outcome = ToolOutcome({"ok": False, "error": f"unknown tool '{name}'"}, is_error=True)
            else:
                try:
                    outcome = await handler(name, args)
                except Exception as exc:
                    self.tool_results.append(
                        FakeToolResult(task, name, args, {"ok": False, "raised": repr(exc)}, True)
                    )
                    raise
            self.tool_results.append(FakeToolResult(task, name, args, outcome.content, outcome.is_error))
            return outcome

        while True:
            if not turns:
                return LoopResult("end_turn", state["calls"], total, last_text)
            turn = turns.pop(0)
            turn_no += 1
            if on_turn is not None:
                await on_turn(turn_no)
            usage = self._charge()
            total = total + usage
            if on_usage is not None and not on_usage(usage):
                return LoopResult("budget", state["calls"], total, last_text)
            if isinstance(turn, str):
                last_text = turn
                if nudged:
                    return LoopResult("end_turn", state["calls"], total, last_text)
                nudged = True
                continue
            uses = []
            for call in turn:
                counter += 1
                uses.append(_ToolUse(f"toolu_{counter}", call.name, call.input))
            result = await _run_tool_turn(uses, recording_handler, state, max_tool_calls)
            total.tool_calls = state["calls"]
            if result.finished:
                return LoopResult("finished", state["calls"], total, last_text)
            if result.limit_hit:
                return LoopResult("tool_limit", state["calls"], total, last_text)
