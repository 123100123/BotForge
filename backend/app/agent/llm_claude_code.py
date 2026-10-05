"""``LLMClient`` over headless Claude Code (``LLM_PROVIDER=claude_cli``), for local development and evals.

Runs the model through the Claude Code CLI with the Python ``claude-agent-sdk`` package (dependency
group ``headless``; not a runtime dependency), so the developer's Claude Code login is used instead of
a paid ``ANTHROPIC_API_KEY``. Production keeps ``AnthropicLLM``; automated tests use ``FakeLLM`` (and
a fake SDK behind the ``_sdk`` seam for this module's own tests).

Every call is one isolated CLI session: our system prompt replaces Claude Code's, every built-in tool
is disabled, no filesystem settings, hooks, CLAUDE.md, skills or user MCP servers are loaded, nothing
is persisted, prompts are delivered verbatim, and ``ANTHROPIC_API_KEY`` is blanked for the child so
the CLI authenticates with the login. ``--bare`` is never used (it forces API-key auth).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.llm import (
    DEFAULT_STRONG_MODEL,
    NUDGE_TEXT,
    LLMError,
    LoopResult,
    StopReason,
    Tier,
    ToolDef,
    ToolHandler,
    Usage,
    UsageHook,
    _extract_json,
    _run_tool_turn,
    _ToolUse,
    cost_of,
)

log = logging.getLogger(__name__)

SERVER_NAME = "botforge"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
STRUCTURED_MAX_TURNS = 10  # the CLI's StructuredOutput tool may ask the model to retry invalid output
DRAIN_SECONDS = 15.0  # after an interrupt, how long to wait for the session's closing result
# Prefix of the error result the SDK's in-process MCP server returns when arguments fail the tool's
# JSON schema; such calls never reach our handler, so the loop counts them itself.
SDK_VALIDATION_PREFIX = "Input validation error"


def _sdk() -> Any:
    """The ``claude_agent_sdk`` module, imported lazily. Tests replace this seam with a fake."""
    try:
        import claude_agent_sdk
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise LLMError(
            "api_error",
            "LLM_PROVIDER=claude_cli needs the claude-agent-sdk package: run `uv sync --group headless`",
        ) from exc
    return claude_agent_sdk


# --------------------------------------------------------------------------- prompt rendering


def _get(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def _render_block(block: Any) -> str | None:
    if isinstance(block, str):
        return block
    kind = _get(block, "type")
    if kind == "text":
        return str(_get(block, "text", ""))
    if kind in ("thinking", "redacted_thinking"):
        return None  # not replayable across sessions; the API would not show it to the model either
    if kind == "tool_use":
        args = json.dumps(_get(block, "input", {}), ensure_ascii=False, sort_keys=True)
        return f"[tool call {_get(block, 'name')} id={_get(block, 'id')}] {args}"
    if kind == "tool_result":
        content = _get(block, "content", "")
        if isinstance(content, list):
            content = "\n".join(filter(None, (_render_block(b) for b in content)))
        label = "tool error" if _get(block, "is_error") else "tool result"
        return f"[{label} id={_get(block, 'tool_use_id')}] {content}"
    return f"[{kind} block omitted]"


def _render_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(part for part in (_render_block(b) for b in content) if part)
    return str(content)


def render_messages(messages: list[Any]) -> str:
    """Anthropic-style ``messages`` as one prompt, deterministically.

    A single user message is sent as its own text. A longer history becomes a transcript of
    ``<turn role="...">`` sections followed by an instruction to answer the last user turn.
    """
    if not messages:
        return ""
    if len(messages) == 1 and _get(messages[0], "role") == "user":
        return _render_content(_get(messages[0], "content", ""))
    turns = [
        f'<turn role="{_get(m, "role")}">\n{_render_content(_get(m, "content", ""))}\n</turn>'
        for m in messages
    ]
    return (
        "The conversation so far:\n\n"
        + "\n\n".join(turns)
        + "\n\nRespond as the assistant to the last user turn."
    )


# --------------------------------------------------------------------------- per-session tracking


@dataclass
class _Session:
    """What one CLI session has produced so far (usage, stop reasons, text, tool bookkeeping)."""

    task: str
    model: str
    on_usage: UsageHook | None = None
    total: Usage = field(default_factory=Usage)
    responses_in_query: int = 0
    response_open: bool = False
    response_started: float = 0.0
    requested_at: float | None = None  # the CLI's "requesting" status for the next response
    response_model: str | None = None
    last_text: str | None = None
    last_stop: str | None = None
    stops: list[str] = field(default_factory=list)  # every response's stop reason, in order
    budget_spent: bool = False
    pending: set[str] = field(default_factory=set)  # our tool uses still waiting for a result

    def charge(self, usage: Usage, *, model: str, stop: str | None, started: float) -> None:
        usage.cost_usd = cost_of(model, usage)
        self.total = self.total + usage
        log.info(
            "llm call task=%s provider=claude_cli model=%s in=%d out=%d cache_read=%d cache_write=%d "
            "duration_ms=%d stop=%s",
            self.task,
            model,
            usage.input_tokens,
            usage.output_tokens,
            usage.cached_tokens,
            usage.cache_write_tokens,
            int((time.perf_counter() - started) * 1000),
            stop,
        )
        if self.on_usage is not None and not self.on_usage(usage):
            self.budget_spent = True

    def observe(self, sdk: Any, message: Any) -> None:
        """Account for one message of the stream (main thread only; there are no subagents)."""
        if getattr(message, "parent_tool_use_id", None) is not None:
            return
        if isinstance(message, sdk.StreamEvent):
            event = message.event or {}
            if event.get("type") == "message_start":
                self.response_open = True
                self.response_started = self.requested_at or time.perf_counter()
                self.requested_at = None
                self.response_model = (event.get("message") or {}).get("model") or self.model
            elif event.get("type") == "message_delta":
                self.response_open = False
                self.responses_in_query += 1
                self.last_stop = (event.get("delta") or {}).get("stop_reason")
                self.stops.append(self.last_stop or "")
                self.charge(
                    _usage_from(event.get("usage")),
                    model=self.response_model or self.model,
                    stop=self.last_stop,
                    started=self.response_started,
                )
        elif isinstance(message, sdk.AssistantMessage):
            text = "".join(b.text for b in message.content if isinstance(b, sdk.TextBlock))
            self.last_text = text or self.last_text
            for b in message.content:
                if isinstance(b, sdk.ToolUseBlock) and b.name.startswith(f"mcp__{SERVER_NAME}__"):
                    self.pending.add(b.id)
        elif isinstance(message, sdk.SystemMessage) and message.subtype == "status":
            if (message.data or {}).get("status") == "requesting":
                self.requested_at = time.perf_counter()  # duration then includes time to first token
        elif isinstance(message, sdk.SystemMessage) and message.subtype == "init":
            source = (message.data or {}).get("apiKeySource")
            if source not in (None, "none"):
                log.warning("claude_cli session authenticated with %s, not the Claude Code login", source)

    def finish_query(self, result: Any) -> None:
        """At a ResultMessage: when the stream carried no per-response usage, charge the result's."""
        if self.responses_in_query == 0 and result.usage:
            self.charge(
                _usage_from(result.usage),
                model=self.model,
                stop=result.stop_reason,
                started=time.perf_counter() - (result.duration_ms or 0) / 1000,
            )
        self.last_stop = result.stop_reason or self.last_stop
        self.responses_in_query = 0
        self.response_open = False


