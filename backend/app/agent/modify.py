"""Deterministic MODIFY rules (roadmap: "Modification Workflow").

Everything here is plain Python over models; no LLM, no database:

- ``merge_delta``: fold a model-proposed ``RequirementsDelta`` into the run's CUMULATIVE delta
  against the base requirements (new ids continue the numbering, ``changed`` and ``removed`` only
  name base ids, statements equal after normalization are not changes).
- ``uncovered_requirements``: added or changed requirements no passing new scenario cites.
- ``apply_delta``: the run's new requirements = base requirements with the delta applied.
- ``supersede_refusal``: the supersede guard (a carried-forward acceptance scenario may be retired
  only when its requirement ids intersect the delta's changed or removed ids).
- ``risk_level``: the review card's deterministic risk rule.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
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


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يكة", "01234567890123456789یکه")


def normalize_statement(text: str) -> str:
    """Comparison key for requirement statements: case, digits (Persian/Arabic/ASCII), Arabic
    letter variants, whitespace, zero-width joiners and punctuation do not count as a change."""
    text = unicodedata.normalize("NFKC", text).translate(_DIGITS).casefold()
    return "".join(
        ch for ch in text if unicodedata.category(ch)[0] not in ("P", "Z", "C") and not ch.isspace()
    )


def same_statement(a: str, b: str) -> bool:
    return normalize_statement(a) == normalize_statement(b)


@dataclass
class DeltaMerge:
    delta: RequirementsDelta  # cumulative, relative to the base revision
    touched: set[str] = field(default_factory=set)  # ids added, changed, reverted or removed now


def _empty_delta() -> RequirementsDelta:
    return RequirementsDelta(added=[], changed=[], removed=[], unsupported=[], open_questions=[])


def merge_delta(prev: RequirementsDelta | None, raw: RequirementsDelta, base: Requirements) -> DeltaMerge:
    """Fold a model-proposed delta into the run's cumulative delta (relative to ``base``).

    The run's delta is CUMULATIVE: whatever earlier rounds of this run added, changed or removed
    stays unless this round says otherwise. Later statements win; ids stay stable.

    - ``changed`` naming a base id changes it; a statement equal to the base one (after
      ``normalize_statement``) is no change, and reverts an earlier change or removal of that id.
      Naming an id added earlier in this run updates that addition. Any other id is an addition.
    - ``added`` items get fresh ids after the highest base and run id, whatever ids the model
      proposed; an addition whose statement equals an existing addition or base requirement is
      a duplicate and ignored (so a model re-listing earlier additions changes nothing).
    - ``removed`` keeps base ids (and wins over a change of the same id); naming an id added earlier
      in this run drops that addition; unknown ids are ignored.
    ``unsupported`` and ``open_questions`` come from this round only.
    """
    prev = prev or _empty_delta()
    base_by = {r.id: r for r in base.items}
    changed: dict[str, Requirement] = {r.id: r for r in prev.changed}
    removed: list[str] = list(prev.removed)
    added: dict[str, Requirement] = {r.id: r for r in prev.added}
    touched: set[str] = set()
    counter = [next_requirement_number(base.items, prev.added)]

    def add_new(item: Requirement) -> None:
        if any(same_statement(a.statement, item.statement) for a in added.values()):
            return
        if any(same_statement(b.statement, item.statement) for b in base.items):
            return
        rid = f"R{counter[0]}"
        counter[0] += 1
        added[rid] = item.model_copy(update={"id": rid})
        touched.add(rid)

    def change(item: Requirement) -> None:
        rid = item.id
        old = base_by.get(rid)
        if old is not None:
            if same_statement(item.statement, old.statement):  # back to the base meaning
                if rid in changed or rid in removed:
                    touched.add(rid)
                changed.pop(rid, None)
                if rid in removed:
                    removed.remove(rid)
                return
            prior = changed.get(rid)
            if prior is None or not same_statement(prior.statement, item.statement) or rid in removed:
                touched.add(rid)
            changed[rid] = item
            if rid in removed:
                removed.remove(rid)
        elif rid in added:
            if not same_statement(added[rid].statement, item.statement):
                added[rid] = item
                touched.add(rid)
        else:
            add_new(item)

    for item in raw.added:
        known = added.get(item.id)
        if known is not None and same_statement(known.statement, item.statement):
            continue  # an earlier addition re-listed
        add_new(item)
    for item in raw.changed:
        change(item)
    for rid in raw.removed:
        if rid in base_by:
            if rid not in removed:
                removed.append(rid)
                touched.add(rid)
            changed.pop(rid, None)
        elif rid in added:
            del added[rid]
            touched.add(rid)
    order = {r.id: i for i, r in enumerate(base.items)}
    return DeltaMerge(
        RequirementsDelta(
            added=list(added.values()),
            changed=sorted(changed.values(), key=lambda r: order.get(r.id, 0)),
            removed=removed,
            unsupported=list(raw.unsupported),
            open_questions=list(raw.open_questions),
        ),
        touched,
    )


def normalize_delta(delta: RequirementsDelta, base: Requirements) -> RequirementsDelta:
    """A first-round delta made well-formed against ``base`` (see ``merge_delta``)."""
    return merge_delta(None, delta, base).delta


def uncovered_requirements(
    delta: RequirementsDelta | None, scenarios: list[Scenario], new_ids: list[str], passed: set[str]
) -> list[Requirement]:
    """Added or changed requirements no passing new acceptance scenario of this run cites."""
    if delta is None:
        return []
    covered: set[str] = set()
    for s in scenarios:
        if s.id in new_ids and s.id in passed:
            covered |= set(s.requirement_ids)
    return [r for r in [*delta.added, *delta.changed] if r.id not in covered]


def uncovered_text(items: list[Requirement]) -> str:
    names = "، ".join(f"{r.id} («{r.statement}»)" for r in items)
    return f"این نیازمندی‌ها هنوز با آزمون موفقی ثابت نشده‌اند: {names}"


def requirements_card(delta: RequirementsDelta | None, base: Requirements) -> dict[str, list[dict[str, str]]]:
    """The review card's requirement delta: what the agent declared added, changed, removed."""
    if delta is None:
        return {"added": [], "changed": [], "removed": []}
    base_by = {r.id: r.statement for r in base.items}
    return {
        "added": [{"id": r.id, "statement": r.statement} for r in delta.added],
        "changed": [
            {"id": r.id, "before": base_by.get(r.id, ""), "after": r.statement} for r in delta.changed
        ],
        "removed": [{"id": rid, "statement": base_by.get(rid, "")} for rid in delta.removed],
    }


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
