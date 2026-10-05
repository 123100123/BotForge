"""ClaudeCodeLLM against a fake ``claude_agent_sdk`` (no CLI subprocess, no network); make_llm selection."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.agent import llm_claude_code
from app.agent.llm import (
    LIMIT_TEXT,
    NUDGE_TEXT,
    AnthropicLLM,
    LLMError,
    ToolDef,
    ToolOutcome,
    Usage,
    cost_of,
    make_llm,
)
from app.agent.llm_claude_code import ClaudeCodeLLM, render_messages
from app.config import get_settings

# --------------------------------------------------------------------------- fake SDK


@dataclass
class TextBlock:
    text: str


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: Any = None
    is_error: bool | None = None


@dataclass
class AssistantMessage:
    content: list[Any]
    model: str = "claude-opus-5-5"
    parent_tool_use_id: str | None = None


@dataclass
class UserMessage:
    content: Any
    parent_tool_use_id: str | None = None


@dataclass
class SystemMessage:
    subtype: str
    data: dict[str, Any]


@dataclass
class StreamEvent:
    event: dict[str, Any]
    parent_tool_use_id: str | None = None


@dataclass
class ResultMessage:
    subtype: str = "success"
    is_error: bool = False
    stop_reason: str | None = "end_turn"
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    duration_ms: int = 10
    api_error_status: int | None = None
    terminal_reason: str | None = "completed"
    errors: list[str] | None = None


class ClaudeSDKError(Exception):
    pass


@dataclass
class ClaudeAgentOptions:
    kwargs: dict[str, Any]


@dataclass
class SdkMcpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Any


def tool(name: str, description: str, input_schema: dict[str, Any]) -> Any:
    return lambda handler: SdkMcpTool(name, description, input_schema, handler)


def create_sdk_mcp_server(name: str, version: str = "1.0.0", tools: list[Any] | None = None) -> dict:
    return {"type": "sdk", "name": name, "tools": {t.name: t for t in tools or []}}


@dataclass
class Resp:
    """One scripted model response: optional text, our tool calls, usage, stop reason."""

    text: str | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    usage: tuple[int, int, int, int] = (100, 20, 0, 0)  # in, out, cache read, cache write
    stop: str = "tool_use"
    results_after_delta: bool = False  # like the real CLI: a tool can finish after message_delta
    reject: bool = False  # the SDK rejects the arguments (schema validation) before our handler


@dataclass
class Query:
    """One query's scripted responses and how its result ends."""

    responses: list[Resp]
    result: ResultMessage | None = None
    stream_events: bool = True


def raw_usage(u: tuple[int, int, int, int]) -> dict[str, int]:
    return {
        "input_tokens": u[0],
        "output_tokens": u[1],
        "cache_read_input_tokens": u[2],
        "cache_creation_input_tokens": u[3],
    }