def _usage_from(raw: dict[str, Any] | None) -> Usage:
    raw = raw or {}
    return Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cached_tokens=int(raw.get("cache_read_input_tokens") or 0),
        cache_write_tokens=int(raw.get("cache_creation_input_tokens") or 0),
        llm_calls=1,
    )


def _result_error(result: Any) -> str:
    parts = [f"subtype={result.subtype}"]
    if getattr(result, "api_error_status", None):
        parts.append(f"status={result.api_error_status}")
    if getattr(result, "terminal_reason", None):
        parts.append(f"terminal_reason={result.terminal_reason}")
    errors = getattr(result, "errors", None) or []
    detail = "; ".join(errors) or (result.result or "")
    return " ".join(parts) + (f": {detail[:1000]}" if detail else "")


# --------------------------------------------------------------------------- client


class ClaudeCodeLLM:
    """``LLMClient`` over headless Claude Code. One instance can serve many concurrent runs.

    Each ``structured`` / ``tool_loop`` call starts its own CLI session (``ClaudeSDKClient``) and
    closes it before returning. Both tiers use the same model (``CLAUDE_CLI_MODEL``) at
    ``CLAUDE_CLI_EFFORT``.

    Usage is taken per model response from the CLI's stream events (exact API usage); calls billed
    to the subscription still report ``cost_usd = cost_of(model, usage)`` as the *notional* API cost,
    so budgets and eval reports keep working. Small background calls the CLI makes on its own (a
    Haiku request per session) are not streamed and are not counted.

    Tools are served by an in-process SDK MCP server named ``botforge``. The SDK validates arguments
    against each tool's JSON schema before our handler runs; such rejected calls are counted toward
    ``max_tool_calls`` like any other call (they reached the model as an error result).
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        effort: str | None = None,
        cli_path: str | None = None,
        log_bodies: bool | None = None,
    ) -> None:
        from app.config import get_settings

        settings = get_settings()
        self.model = model or settings.CLAUDE_CLI_MODEL or DEFAULT_STRONG_MODEL
        self.effort = effort or settings.CLAUDE_CLI_EFFORT or "medium"
        if self.effort not in EFFORT_LEVELS:
            raise ValueError(f"CLAUDE_CLI_EFFORT must be one of {', '.join(EFFORT_LEVELS)}")
        self.cli_path = cli_path or settings.CLAUDE_CLI_PATH or None
        self.log_bodies = settings.LOG_LLM_BODIES if log_bodies is None else log_bodies
        self.strong_model = self.fast_model = self.model

    def model_for(self, tier: Tier) -> str:
        return self.model

    def _options(self, sdk: Any, system: str, **extra: Any) -> Any:
        return sdk.ClaudeAgentOptions(
            model=self.model,
            effort=self.effort,
            system_prompt=system,  # replaces Claude Code's default system prompt
            tools=[],  # --tools "": no built-in tools
            setting_sources=[],  # no user/project/local settings, hooks or CLAUDE.md
            skills=[],
            strict_mcp_config=True,  # only our server; no user or claude.ai MCP servers
            permission_mode="dontAsk",  # anything not explicitly allowed is denied, never prompted
            verbatim_prompts=True,  # no @file expansion or slash commands in our prompt text
            include_partial_messages=True,  # stream events carry exact per-response usage
            cwd=tempfile.gettempdir(),
            cli_path=self.cli_path,
            env={"ANTHROPIC_API_KEY": ""},  # authenticate with the Claude Code login, never a key
            extra_args={"no-session-persistence": None},
            **extra,
        )

    def _log_request(self, task: str, kind: str, system: str, prompt: str) -> None:
        if self.log_bodies:
            log.info(
                "llm request task=%s provider=claude_cli kind=%s body=%s",
                task,
                kind,
                json.dumps({"system": system, "prompt": prompt}, ensure_ascii=False),
            )

    async def structured(
        self,
        *,
        task: str,
        system: str,
        messages: list[Any],
        schema: type[BaseModel],
        tier: Tier = "strong",
    ) -> tuple[BaseModel, Usage]:
        sdk = _sdk()
        prompt = render_messages(messages)
        self._log_request(task, "structured", system, prompt)
        options = self._options(
            sdk,
            system,
            output_format={"type": "json_schema", "schema": schema.model_json_schema()},
            max_turns=STRUCTURED_MAX_TURNS,
        )
        session = _Session(task, self.model)
        result: Any = None
        try:
            async with sdk.ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    session.observe(sdk, message)
                    if isinstance(message, sdk.ResultMessage):
                        session.finish_query(message)
                        result = message
        except sdk.ClaudeSDKError as exc:
            raise LLMError("api_error", f"claude_cli: {exc}"[:2000], usage=session.total) from None
        usage = session.total
        if result is None:
            raise LLMError("api_error", "claude_cli session ended without a result", usage=usage)
        stops = [*session.stops, result.stop_reason or ""]
        if "refusal" in stops:
            raise LLMError("refusal", "model declined (claude_cli)", usage=usage)
        if "max_tokens" in stops and result.structured_output is None:
            raise LLMError("max_tokens", "output was cut off at max_tokens", usage=usage)
        if result.is_error and result.structured_output is None:
            if result.subtype.startswith("error_max"):  # turns / structured-output retries spent
                raise LLMError("invalid_output", _result_error(result), usage=usage)
            raise LLMError("api_error", _result_error(result), usage=usage)
        try:
            payload = (
                result.structured_output
                if result.structured_output is not None
                else _extract_json(result.result or session.last_text or "")
            )
            return schema.model_validate(payload), usage
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
    ) -> LoopResult:
        sdk = _sdk()
        prompt = render_messages(messages)
        self._log_request(task, "tool_loop", system, prompt)
        state = {"calls": 0}
        flags = {"finished": False, "limit_hit": False}
        counter = itertools.count(1)

        def make_mcp_tool(tool_def: ToolDef) -> Any:
            async def run(args: dict[str, Any]) -> dict[str, Any]:
                use = _ToolUse(f"cli_{next(counter)}", tool_def.name, args if isinstance(args, dict) else {})
                turn = await _run_tool_turn([use], handler, state, max_tool_calls)
                flags["finished"] = flags["finished"] or turn.finished
                flags["limit_hit"] = flags["limit_hit"] or turn.limit_hit
                out = turn.results[0]
                return {"content": [{"type": "text", "text": out["content"]}], "is_error": out["is_error"]}

            return sdk.tool(tool_def.name, tool_def.description, tool_def.input_schema)(run)

        server = sdk.create_sdk_mcp_server(
            name=SERVER_NAME, version="1.0.0", tools=[make_mcp_tool(t) for t in tools]
        )
        options = self._options(
            sdk,
            system,
            mcp_servers={SERVER_NAME: server},
            allowed_tools=[f"mcp__{SERVER_NAME}__{t.name}" for t in tools],
            max_turns=max_tool_calls * 2 + 20,  # our limits end the loop before the CLI's does
        )
        session = _Session(task, self.model, on_usage)
        started = time.perf_counter()

        def done(reason: StopReason) -> LoopResult:
            session.total.tool_calls = state["calls"]
            log.info(
                "llm loop task=%s provider=claude_cli stop=%s tool_calls=%d llm_calls=%d duration_ms=%d",
                task,
                reason,
                state["calls"],
                session.total.llm_calls,
                int((time.perf_counter() - started) * 1000),
            )
            return LoopResult(reason, state["calls"], session.total, session.last_text)

        def count_rejected(message: Any) -> None:
            """Tool results for our calls; SDK schema rejections count as calls (see class doc)."""
            if getattr(message, "parent_tool_use_id", None) is not None:
                return
            content = message.content if isinstance(message.content, list) else []
            for block in content:
                if not isinstance(block, sdk.ToolResultBlock) or block.tool_use_id not in session.pending:
                    continue
                session.pending.discard(block.tool_use_id)
                if block.is_error and _render_content(block.content).startswith(SDK_VALIDATION_PREFIX):
                    if state["calls"] >= max_tool_calls:
                        flags["limit_hit"] = True
                    else:
                        state["calls"] += 1

        def early_stop() -> StopReason | None:
            if session.budget_spent:
                return "budget"
            if session.last_stop in ("refusal", "max_tokens") and not session.response_open:
                return session.last_stop  # type: ignore[return-value]
            if session.response_open or session.pending:
                return None  # let the current response and its tool calls complete
            if flags["finished"]:
                return "finished"
            if flags["limit_hit"]:
                return "tool_limit"
            return None

        nudged = False
        try:
            async with sdk.ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                while True:
                    reason: StopReason | None = None
                    result: Any = None
                    async for message in client.receive_response():
                        session.observe(sdk, message)
                        if isinstance(message, sdk.UserMessage):
                            count_rejected(message)
                        if isinstance(message, sdk.ResultMessage):
                            session.finish_query(message)
                            result = message
                            break
                        reason = early_stop()
                        if reason is not None:
                            break
                    if reason is not None:
                        await self._stop(sdk, client, session)
                        return done(reason)
                    if result is None:
                        raise LLMError("api_error", "claude_cli session ended without a result")
                    session.pending.clear()  # the turn is over; nothing more will arrive for them
                    reason = early_stop()
                    if reason is not None:
                        return done(reason)
                    if result.is_error:
                        if result.subtype == "error_max_turns":
                            return done("tool_limit")
                        raise LLMError("api_error", _result_error(result), usage=session.total)
                    if nudged:
                        return done("end_turn")
                    nudged = True
                    await client.query(NUDGE_TEXT)
        except LLMError as exc:
            exc.usage = session.total
            raise
        except sdk.ClaudeSDKError as exc:
            raise LLMError("api_error", f"claude_cli: {exc}"[:2000], usage=session.total) from None

    async def _stop(self, sdk: Any, client: Any, session: _Session) -> None:
        """Interrupt the session and drain it to its closing result; the context exit then closes it.

        A response that still completes during the drain is charged (``on_usage`` included); its
        verdict no longer matters because the loop is already ending.
        """
        try:
            await client.interrupt()
            async with asyncio.timeout(DRAIN_SECONDS):
                async for message in client.receive_response():
                    session.observe(sdk, message)
        except (TimeoutError, sdk.ClaudeSDKError) as exc:
            log.warning("claude_cli session did not drain cleanly after interrupt: %r", exc)
