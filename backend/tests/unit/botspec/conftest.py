import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.botspec.models import BotSpec

EXAMPLES = Path(__file__).resolve().parents[4] / "examples"


def load_json(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def workshop_data() -> dict[str, Any]:
    return copy.deepcopy(load_json("workshop.botspec.json"))


@pytest.fixture
def repair_data() -> dict[str, Any]:
    return copy.deepcopy(load_json("repair.botspec.json"))


@pytest.fixture
def workshop(workshop_data: dict[str, Any]) -> BotSpec:
    return BotSpec.model_validate(workshop_data)


@pytest.fixture
def repair(repair_data: dict[str, Any]) -> BotSpec:
    return BotSpec.model_validate(repair_data)


@pytest.fixture
def scenarios_data() -> list[dict[str, Any]]:
    return copy.deepcopy(load_json("workshop.scenarios.json"))
