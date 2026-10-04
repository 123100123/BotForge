"""testgen (modify): derived from the draft + every carried-forward acceptance scenario + new ones.

- Derived scenarios are regenerated from the draft.
- Every acceptance scenario of the base revision is carried forward unchanged (same id, same
  content). A scenario superseded earlier in this run stays superseded only while the current delta
  still releases it (its requirement ids intersect the changed or removed ids).
- One structured call writes acceptance scenarios for the added and changed requirements only,
  validated like CREATE (``check_acceptance``) plus: each must reference an added or changed id.
  Their ids are recorded in ``new_scenario_ids`` (the only ids ``fix_scenario`` accepts).
"""

from typing import Any

from app.agent import events as ev
from app.agent import prompts
from app.agent.checks import check_acceptance, compact_json, requirement_ids
from app.agent.context import Next, RunContext
from app.agent.llm import LLMError
from app.agent.modify import releasable_ids, target_ids
from app.agent.phases import BUDGET_MESSAGE, section
from app.agent.phases.testgen import AcceptanceOut, _unique_id
from app.agent.prompts import system_prompt
from app.botspec.outline import spec_outline
from app.testing.derive import derive_scenarios
from app.testing.scenario import Scenario


def retained_scenarios(ctx: RunContext, targets: set[str]) -> list[Scenario]:
    """This run's new scenarios from earlier rounds that still hold.

    Dropped when a requirement they cite was touched in the latest round, when they no longer cite
    any added or changed requirement, or when they no longer validate against the current draft.
    """
    state = ctx.state
    touched = set(state.delta_touched)
    kept: list[Scenario] = []
    for s in state.scenarios:
        if s.id not in state.new_scenario_ids:
            continue
        cites = set(s.requirement_ids)
        if cites & touched or not cites & targets:
            continue
        sc, _ = _check(s.model_dump(mode="json"), ctx, targets)
        if sc is not None:
            kept.append(sc.model_copy(update={"id": s.id}))
    return kept


def _message(*sections: str) -> dict[str, Any]:
    body = "\n\n".join([prompts.load("testgen_change"), prompts.load("testgen"), *sections])
    return {"role": "user", "content": body}


def _check(raw: Any, ctx: RunContext, targets: set[str]) -> tuple[Scenario | None, list[str]]:
    state = ctx.state
    assert state.draft_spec is not None
    sc, problems = check_acceptance(raw, req_ids=requirement_ids(state.requirements), spec=state.draft_spec)
    if sc is not None and not set(sc.requirement_ids) & targets:
        return None, [f"requirement_ids must include an added or changed requirement id ({sorted(targets)})"]
    return sc, problems


async def author(ctx: RunContext, targets: set[str], notes: list[str]) -> list[Scenario]:
    """The one structured call (plus one corrective retry for invalid scenarios)."""
    state = ctx.state
    assert state.draft_spec is not None and state.requirements is not None
    focus = [r for r in state.requirements.items if r.id in targets]
    first = _message(
        section("requirements", state.requirements),
        section("changed_requirements", [r.model_dump(mode="json") for r in focus]),
        section("bot_outline", spec_outline(state.draft_spec)),
    )
    try:
        out, usage = await ctx.llm.structured(
            task="testgen", system=system_prompt(), messages=[first], schema=AcceptanceOut, tier="strong"
        )
    except LLMError as exc:
        ctx.charge(exc.usage)
        notes.append(f"acceptance authoring failed: {exc.code}")
        return []
    ctx.charge(usage)
    assert isinstance(out, AcceptanceOut)
    pending = list(out.scenarios)
    accepted: list[Scenario] = []
    invalid: list[tuple[Any, list[str]]] = []
    for raw in pending:
        sc, problems = _check(raw, ctx, targets)
        if sc is None:
            invalid.append((raw, problems))
        else:
            accepted.append(sc)
    if invalid and not ctx.over_budget():
        feedback = [
            {"id": raw.get("id") if isinstance(raw, dict) else None, "problems": problems}
            for raw, problems in invalid
        ]
        retry_messages = [
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
        try:
            out, usage = await ctx.llm.structured(
                task="testgen",
                system=system_prompt(),
                messages=retry_messages,
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
        fixed = 0
        for raw in retried[: len(invalid)]:
            sc, _ = _check(raw, ctx, targets)
            if sc is not None:
                accepted.append(sc)
                fixed += 1
        if fixed < len(invalid):
            notes.append(f"{len(invalid) - fixed} invalid acceptance scenario(s) dropped after one retry")
    elif invalid:
        notes.append(f"{len(invalid)} invalid acceptance scenario(s) dropped (budget)")
    return accepted


async def run(ctx: RunContext) -> Next:
    state = ctx.state
    assert state.draft_spec is not None and state.requirements is not None
    state.derived = derive_scenarios(state.draft_spec)
    notes: list[str] = []

    # Carried forward: every acceptance scenario of the base, minus those still validly superseded.
    snapshot = await ctx.repo.load_revision(state.base_revision_id or "")
    base_acceptance = [s for s in snapshot.scenarios if s.source == "acceptance"]
    releasable = releasable_ids(state.delta)
    state.superseded = [s for s in state.superseded if set(s.scenario.requirement_ids) & releasable]
    retired = {s.scenario.id for s in state.superseded}
    carried = [s for s in base_acceptance if s.id not in retired]
    state.carried_ids = [s.id for s in carried]

    targets = target_ids(state.delta)
    # New scenarios from earlier rounds of this run are kept unless a requirement they cite was
    # added, changed or removed in the latest round (then they are regenerated).
    kept = retained_scenarios(ctx, targets)
    covered = {rid for s in kept for rid in s.requirement_ids}
    focus = targets - covered
    accepted: list[Scenario] = []
    if not targets:
        notes.append("no added or changed requirements: no new acceptance scenarios")
    elif not focus:
        notes.append(f"kept {len(kept)} new scenario(s) from the previous round; nothing to rewrite")
    elif ctx.over_budget():
        state.approval_blocked_reason = BUDGET_MESSAGE + " آزمون‌های تغییر نوشته نشد."
        notes.append("token budget exhausted: no new acceptance scenarios")
    else:
        accepted = await author(ctx, focus, notes)

    taken = {s.id for s in state.derived} | {s.id for s in base_acceptance} | {s.id for s in kept}
    authored: list[Scenario] = []
    for sc in accepted:
        new_id = _unique_id(sc.id, taken)
        taken.add(new_id)
        authored.append(sc.model_copy(update={"id": new_id}))
    if len(authored) > ctx.limits.max_change_acceptance:
        notes.append(f"kept the first {ctx.limits.max_change_acceptance} of {len(authored)} new scenarios")
        authored = authored[: ctx.limits.max_change_acceptance]
    new = [*kept, *authored]
    if targets and not new:
        notes.append("no valid acceptance scenario for the changed requirements")
    # Coverage of every added/changed requirement is enforced at review (uncovered_requirements).

    state.scenarios = [*carried, *new]
    state.new_scenario_ids = [s.id for s in new]
    await ctx.emit(ev.tests_generated(len(state.derived), len(state.scenarios), notes))
    return Next("run")
