"""The agent's prompts describe the capability registry, orders, events, enabled and audience."""

import json
import re

import pytest

from app.agent import prompts
from app.agent.checks import check_acceptance, check_sample_record
from app.botspec.models import BotSpec, OrdersCapability
from app.botspec.patch import apply_patch
from app.botspec.validate import validate_spec
from app.capabilities import REGISTRY_IDS
from app.testing.orders_driver import OrdersDriver


def _field(key: str, label: str, type_: str, required: bool) -> dict:
    return {"key": key, "label": label, "type": type_, "required": required, "choices": None, "default": None}


def _section(text: str, heading: str) -> str:
    start = text.index(f"## {heading}")
    nxt = text.find("\n## ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def test_system_prompt_lists_every_registry_id() -> None:
    registry = _section(prompts.system_prompt(), "Capability registry")
    assert len(REGISTRY_IDS) == 18
    for cap_id in REGISTRY_IDS:
        assert f"| {cap_id} |" in registry, cap_id


def test_system_prompt_documents_orders_events_enabled_audience() -> None:
    text = prompts.system_prompt()
    assert "## orders" in text
    assert "payment_status" in text and "unpaid" in text
    assert 'preset: "events"' in text and "reminder_hours_before" in text and "category_field" in text
    assert "## enabled and audience" in text
    assert "instead of removing it" in text
    for audience in ("everyone", "staff", "managers"):
        assert f'"{audience}"' in text
    assert "Capability Center" in text
    # the unsupported list stays honest
    assert "Online payment" in text and "external calendars" in text and "arbitrary code" in text
    assert "four capability types" not in text


def test_registry_section_is_generated_and_cached() -> None:
    assert prompts.system_prompt() is prompts.system_prompt()
    assert prompts.system_prompt().rstrip().endswith("|")  # registry table is the last section


def test_testgen_lists_exactly_the_orders_driver_steps() -> None:
    text = prompts.load("testgen")
    block = text[text.index("- orders, exactly these") : text.index("Only test capabilities")]
    listed = set(re.findall(r"- `([a-z_]+)` \(", block))
    assert listed == set(OrdersDriver.supported)
    assert "Never use expect_booking" in block


def test_catalog_orders_example_validates() -> None:
    catalog = prompts.load("catalog")
    block = catalog[catalog.index("Default shape (use it unless") :]
    example = json.loads(block[block.index("```\n") + 4 : block.index("\n```", block.index("```\n") + 4)])
    resource = {
        "key": "product",
        "label": "کالا",
        "label_plural": "کالاها",
        "title_field": "title",
        "fields": [
            _field("title", "عنوان", "text", True),
            _field("price", "قیمت", "integer", True),
            _field("stock", "موجودی", "integer", False),
        ],
    }
    spec = BotSpec.model_validate(
        {
            "bot": {"name": "ف", "welcome_text": "سلام"},
            "resources": [resource],
            "capabilities": [example],
            "menu": [{"key": "shop", "label": "فروشگاه", "capability": "shop", "view": "main"}],
        }
    )
    assert isinstance(spec.capabilities[0], OrdersCapability)
    assert not [i for i in validate_spec(spec) if i.severity == "error"]


def _orders_spec() -> BotSpec:
    from app.capabilities.registry import REGISTRY_BY_ID

    base = BotSpec.model_validate(
        {
            "bot": {"name": "ف", "welcome_text": "سلام"},
            "resources": [
                {
                    "key": "product",
                    "label": "کالا",
                    "label_plural": "کالاها",
                    "title_field": "title",
                    "fields": [
                        _field("title", "عنوان", "text", True),
                        _field("price", "قیمت", "integer", False),
                    ],
                }
            ],
            "capabilities": [
                {
                    "type": "catalog",
                    "key": "items",
                    "title": "کالاها",
                    "resource": "product",
                    "detail_fields": ["price"],
                }
            ],
            "menu": [{"key": "items", "label": "کالاها", "capability": "items", "view": "main"}],
        }
    )
    ops = REGISTRY_BY_ID["orders"].default_ops(base)
    assert ops is not None
    return apply_patch(base, ops)


def _scenario(seed_values: list[dict[str, str]], steps: list[dict]) -> dict:
    return {
        "id": "acc_order",
        "title": "سفارش",
        "requirement_ids": ["R1"],
        "capability_keys": ["orders"],
        "seed": [{"ref": "p1", "collection": "product", "values": seed_values}],
        "steps": steps,
    }


@pytest.mark.parametrize("priced", [True, False])
def test_check_acceptance_accepts_orders_steps_and_requires_a_price(priced: bool) -> None:
    spec = _orders_spec()
    values = [{"key": "title", "value": "چای"}] + ([{"key": "price", "value": "50000"}] if priced else [])
    steps = [
        {"do": "submit_request", "actor": "ali", "capability": "orders", "item": "p1", "expect": "submitted"},
        {"do": "expect_request", "actor": "ali", "capability": "orders", "expect": "new"},
        {
            "do": "owner_action",
            "capability": "orders",
            "action": "confirm",
            "target_actor": "ali",
            "expect": "ok",
        },
        {"do": "expect_request", "actor": "ali", "capability": "orders", "expect": "confirmed"},
        {"do": "expect_notified", "actor": "ali", "event": "order_status_changed"},
    ]
    sc, issues = check_acceptance(_scenario(values, steps), req_ids={"R1"}, spec=spec)
    if priced:
        assert issues == [] and sc is not None
    else:
        assert sc is None and any("price" in i for i in issues)


def test_check_acceptance_rejects_booking_steps_and_bad_statuses_on_orders() -> None:
    spec = _orders_spec()
    values = [{"key": "title", "value": "چای"}, {"key": "price", "value": "1"}]
    steps = [
        {"do": "expect_booking", "actor": "ali", "capability": "orders", "item": "p1", "expect": "confirmed"},
        {"do": "expect_request", "actor": "ali", "capability": "orders", "expect": "shipped"},
    ]
    _, issues = check_acceptance(_scenario(values, steps), req_ids={"R1"}, spec=spec)
    assert any("needs a booking capability" in i for i in issues)
    assert any("not a status" in i for i in issues)


def test_check_sample_record_requires_price_for_orders_items() -> None:
    spec = _orders_spec()
    bare = {"ref": "s1", "collection": "product", "values": [{"key": "title", "value": "چای"}]}
    seed, problem = check_sample_record(bare, spec)
    assert seed is None and problem is not None and "price" in problem
    full = {**bare, "values": [*bare["values"], {"key": "price", "value": "50000"}]}
    seed, problem = check_sample_record(full, spec)
    assert seed is not None and problem is None


def test_prompts_do_not_ask_the_model_to_design_menus() -> None:
    """Navigation is generated (runtime/nav.py): the model writes `menu: []` and never edits items."""
    system = prompts.system_prompt()
    assert '"menu": []' in system
    assert "## Navigation is generated" in system
    assert "## Menu" not in system
    for stale in ("8 items or fewer", '"main" menu item', '"mine" menu item', "1 to 8", '["menu"'):
        assert stale not in system, stale
    build = prompts.load("build")
    assert '"menu": []' in build and "8 items" not in build and '"mine" menu' not in build
    change = prompts.load("build_change")
    assert "not menu edits" in change and "enabled" in change
    assert "menu item" not in prompts.load("triage")
