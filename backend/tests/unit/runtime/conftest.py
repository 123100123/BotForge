from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.validate import validate_spec
from tests.unit.runtime.harness import Harness, load_example


def build_catalog_spec(
    catalog: dict[str, Any] | None = None, info_pages: int = 1, validate: bool = True
) -> BotSpec:
    """A small valid spec: an ``events`` catalog over resource ``event`` plus an ``info`` cap."""
    pages = [
        {"key": f"p{i}", "title": f"صفحه {i}", "body": f"متن صفحه {i}"} for i in range(1, info_pages + 1)
    ]
    data: dict[str, Any] = {
        "bot": {"name": "ربات آزمایشی", "welcome_text": "خوش آمدید!"},
        "resources": [
            {
                "key": "event",
                "label": "رویداد",
                "label_plural": "رویدادها",
                "title_field": "title",
                "fields": [
                    {"key": "title", "label": "عنوان", "type": "text"},
                    {"key": "starts_at", "label": "زمان شروع", "type": "datetime"},
                    {"key": "price", "label": "هزینه", "type": "integer", "required": False},
                    {"key": "online", "label": "آنلاین", "type": "boolean", "required": False},
                ],
            }
        ],
        "capabilities": [
            {
                "type": "catalog",
                "key": "events",
                "title": "فهرست رویدادها",
                "resource": "event",
                "detail_fields": ["starts_at", "price", "online"],
                **(catalog or {}),
            },
            {"type": "info", "key": "info", "title": "دربارهٔ ما", "pages": pages},
        ],
        "menu": [
            {"key": "events_menu", "label": "رویدادها", "capability": "events"},
            {"key": "about", "label": "دربارهٔ ما", "capability": "info"},
        ],
    }
    spec = BotSpec.model_validate(data)
    if validate:
        errors = [i for i in validate_spec(spec) if i.severity == "error"]
        assert not errors, errors
    return spec


@pytest.fixture
def workshop() -> BotSpec:
    return load_example("workshop.botspec.json")


@pytest.fixture
def repair() -> BotSpec:
    return load_example("repair.botspec.json")


@pytest.fixture
def workshop_h(workshop: BotSpec) -> Harness:
    return Harness(workshop)
