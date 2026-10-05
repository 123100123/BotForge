"""Deterministic dependency resolution over the capability registry (pure functions, no I/O).

Edges: ``requires`` (all of), ``requires_any`` (at least one of; when none is on, the first member
is chosen), ``conflicts`` (mutually exclusive; checked in both directions).

``plan_enable`` returns ``will_enable`` in dependency order (dependencies first, the target last),
excluding capabilities already enabled. ``plan_disable`` returns ``will_disable`` with dependents
first and the target last: every enabled capability that would lose a ``requires`` member, or the
last enabled member of its ``requires_any`` group, is disabled with it (transitively).

Both are cycle-safe (a cycle never loops; the registry integrity test forbids cycles anyway) and
order ties by registry order, so the same inputs always give the same plan.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol


class Node(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def requires(self) -> Sequence[str]: ...
    @property
    def requires_any(self) -> Sequence[str]: ...
    @property
    def conflicts(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class Plan:
    target: str
    action: Literal["enable", "disable"]
    will_enable: list[str] = field(default_factory=list)
    will_disable: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)


def _index(registry: Iterable[Node]) -> tuple[dict[str, Node], dict[str, int]]:
    by_id: dict[str, Node] = {}
    order: dict[str, int] = {}
    for i, node in enumerate(registry):
        by_id[node.id] = node
        order[node.id] = i
    return by_id, order


def plan_enable(registry: Sequence[Node], enabled_ids: Iterable[str], target: str) -> Plan:
    by_id, order = _index(registry)
    if target not in by_id:
        raise KeyError(target)
    enabled = set(enabled_ids)
    out: list[str] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(cid: str) -> None:
        if cid in done or cid in visiting or cid not in by_id:
            return
        visiting.add(cid)
        node = by_id[cid]
        for dep in node.requires:
            if dep not in enabled:
                visit(dep)
        if node.requires_any:
            chosen = set(out) | {cid}
            if not any(m in enabled or m in chosen for m in node.requires_any):
                visit(node.requires_any[0])
        visiting.discard(cid)
        done.add(cid)
        if cid not in enabled:
            out.append(cid)

    visit(target)

    after = enabled | set(out)
    blocked: set[str] = set()
    for cid in out:
        for other in after - {cid}:
            if other in by_id[cid].conflicts or (other in by_id and cid in by_id[other].conflicts):
                blocked.add(other)
    blocked_by = sorted(blocked, key=lambda c: order.get(c, len(order)))
    return Plan(target=target, action="enable", will_enable=out, blocked_by=blocked_by)


def plan_disable(registry: Sequence[Node], enabled_ids: Iterable[str], target: str) -> Plan:
    by_id, order = _index(registry)
    if target not in by_id:
        raise KeyError(target)
    enabled = set(enabled_ids)
    off: set[str] = {target} if target in enabled else set()
    if not off:
        return Plan(target=target, action="disable")

    changed = True
    while changed:
        changed = False
        for node in registry:
            cid = node.id
            if cid not in enabled or cid in off:
                continue
            lost_required = any(dep in off for dep in node.requires)
            still_any = [m for m in node.requires_any if m in enabled and m not in off]
            lost_any = bool(node.requires_any) and not still_any
            if lost_required or lost_any:
                off.add(cid)
                changed = True

    # Dependents before what they depend on; the target last. A node goes out once none of the
    # still-pending nodes depends on it.
    pending = sorted(off - {target}, key=lambda c: order[c])
    out: list[str] = []
    while pending:
        progressed = False
        for cid in list(pending):
            blockers = [
                p for p in pending if p != cid and (cid in by_id[p].requires or cid in by_id[p].requires_any)
            ]
            if not blockers:
                out.append(cid)
                pending.remove(cid)
                progressed = True
                break
        if not progressed:  # a cycle: fall back to registry order
            out.extend(pending)
            break
    out.append(target)
    return Plan(target=target, action="disable", will_disable=out)


def find_cycle(registry: Sequence[Node]) -> list[str] | None:
    """A ``requires``/``requires_any`` cycle as an id path, or None (used by integrity tests)."""
    by_id, _ = _index(registry)
    state: dict[str, int] = {}  # 1 = on stack, 2 = done
    stack: list[str] = []

    def dfs(cid: str) -> list[str] | None:
        state[cid] = 1
        stack.append(cid)
        node = by_id[cid]
        for dep in [*node.requires, *node.requires_any]:
            if dep not in by_id:
                continue
            if state.get(dep) == 1:
                return [*stack[stack.index(dep) :], dep]
            if state.get(dep) is None and (found := dfs(dep)) is not None:
                return found
        stack.pop()
        state[cid] = 2
        return None

    for node in registry:
        if state.get(node.id) is None and (found := dfs(node.id)) is not None:
            return found
    return None
