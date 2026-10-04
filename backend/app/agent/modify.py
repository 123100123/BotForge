"""Deterministic MODIFY rules (roadmap: "Modification Workflow").

Everything here is plain Python over models; no LLM, no database:

- ``normalize_delta``: make a model-proposed ``RequirementsDelta`` well-formed against the base
  requirements (new ids continue the base numbering, ``changed`` and ``removed`` only name base ids).
- ``apply_delta``: the run's new requirements = base requirements with the delta applied.
- ``supersede_refusal``: the supersede guard (a carried-forward acceptance scenario may be retired
  only when its requirement ids intersect the delta's changed or removed ids).
- ``risk_level``: the review card's deterministic risk rule.
"""

from __future__ import annotations

import re
from typing import Literal

from app.agent.requirements import Requirement, Requirements, RequirementsDelta
from app.botspec.diff import SpecChange
from app.botspec.validate import SpecIssue
from app.testing.scenario import Scenario

Risk = Literal["low", "medium", "high"]

_RID = re.compile(r"^R(\d+)$")

# Keyed lists whose element additions/removals still count as "text changes" (risk low).
TEXT_LISTS = frozenset({"texts"})


def _num(rid: str) -> int | None:
    m = _RID.match(rid)
    return int(m.group(1)) if m else None


def next_requirement_number(*groups: list[Requirement]) -> int:
    nums = [n for g in groups for r in g if (n := _num(r.id)) is not None]
    return max(nums, default=0) + 1


def empty_requirements() -> Requirements:
    return Requirements(business_summary="", items=[], unsupported=[], open_questions=[])


def normalize_delta(delta: RequirementsDelta, base: Requirements) -> RequirementsDelta:
    """Well-formed delta against ``base``.

    - ``changed`` entries must name a base id; an unknown id is treated as an addition. A change
      whose statement equals the base statement is dropped (nothing changed).
    - ``removed`` keeps only base ids, without duplicates, and wins over a change of the same id.
    - ``added`` items always get fresh ids after the highest base id (never reusing a base or a
      removed id), whatever ids the model proposed.
    """
    base_by = {r.id: r for r in base.items}
    removed: list[str] = []
    for rid in delta.removed:
        if rid in base_by and rid not in removed:
            removed.append(rid)
    changed: list[Requirement] = []
    added_raw: list[Requirement] = list(delta.added)
    seen: set[str] = set()
    for item in delta.changed:
        old = base_by.get(item.id)
        if old is None:
            added_raw.append(item)
            continue
        if item.id in removed or item.id in seen:
            continue
        if item.statement.strip() == old.statement.strip() and item.kind == old.kind:
            continue
        seen.add(item.id)
        changed.append(item)
    n = next_requirement_number(base.items)
    added: list[Requirement] = []
    for item in added_raw:
        added.append(item.model_copy(update={"id": f"R{n}"}))
        n += 1
    return RequirementsDelta(
        added=added,
        changed=changed,
        removed=removed,
        unsupported=list(delta.unsupported),
        open_questions=list(delta.open_questions),
    )


def delta_is_empty(delta: RequirementsDelta) -> bool:
    return not (delta.added or delta.changed or delta.removed)


def apply_delta(base: Requirements, delta: RequirementsDelta) -> Requirements:
    """Base items in order with changes applied and removals dropped, then the additions."""
    changed = {r.id: r for r in delta.changed}
    removed = set(delta.removed)
    items = [changed.get(r.id, r) for r in base.items if r.id not in removed]
    items += delta.added
    return Requirements(
        business_summary=base.business_summary,
        items=items,
        unsupported=list(delta.unsupported),
        open_questions=list(delta.open_questions),
    )


def target_ids(delta: RequirementsDelta | None) -> set[str]:
    """Requirements new acceptance scenarios are written for: added and changed."""
    if delta is None:
        return set()
    return {r.id for r in delta.added} | {r.id for r in delta.changed}


def releasable_ids(delta: RequirementsDelta | None) -> set[str]:
    """Requirements whose carried-forward scenarios may be superseded: changed and removed."""
    if delta is None:
        return set()
    return {r.id for r in delta.changed} | set(delta.removed)


def supersede_refusal(
    scenario: Scenario | None,
    *,
    carried_ids: list[str],
    new_ids: list[str],
    delta: RequirementsDelta | None,
) -> str | None:
    """None when ``scenario`` may be superseded, else an explanation the model can act on."""
    if scenario is None:
        return "unknown scenario id; use an id from the failure list"
    if scenario.source == "derived":
        return (
            "derived scenarios are regenerated from the spec on every run and are never superseded; "
            "if one fails, the spec is wrong: fix it with apply_spec_patch"
        )
    if scenario.id in new_ids:
        return (
            "this scenario was written in this run; if it misstates the requirement, correct it with "
            "fix_scenario instead"
        )
    if scenario.id not in carried_ids:
        return "only carried-forward acceptance scenarios can be superseded"
    releasable = releasable_ids(delta)
    if not set(scenario.requirement_ids) & releasable:
        return (
            f"refused: this scenario checks requirements {sorted(scenario.requirement_ids)}, which "
            f"this change does not touch (changed or removed: {sorted(releasable)}). A carried-forward "
            "scenario for an unchanged requirement that now fails is a regression: fix the spec so "
            "it passes again"
        )
    return None


def _is_text_change(ch: SpecChange) -> bool:
    return any(seg in TEXT_LISTS for seg in ch.path[:-1]) or (bool(ch.path) and ch.path[-1] in TEXT_LISTS)


def risk_level(changes: list[SpecChange], compat: list[SpecIssue]) -> Risk:
    """Deterministic risk (roadmap item 7).

    high:   any compatibility warning (or error).
    medium: any keyed-list element (capability, resource, field, form field, menu item, page,
            status, owner action) added or removed, or a whole element replaced (capability type);
            text override entries are the exception and count as text changes.
    low:    otherwise: only scalar parameter, scalar-list, ordering, or text changes.
    """
    if compat:
        return "high"
    for ch in changes:
        if ch.kind in ("added", "removed") and not _is_text_change(ch):
            return "medium"
        if ch.kind == "changed" and (isinstance(ch.old, dict) or isinstance(ch.new, dict)):
            return "medium"
    return "low"


def requirement_lines(delta: RequirementsDelta, base: Requirements) -> list[str]:
    """Short Persian lines describing the delta (for the owner)."""
    base_by = {r.id: r.statement for r in base.items}
    lines = [f"• جدید: {r.statement}" for r in delta.added]
    lines += [f"• تغییر: {r.statement}" for r in delta.changed]
    lines += [f"• حذف: {base_by.get(rid, rid)}" for rid in delta.removed]
    return lines
