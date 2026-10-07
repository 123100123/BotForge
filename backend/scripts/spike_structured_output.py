"""Spike (roadmap open decision O5): strict structured output vs tool input for the full BotSpec.

Sends the golden Persian prompt with the real system prompt (role + catalog) and asks for a complete
BotSpec three ways, then reports for each whether the request was accepted, whether a schema-valid
and semantically valid BotSpec came back, and the token counts and cost:

  structured   output_config.format with the BotSpec JSON schema (anthropic.transform_schema)
  tool         a non-strict set_spec tool; the spec is the tool input
  tool_strict  the same tool with strict: true (may be rejected for schema complexity)

Usage (from backend/, needs ANTHROPIC_API_KEY; costs real money, roughly a few cents per mode):
    uv run python scripts/spike_structured_output.py [--modes structured,tool,tool_strict] [--model ...]

With ``--provider openai`` (default: LLM_PROVIDER) the same modes go through the OpenAI-compatible
endpoint chain (README "Environment"): structured = response_format json_schema, tool = a set_spec
function, tool_strict = the same with "strict": true. ``--endpoint LLM_1`` keeps only that chain
entry (one of LLM_1..LLM_5, or LLM for the plain LLM_BASE_URL endpoint), to check one key at a time.
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

from app.agent.llm import AnthropicLLM, LLMError, ToolDef, _extract_json
from app.agent.llm_openai import OpenAICompatLLM, _content_text, _to_openai, endpoints_from_settings
from app.agent.prompts import load, system_prompt
from app.agent.tools import TOOL_DEFS
from app.botspec.models import BotSpec
from app.botspec.validate import check_spec, has_errors
from app.config import get_settings

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def golden_prompt() -> str:
    text = (EXAMPLES / "prompts.fa.md").read_text(encoding="utf-8")
    return text.split("## Create", 1)[1].split("##", 1)[0].strip()


def user_message(mode: str) -> dict[str, Any]:
    how = (
        "Return the complete BotSpec as the JSON response."
        if mode == "structured"
        else "Call the set_spec tool exactly once with the complete BotSpec."
    )
    owner = f"<owner_messages>\nOwner: {golden_prompt()}\n</owner_messages>"
    return {"role": "user", "content": f"{load('build')}\n\n{owner}\n\n{how}"}


def evaluate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"valid": False, "errors": ["no spec object"]}
    issues = check_spec(raw)
    errors = [f"{'/'.join(i.path)}: {i.code}" for i in issues if i.severity == "error"]
    out: dict[str, Any] = {"valid": not has_errors(issues), "errors": errors[:10]}
    if not errors:
        spec = BotSpec.model_validate(raw)
        booking = next((c for c in spec.capabilities if c.type == "booking"), None)
        if booking is not None:
            out["capacity"] = booking.capacity.model_dump()
            out["waitlist"] = booking.waitlist.model_dump()
            out["cancellation"] = booking.cancellation.model_dump()
    return out


async def run_mode(llm: AnthropicLLM, mode: str) -> dict[str, Any]:
    params = llm._params("spike", "strong", system_prompt(), [user_message(mode)])
    if mode == "structured":
        schema = anthropic.transform_schema(BotSpec.model_json_schema())
        params["output_config"] = {
            **params.get("output_config", {}),
            "format": {"type": "json_schema", "schema": schema},
        }
    else:
        base = TOOL_DEFS["set_spec"]
        tool = ToolDef(base.name, base.description, base.input_schema, strict=(mode == "tool_strict"))
        params["tools"] = [tool.to_api()]
    started = time.perf_counter()
    try:
        message, usage = await llm._call("spike", params)
    except anthropic.BadRequestError as exc:
        return {"mode": mode, "accepted": False, "error": str(exc)[:400]}
    result: dict[str, Any] = {
        "mode": mode,
        "accepted": True,
        "stop_reason": message.stop_reason,
        "served_by": message.model,
        "seconds": round(time.perf_counter() - started, 1),
        "usage": usage.model_dump(),
    }
    if message.stop_reason in ("refusal", "max_tokens"):
        result["valid"] = False
        return result
    raw: Any = None
    if mode == "structured":
        text = "".join(b.text for b in message.content if b.type == "text")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            result["parse_error"] = str(exc)
    else:
        use = next((b for b in message.content if b.type == "tool_use"), None)
        raw = use.input.get("spec") if use is not None and isinstance(use.input, dict) else None
        result["tool_called"] = use is not None
    result.update(evaluate(raw))
    return result


async def run_mode_openai(llm: OpenAICompatLLM, mode: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "messages": _to_openai(system_prompt(), [user_message(mode)]),
        "max_tokens": llm.max_tokens,
    }
    if mode == "structured":
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "BotSpec", "schema": BotSpec.model_json_schema(), "strict": False},
        }
    else:
        base = TOOL_DEFS["set_spec"]
        tool: dict[str, Any] = {
            "type": "function",
            "function": {"name": base.name, "description": base.description, "parameters": base.input_schema},
        }
        if mode == "tool_strict":
            tool["function"]["strict"] = True
        body["tools"] = [tool]
    started = time.perf_counter()
    try:
        message, finish, usage, endpoint = await llm.complete("spike", "strong", body)
    except LLMError as exc:
        return {"mode": mode, "accepted": False, "error": f"{exc.code}: {exc.message}"[:600]}
    result: dict[str, Any] = {
        "mode": mode,
        "accepted": True,
        "stop_reason": finish,
        "served_by": f"{endpoint.label} {endpoint.strong_model}",
        "seconds": round(time.perf_counter() - started, 1),
        "usage": usage.model_dump(),
    }
    if finish in ("length", "content_filter"):
        result["valid"] = False
        return result
    raw: Any = None
    if mode == "structured":
        try:
            raw = _extract_json(_content_text(message.get("content")))
        except json.JSONDecodeError as exc:
            result["parse_error"] = str(exc)
    else:
        calls = message.get("tool_calls") or []
        result["tool_called"] = bool(calls)
        if calls:
            try:
                args = json.loads(calls[0]["function"]["arguments"] or "{}")
                raw = args.get("spec") if isinstance(args, dict) else None
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                result["parse_error"] = str(exc)
    result.update(evaluate(raw))
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--modes", default="structured,tool,tool_strict")
    parser.add_argument("--model", default=None, help="override the strong model")
    parser.add_argument(
        "--provider", choices=("anthropic", "openai"), default=None, help="default: LLM_PROVIDER"
    )
    parser.add_argument("--endpoint", default=None, help="openai provider: keep only this chain entry")
    args = parser.parse_args()
    provider = args.provider or get_settings().LLM_PROVIDER
    if provider == "openai":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        endpoints, problems = endpoints_from_settings(get_settings())
        for problem in problems:
            print(f"config problem: {problem}", file=sys.stderr)
        if args.endpoint:
            endpoints = [e for e in endpoints if e.name == args.endpoint]
        if args.model:
            endpoints = [dataclasses.replace(e, strong_model=args.model) for e in endpoints]
        if not endpoints:
            print("no usable OpenAI-compatible endpoint (README, Environment)", file=sys.stderr)
            return 2
        settings = get_settings()
        compat = OpenAICompatLLM(
            endpoints=endpoints,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
            max_tokens=settings.LLM_MAX_TOKENS,
            price_input_per_m=settings.LLM_PRICE_INPUT_PER_M,
            price_output_per_m=settings.LLM_PRICE_OUTPUT_PER_M,
        )
        print(f"chain: {compat.describe()}")
        for mode in args.modes.split(","):
            print(json.dumps(await run_mode_openai(compat, mode.strip()), ensure_ascii=False, indent=2))
        return 0
    llm = AnthropicLLM(strong_model=args.model, max_tokens=32000)
    print(f"model: {llm.strong_model}")
    total_cost = 0.0
    for mode in args.modes.split(","):
        result = await run_mode(llm, mode.strip())
        total_cost += (result.get("usage") or {}).get("cost_usd", 0.0)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"total cost: ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