class FakeClient:
    """Mimics ``ClaudeSDKClient``: scripted queries; our MCP tools are really invoked."""

    instances: list["FakeClient"] = []
    script: list[Query] = []
    api_key_source = "none"

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options.kwargs
        self.queries = list(FakeClient.script)
        self.prompts: list[str] = []
        self.interrupted = False
        self.open = False
        self.counter = 0
        FakeClient.instances.append(self)

    async def __aenter__(self) -> "FakeClient":
        self.open = True
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        self.open = False
        return False

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def interrupt(self) -> None:
        self.interrupted = True

    async def _results(self, ids: list[tuple[str, Resp, tuple[str, dict[str, Any]]]]) -> list[Any]:
        out: list[Any] = []
        if not ids:
            return out
        tools = self.options["mcp_servers"]["botforge"]["tools"]
        for use_id, resp, (name, args) in ids:
            if resp.reject:
                block = ToolResultBlock(use_id, "Input validation error: 'x' is required", True)
            else:
                res = await tools[name].handler(args)
                block = ToolResultBlock(use_id, res["content"], res["is_error"] or None)
            out.append(UserMessage([block]))
        return out

    async def receive_response(self) -> Any:
        if self.interrupted:  # the drain after an interrupt
            yield ResultMessage(stop_reason=None, terminal_reason="aborted_tools")
            return
        q = self.queries.pop(0)
        if self.prompts and len(self.prompts) == 1:
            yield SystemMessage("init", {"apiKeySource": self.api_key_source})
        yield SystemMessage("status", {"status": "requesting"})
        total = [0, 0, 0, 0]
        last_text = None
        for resp in q.responses:
            if self.interrupted:
                yield ResultMessage(stop_reason=None, terminal_reason="aborted_streaming")
                return
            if q.stream_events:
                yield StreamEvent({"type": "message_start", "message": {"model": "claude-opus-5-5"}})
            if resp.text:
                last_text = resp.text
                yield AssistantMessage([TextBlock(resp.text)])
            ids = []
            for call in resp.calls:
                self.counter += 1
                use_id = f"toolu_{self.counter}"
                ids.append((use_id, resp, call))
                yield AssistantMessage([ToolUseBlock(use_id, f"mcp__botforge__{call[0]}", call[1])])
            delta = StreamEvent(
                {"type": "message_delta", "delta": {"stop_reason": resp.stop}, "usage": raw_usage(resp.usage)}
            )
            if not resp.results_after_delta:
                for m in await self._results(ids):
                    yield m
            if q.stream_events:
                yield delta
            if resp.results_after_delta:
                for m in await self._results(ids):
                    yield m
            total = [a + b for a, b in zip(total, resp.usage, strict=True)]
        result = q.result or ResultMessage(
            stop_reason=q.responses[-1].stop if q.responses else "end_turn", result=last_text
        )
        if result.usage is None:
            result.usage = raw_usage(tuple(total))  # type: ignore[arg-type]
        yield result


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    fake = SimpleNamespace(
        ClaudeAgentOptions=lambda **kw: ClaudeAgentOptions(kw),
        ClaudeSDKClient=FakeClient,
        ClaudeSDKError=ClaudeSDKError,
        create_sdk_mcp_server=create_sdk_mcp_server,
        tool=tool,
        AssistantMessage=AssistantMessage,
        UserMessage=UserMessage,
        SystemMessage=SystemMessage,
        ResultMessage=ResultMessage,
        StreamEvent=StreamEvent,
        TextBlock=TextBlock,
        ToolUseBlock=ToolUseBlock,
        ToolResultBlock=ToolResultBlock,
    )
    FakeClient.instances = []
    FakeClient.script = []
    FakeClient.api_key_source = "none"
    monkeypatch.setattr(llm_claude_code, "_sdk", lambda: fake)
    return fake


def script(*queries: Query) -> None:
    FakeClient.script = list(queries)


def client() -> FakeClient:
    (c,) = FakeClient.instances
    return c


def llm() -> ClaudeCodeLLM:
    return ClaudeCodeLLM(model="claude-opus-5-5", effort="medium", log_bodies=False)


class Place(BaseModel):
    city: str
    country: str


TOOLS = [
    ToolDef("add", "add", {"type": "object", "properties": {"a": {"type": "integer"}}}),
    ToolDef("finish", "done", {"type": "object", "properties": {}}, strict=True),
]

# --------------------------------------------------------------------------- rendering


def test_single_user_message_is_sent_as_is() -> None:
    assert render_messages([{"role": "user", "content": "سلام @/etc/passwd"}]) == "سلام @/etc/passwd"
    blocks = [{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]
    assert render_messages(blocks) == "a\n\nb"


def test_history_renders_as_a_deterministic_transcript() -> None:
    messages = [
        {"role": "user", "content": "first"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "text", "text": "calling"},
                {"type": "tool_use", "id": "t1", "name": "add", "input": {"b": 2, "a": 1}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "3", "is_error": False}],
        },
        {"role": "user", "content": [{"type": "image", "source": {}}]},
    ]
    out = render_messages(messages)
    assert out == render_messages(messages)
    assert out == (
        "The conversation so far:\n\n"
        '<turn role="user">\nfirst\n</turn>\n\n'
        '<turn role="assistant">\ncalling\n\n[tool call add id=t1] {"a": 1, "b": 2}\n</turn>\n\n'
        '<turn role="user">\n[tool result id=t1] 3\n</turn>\n\n'
        '<turn role="user">\n[image block omitted]\n</turn>'
        "\n\nRespond as the assistant to the last user turn."
    )


# --------------------------------------------------------------------------- structured


