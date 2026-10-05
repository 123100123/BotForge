"""Derived scenarios for orders capabilities (W1-ORD) run green on the real runtime."""

from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.runtime.engines import override_engine
from app.runtime.engines.orders import OrdersEngine
from app.testing.derive import derive_scenarios
from app.testing.runner import run_scenarios
from app.testing.scenario import TestReport
from tests.unit.botspec.test_capability_flags import business_data
from tests.unit.runtime.test_orders import shop_spec

SHOP_IDS = [
    "derived:shop:checkout",
    "derived:shop:out_of_stock",
    "derived:shop:cancel_restocks",
    "derived:shop:non_owner_rejected",
]


def failures(report: TestReport) -> dict[str, str]:
    return {
        r.scenario_id: next(s.message or "" for s in r.steps if not s.passed)
        for r in report.results
        if not r.passed
    }


def shop_scenarios(spec: BotSpec) -> list[Any]:
    return [s for s in derive_scenarios(spec) if s.capability_keys == ["shop"]]


@pytest.mark.parametrize(
    "spec",
    [
        shop_spec(),
        shop_spec(stock_field=None, checkout_fields=[], notify_owner_on=[], notify_user_on=[]),
        BotSpec.model_validate(business_data()),  # no "cancelled" status: no cancel template
        shop_spec(audience="staff"),  # driven as the owner; multi-customer templates dropped
    ],
)
async def test_derived_orders_scenarios_pass(spec: BotSpec) -> None:
    scenarios = shop_scenarios(spec)
    assert scenarios
    report = await run_scenarios(spec, scenarios)
    assert report.failed == 0, failures(report)


def test_template_selection() -> None:
    assert [s.id for s in shop_scenarios(shop_spec())] == SHOP_IDS
    no_stock = [s.id for s in shop_scenarios(shop_spec(stock_field=None))]
    assert "derived:shop:out_of_stock" not in no_stock and "derived:shop:cancel_restocks" in no_stock
    business = [s.id for s in shop_scenarios(BotSpec.model_validate(business_data()))]
    assert "derived:shop:cancel_restocks" not in business
    staff = [s.id for s in shop_scenarios(shop_spec(audience="staff"))]
    assert "derived:shop:out_of_stock" not in staff and "derived:shop:non_owner_rejected" not in staff
    assert shop_scenarios(shop_spec(enabled=False)) == []


class _NoRestock(OrdersEngine):
    async def _move_stock(self, *args: Any, **kwargs: Any) -> None:
        return None


async def test_derived_scenarios_catch_a_missing_restock() -> None:
    spec = shop_spec()
    with override_engine("orders", _NoRestock()):
        report = await run_scenarios(spec, shop_scenarios(spec))
    assert set(failures(report)) == {"derived:shop:cancel_restocks"}
