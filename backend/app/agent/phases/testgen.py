"""testgen: derived scenarios from the spec + one structured call authoring acceptance scenarios.

The acceptance author sees the requirements and the spec OUTLINE only (never rule values). Each
scenario must parse as ``Scenario``, reference existing capability keys, and carry at least one
existing requirement id. Invalid ones get one corrective retry, then are dropped with a note.
"""

from typing import Any

from pydantic import BaseModel

from app.agent import events as ev
from app.agent.checks import check_acceptance, compact_json, requirement_ids
from app.agent.context import Next, RunContext
from app.agent.llm import LLMError
from app.agent.phases import BUDGET_MESSAGE, CORRECTIVE_RETRY_REASON, add_block_reason, section, task_message
from app.agent.prompts import system_prompt
from app.botspec.outline import spec_outline
from app.testing.derive import derive_scenarios
from app.testing.scenario import Scenario

NO_ACCEPTANCE = "هیچ آزمون پذیرش معتبری برای خواسته‌های شما نوشته نشد، پس درستی ربات ثابت نشده است."


class AcceptanceOut(BaseModel):
    """Raw scenarios (validated one by one); the JSON schema sent to the model is Scenario's."""

    scenarios: list[dict[str, Any]]

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        item = Scenario.model_json_schema()
        defs = item.pop("$defs", {})
        return {
            "type": "object",
            "properties": {"scenarios": {"type": "array", "items": item}},
            "required": ["scenarios"],
            "additionalProperties": False,
            "$defs": defs,
        }


def _unique_id(raw_id: str, taken: set[str]) -> str:
    base = raw_id if raw_id.startswith("acc_") else f"acc_{raw_id}"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    assert state.draft_spec is not None and state.requirements is not None
    spec = state.draft_spec
    state.derived = derive_scenarios(spec)
    notes: list[str] = []
    accepted: list[Scenario] = []

    if ctx.over_budget():
        state.approval_blocked_reason = BUDGET_MESSAGE + " آزمون‌های پذیرش نوشته نشد."
        notes.append("token budget exhausted: no acceptance scenarios")
    else:
        req_ids = requirement_ids(state.requirements)
        first = task_message(
            "testgen",
            section("requirements", state.requirements),
            section("bot_outline", spec_outline(spec)),
        )
        messages: list[Any] = [first]
        pending: list[Any] = []
        try:
            out, usage = await ctx.llm.structured(
                task="testgen", system=system_prompt(), messages=messages, schema=AcceptanceOut, tier="strong"
            )
            ctx.charge(usage)
            assert isinstance(out, AcceptanceOut)
            pending = list(out.scenarios)
        except LLMError as exc:
            ctx.charge(exc.usage)
            notes.append(f"acceptance authoring failed: {exc.code}")

        invalid: list[tuple[Any, list[str]]] = []
        for raw in pending:
            sc, problems = check_acceptance(raw, req_ids=req_ids, spec=spec)
            if sc is None:
                invalid.append((raw, problems))
            else:
                accepted.append(sc)

        if invalid and not ctx.over_budget():
            feedback = [
                {"id": raw.get("id") if isinstance(raw, dict) else None, "problems": problems}
                for raw, problems in invalid
            ]
            messages = [
                first,
                {"role": "assistant", "content": compact_json({"scenarios": pending})},
                {
                    "role": "user",
                    "content": "These scenarios are invalid:\n"
                    + compact_json(feedback)
                    + '\nReturn {"scenarios": [...]} with corrected versions of ONLY these scenarios, '
                    "keeping their ids. Fix every listed problem.",
                },
            ]
            await ctx.emit(ev.retrying("testgen", 2, CORRECTIVE_RETRY_REASON))
            try:
                out, usage = await ctx.llm.structured(
                    task="testgen",
                    system=system_prompt(),
                    messages=messages,
                    schema=AcceptanceOut,
                    tier="strong",
                )
                ctx.charge(usage)
                assert isinstance(out, AcceptanceOut)
                retried = list(out.scenarios)
            except LLMError as exc:
                ctx.charge(exc.usage)
                retried = []
                notes.append(f"corrective retry failed: {exc.code}")
            fixed_ids: set[str] = set()
            retry_problems: dict[str, list[str]] = {}
            for raw in retried[: len(invalid)]:
                sc, problems = check_acceptance(raw, req_ids=req_ids, spec=spec)
                if sc is not None:
                    accepted.append(sc)
                    fixed_ids.add(sc.id)
                elif isinstance(raw, dict):
                    retry_problems[str(raw.get("id"))] = problems
            dropped = 0
            for raw, problems in invalid:
                rid = str(raw.get("id")) if isinstance(raw, dict) else "?"
                if rid not in fixed_ids:
                    dropped += 1
                    notes.append(f"dropped '{rid}': {'; '.join(retry_problems.get(rid, problems))[:300]}")
            if dropped:
                notes.append(f"{dropped} invalid acceptance scenario(s) dropped after one retry")
        elif invalid:
            notes.append(f"{len(invalid)} invalid acceptance scenario(s) dropped (budget)")

    # Unique ids, never colliding with derived ids; at most max_acceptance.
    taken = {s.id for s in state.derived}
    final: list[Scenario] = []
    for sc in accepted:
        new_id = _unique_id(sc.id, taken)
        taken.add(new_id)
        final.append(sc.model_copy(update={"id": new_id}))
    if len(final) > ctx.limits.max_acceptance:
        notes.append(f"kept the first {ctx.limits.max_acceptance} of {len(final)} acceptance scenarios")
        final = final[: ctx.limits.max_acceptance]
    if len(final) < ctx.limits.min_acceptance:
        notes.append(
            f"only {len(final)} acceptance scenario(s); at least {ctx.limits.min_acceptance} expected"
        )
    if not final:
        # Derived scenarios only prove the runtime honors the spec, not that the spec is what the
        # owner asked for: without one acceptance scenario the bot is unproven.
        add_block_reason(state, NO_ACCEPTANCE)

    state.scenarios = final
    state.new_scenario_ids = [s.id for s in final]
    await ctx.emit(ev.tests_generated(len(state.derived), len(final), notes))
    return Next("run")