async def test_structured_success_and_session_isolation(sdk: SimpleNamespace) -> None:
    script(
        Query(
            [Resp(stop="tool_use", usage=(2, 24, 0, 910)), Resp(stop="end_turn", usage=(1, 5, 900, 0))],
            ResultMessage(structured_output={"city": "اصفهان", "country": "ایران"}),
        )
    )
    out, used = await llm().structured(
        task="understand", system="SYS", messages=[{"role": "user", "content": "hi"}], schema=Place
    )
    assert out == Place(city="اصفهان", country="ایران")
    assert used.input_tokens == 3 and used.output_tokens == 29
    assert used.cached_tokens == 900 and used.cache_write_tokens == 910 and used.llm_calls == 2
    assert used.cost_usd == pytest.approx(cost_of("claude-opus-5-5", used))
    c = client()
    o = c.options
    assert c.prompts == ["hi"] and not c.open
    assert o["model"] == "claude-opus-5-5" and o["effort"] == "medium" and o["system_prompt"] == "SYS"
    assert o["tools"] == [] and o["setting_sources"] == [] and o["strict_mcp_config"] is True
    assert o["output_format"] == {"type": "json_schema", "schema": Place.model_json_schema()}
    assert o["env"] == {"ANTHROPIC_API_KEY": ""} and o["cli_path"] is None
    assert "bare" not in o["extra_args"] and "no-session-persistence" in o["extra_args"]


async def test_structured_parses_json_from_text_when_no_structured_output(sdk: SimpleNamespace) -> None:
    script(Query([Resp(stop="end_turn")], ResultMessage(result='Here: {"city": "a", "country": "b"}')))
    out, _ = await llm().structured(task="t", system="S", messages=[], schema=Place)
    assert out == Place(city="a", country="b")


async def test_structured_uses_result_usage_without_stream_events(sdk: SimpleNamespace) -> None:
    script(
        Query(
            [Resp(stop="end_turn", usage=(7, 3, 0, 0))],
            ResultMessage(structured_output={"city": "a", "country": "b"}),
            stream_events=False,
        )
    )
    _, used = await llm().structured(task="t", system="S", messages=[], schema=Place)
    assert used.input_tokens == 7 and used.output_tokens == 3 and used.llm_calls == 1


async def test_structured_invalid_json_is_invalid_output(sdk: SimpleNamespace) -> None:
    script(Query([Resp(stop="end_turn")], ResultMessage(result="not json")))
    with pytest.raises(LLMError) as exc:
        await llm().structured(task="t", system="S", messages=[], schema=Place)
    assert exc.value.code == "invalid_output" and exc.value.usage.input_tokens == 100


async def test_structured_schema_mismatch_is_invalid_output(sdk: SimpleNamespace) -> None:
    script(Query([Resp(stop="end_turn")], ResultMessage(structured_output={"city": "a"})))
    with pytest.raises(LLMError) as exc:
        await llm().structured(task="t", system="S", messages=[], schema=Place)
    assert exc.value.code == "invalid_output"


@pytest.mark.parametrize(
    ("stop", "result", "code"),
    [
        ("refusal", ResultMessage(stop_reason="refusal"), "refusal"),
        ("max_tokens", ResultMessage(stop_reason="max_tokens", result='{"city": "a", "co'), "max_tokens"),
        (
            "end_turn",
            ResultMessage(subtype="error_max_structured_output_retries", is_error=True),
            "invalid_output",
        ),
        ("end_turn", ResultMessage(is_error=True, api_error_status=529, result="API Error"), "api_error"),
    ],
)
async def test_structured_failures_map_to_llm_error_codes(
    sdk: SimpleNamespace, stop: str, result: ResultMessage, code: str
) -> None:
    script(Query([Resp(stop=stop)], result))
    with pytest.raises(LLMError) as exc:
        await llm().structured(task="t", system="S", messages=[], schema=Place)
    assert exc.value.code == code and exc.value.usage.llm_calls == 1


async def test_sdk_errors_become_api_errors(sdk: SimpleNamespace) -> None:
    class Broken(FakeClient):
        async def query(self, prompt: str) -> None:
            raise ClaudeSDKError("CLI not found")

    sdk.ClaudeSDKClient = Broken
    with pytest.raises(LLMError) as exc:
        await llm().structured(task="t", system="S", messages=[], schema=Place)
    assert exc.value.code == "api_error" and "CLI not found" in exc.value.message


