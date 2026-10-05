"""Dependency resolution: requires chains, requires_any, conflicts, disable cascades, determinism."""

from dataclasses import dataclass

import pytest

from app.capabilities.registry import REGISTRY
from app.capabilities.resolve import find_cycle, plan_disable, plan_enable


@dataclass(frozen=True)
class N:
    id: str
    requires: tuple[str, ...] = ()
    requires_any: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


CHAIN = [N("a"), N("b", requires=("a",)), N("c", requires=("b",)), N("d", requires=("c", "a"))]


def test_enable_chain_in_dependency_order() -> None:
    plan = plan_enable(CHAIN, set(), "d")
    assert plan.will_enable == ["a", "b", "c", "d"]
    assert plan.blocked_by == []


def test_enable_skips_already_enabled() -> None:
    assert plan_enable(CHAIN, {"a", "b"}, "d").will_enable == ["c", "d"]


def test_enable_already_enabled_target_is_empty() -> None:
    assert plan_enable(CHAIN, {"a", "b", "c", "d"}, "d").will_enable == []


def test_requires_any_picks_first_member_when_none_enabled() -> None:
    reg = [N("x"), N("y"), N("t", requires_any=("x", "y"))]
    assert plan_enable(reg, set(), "t").will_enable == ["x", "t"]


def test_requires_any_satisfied_by_enabled_member() -> None:
    reg = [N("x"), N("y"), N("t", requires_any=("x", "y"))]
    assert plan_enable(reg, {"y"}, "t").will_enable == ["t"]


def test_requires_any_satisfied_by_member_chosen_through_requires() -> None:
    reg = [N("x"), N("y"), N("t", requires=("y",), requires_any=("x", "y"))]
    assert plan_enable(reg, set(), "t").will_enable == ["y", "t"]


def test_conflicts_block_both_directions() -> None:
    reg = [N("a"), N("b", conflicts=("a",)), N("c", requires=("b",))]
    assert plan_enable(reg, {"a"}, "c").blocked_by == ["a"]
    assert plan_enable(reg, {"b"}, "a").blocked_by == ["b"]
    assert plan_enable(reg, set(), "a").blocked_by == []


def test_disable_cascades_to_transitive_dependents() -> None:
    plan = plan_disable(CHAIN, {"a", "b", "c", "d"}, "a")
    assert plan.will_disable == ["d", "c", "b", "a"]


def test_disable_leaf_only_itself() -> None:
    assert plan_disable(CHAIN, {"a", "b", "c", "d"}, "d").will_disable == ["d"]


def test_disable_not_enabled_is_empty() -> None:
    assert plan_disable(CHAIN, {"a"}, "b").will_disable == []


def test_disable_requires_any_only_when_last_member_goes() -> None:
    reg = [N("x"), N("y"), N("t", requires_any=("x", "y"))]
    assert plan_disable(reg, {"x", "y", "t"}, "x").will_disable == ["x"]
    assert plan_disable(reg, {"x", "t"}, "x").will_disable == ["t", "x"]


def test_cycle_safe_and_detected() -> None:
    reg = [N("a", requires=("b",)), N("b", requires=("a",))]
    plan = plan_enable(reg, set(), "a")
    assert sorted(plan.will_enable) == ["a", "b"]
    assert find_cycle(reg) is not None
    assert sorted(plan_disable(reg, {"a", "b"}, "a").will_disable) == ["a", "b"]


def test_unknown_target_raises() -> None:
    with pytest.raises(KeyError):
        plan_enable(CHAIN, set(), "zzz")


def test_deterministic() -> None:
    plans = {tuple(plan_enable(REGISTRY, set(), "staff_reporting").will_enable) for _ in range(5)}
    assert plans == {("staff", "spreadsheet_intelligence", "staff_reporting")}


def test_real_registry_plans() -> None:
    assert plan_enable(REGISTRY, {"reporting"}, "scheduled_reports").will_enable == ["scheduled_reports"]
    assert plan_enable(REGISTRY, set(), "scheduled_reports").will_enable == ["reporting", "scheduled_reports"]
    assert plan_enable(REGISTRY, set(), "inventory").will_enable == ["catalog", "orders", "inventory"]
    on = {"catalog", "orders", "inventory", "reporting", "copilot", "scheduled_reports"}
    assert plan_disable(REGISTRY, on, "catalog").will_disable == ["inventory", "orders", "catalog"]
    assert plan_disable(REGISTRY, on, "reporting").will_disable == [
        "scheduled_reports",
        "copilot",
        "reporting",
    ]