async def test_a_session_not_on_the_login_is_logged(
    sdk: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    FakeClient.api_key_source = "ANTHROPIC_API_KEY"
    script(Query([Resp(stop="end_turn")], ResultMessage(structured_output={"city": "a", "country": "b"})))
    await llm().structured(task="t", system="S", messages=[], schema=Place)
    assert "authenticated with ANTHROPIC_API_KEY" in caplog.text


def test_invalid_effort_is_rejected() -> None:
    with pytest.raises(ValueError):
        ClaudeCodeLLM(effort="extreme")


# --------------------------------------------------------------------------- tool loop


def recorder(stop_on: str = "finish", fail_on: str | None = None) -> tuple[list[tuple[str, dict]], Any]:
    seen: list[tuple[str, dict]] = []

    async def handler(name: str, args: dict[str, Any]) -> ToolOutcome:
        seen.append((name, args))
        if name == fail_on:
            raise RuntimeError("boom")
        return ToolOutcome({"ok": True, "name": name}, stop=name == stop_on)

    return seen, handler


async def run_loop(handler: Any, limit: int = 10, on_usage: Any = None) -> Any:
    return await llm().tool_loop(
        task="build",
        system="SYS",
        messages=[{"role": "user", "content": "go"}],
        tools=TOOLS,
        handler=handler,
        max_tool_calls=limit,
        on_usage=on_usage,
    )


@pytest.mark.parametrize("after_delta", [False, True])
async def test_finish_stops_the_loop_and_closes_the_session(sdk: SimpleNamespace, after_delta: bool) -> None:
    script(
        Query(
            [
                Resp(text="adding", calls=[("add", {"a": 1})]),
                Resp(calls=[("finish", {})], results_after_delta=after_delta),
                Resp(text="never reached", stop="end_turn"),
            ]
        )
    )
    seen, handler = recorder()
    hooked: list[Usage] = []
    result = await run_loop(handler, on_usage=lambda u: hooked.append(u) or True)
    assert result.stop_reason == "finished" and result.tool_calls == 2
    assert seen == [("add", {"a": 1}), ("finish", {})]
    assert result.text == "adding"
    assert result.usage.llm_calls == 2 and result.usage.tool_calls == 2
    assert sum(u.input_tokens for u in hooked) == result.usage.input_tokens == 200
    c = client()
    assert c.interrupted and not c.open
    o = c.options
    assert o["allowed_tools"] == ["mcp__botforge__add", "mcp__botforge__finish"]
    assert o["max_turns"] == 10 * 2 + 20 and o["tools"] == []
    assert list(o["mcp_servers"]) == ["botforge"]


async def test_tool_results_are_json_text_with_is_error(sdk: SimpleNamespace) -> None:
    script(Query([Resp(calls=[("add", {"a": 1})], stop="tool_use"), Resp(calls=[("finish", {})])]))

    async def handler(name: str, args: dict[str, Any]) -> ToolOutcome:
        if name == "add":
            return ToolOutcome({"ok": False, "error": "نه"}, is_error=True)
        return ToolOutcome({"ok": True}, stop=True)

    tools = None

    def capture(**kw: Any) -> ClaudeAgentOptions:
        nonlocal tools
        tools = kw.get("mcp_servers", {}).get("botforge", {}).get("tools")
        return ClaudeAgentOptions(kw)

    sdk.ClaudeAgentOptions = capture
    await run_loop(handler)
    assert tools is not None
    out = await tools["add"].handler({"a": 2})
    assert out == {"content": [{"type": "text", "text": '{"ok":false,"error":"نه"}'}], "is_error": True}


async def test_tool_limit_stops_and_does_not_call_the_handler(sdk: SimpleNamespace) -> None:
    script(
        Query(
            [
                Resp(calls=[("add", {"a": 1}), ("add", {"a": 2})]),
                Resp(calls=[("add", {"a": 3}), ("add", {"a": 4})]),
                Resp(calls=[("add", {"a": 5})]),
            ]
        )
    )
    seen, handler = recorder()
    result = await run_loop(handler, limit=3)
    assert result.stop_reason == "tool_limit" and result.tool_calls == 3
    assert [a["a"] for _, a in seen] == [1, 2, 3]  # the fourth call got LIMIT_TEXT, not the handler
    assert client().interrupted


async def test_limit_text_is_returned_as_an_error(sdk: SimpleNamespace) -> None:
    tools = None

    def capture(**kw: Any) -> ClaudeAgentOptions:
        nonlocal tools
        tools = kw["mcp_servers"]["botforge"]["tools"]
        return ClaudeAgentOptions(kw)

    sdk.ClaudeAgentOptions = capture
    script(Query([Resp(calls=[("add", {"a": 1})]), Resp(calls=[("add", {"a": 2})])]))
    _, handler = recorder()
    await run_loop(handler, limit=1)
    assert tools is not None
    out = await tools["add"].handler({"a": 9})
    assert out == {"content": [{"type": "text", "text": LIMIT_TEXT}], "is_error": True}


async def test_schema_rejected_calls_count_toward_the_limit(sdk: SimpleNamespace) -> None:
    script(Query([Resp(calls=[("add", {})], reject=True), Resp(calls=[("add", {"a": 1})]), Resp(calls=[])]))
    seen, handler = recorder()
    result = await run_loop(handler, limit=1)
    assert result.stop_reason == "tool_limit" and result.tool_calls == 1 and seen == []


async def test_handler_exception_becomes_an_error_result_and_the_loop_continues(
    sdk: SimpleNamespace,
) -> None:
    script(Query([Resp(calls=[("add", {"a": 1})]), Resp(calls=[("finish", {})])]))
    seen, handler = recorder(fail_on="add")
    result = await run_loop(handler)
    assert result.stop_reason == "finished" and result.tool_calls == 2
    assert [n for n, _ in seen] == ["add", "finish"]


async def test_no_finish_nudges_once_then_end_turn(sdk: SimpleNamespace) -> None:
    script(
        Query([Resp(calls=[("add", {"a": 1})]), Resp(text="done?", stop="end_turn")]),
        Query([Resp(text="still done", stop="end_turn")]),
    )
    _, handler = recorder()
    result = await run_loop(handler)
    assert result.stop_reason == "end_turn" and result.tool_calls == 1
    assert result.text == "still done" and result.usage.llm_calls == 3
    c = client()
    assert c.prompts == ["go", NUDGE_TEXT] and not c.interrupted and not c.open


async def test_nudge_can_lead_to_finish(sdk: SimpleNamespace) -> None:
    script(Query([Resp(text="hm", stop="end_turn")]), Query([Resp(calls=[("finish", {})])]))
    _, handler = recorder()
    result = await run_loop(handler)
    assert result.stop_reason == "finished" and client().prompts == ["go", NUDGE_TEXT]


async def test_budget_hook_false_stops_with_budget(sdk: SimpleNamespace) -> None:
    script(Query([Resp(calls=[("add", {"a": 1})]), Resp(calls=[("add", {"a": 2})]), Resp(calls=[])]))
    _, handler = recorder()
    calls: list[Usage] = []
    result = await run_loop(handler, on_usage=lambda u: calls.append(u) or len(calls) < 2)
    assert result.stop_reason == "budget" and result.usage.llm_calls == 2
    assert client().interrupted


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
async def test_refusal_and_max_tokens_stop_the_loop(sdk: SimpleNamespace, stop: str) -> None:
    script(Query([Resp(calls=[("add", {"a": 1})]), Resp(text="partial", stop=stop), Resp(calls=[])]))
    _, handler = recorder()
    result = await run_loop(handler)
    assert result.stop_reason == stop and result.text == "partial"


async def test_max_turns_result_is_tool_limit_and_errors_raise(sdk: SimpleNamespace) -> None:
    script(Query([Resp(calls=[("add", {"a": 1})])], ResultMessage(subtype="error_max_turns", is_error=True)))
    _, handler = recorder()
    assert (await run_loop(handler)).stop_reason == "tool_limit"

    FakeClient.instances = []
    script(Query([Resp(stop="end_turn")], ResultMessage(is_error=True, api_error_status=500)))
    with pytest.raises(LLMError) as exc:
        await run_loop(handler)
    assert exc.value.code == "api_error" and exc.value.usage.llm_calls == 1


# --------------------------------------------------------------------------- provider selection


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_make_llm_selects_the_provider(settings_env: pytest.MonkeyPatch) -> None:
    settings_env.setenv("LLM_PROVIDER", "anthropic")
    get_settings.cache_clear()
    assert isinstance(make_llm(), AnthropicLLM)

    settings_env.setenv("LLM_PROVIDER", "claude_cli")
    settings_env.setenv("CLAUDE_CLI_MODEL", "claude-opus-5-5")
    settings_env.setenv("CLAUDE_CLI_EFFORT", "high")
    settings_env.setenv("CLAUDE_CLI_PATH", "/opt/claude")
    get_settings.cache_clear()
    made = make_llm()
    assert isinstance(made, ClaudeCodeLLM)
    assert (made.model, made.effort, made.cli_path) == ("claude-opus-5-5", "high", "/opt/claude")
    assert made.model_for("fast") == made.model_for("strong") == "claude-opus-5-5"
