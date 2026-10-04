"""Shared helpers for the testing-package tests: spec variants built with ``apply_patch``."""

import json
from pathlib import Path
from typing import Any

from app.botspec.models import BotSpec
from app.botspec.patch import PatchOp, apply_patch
from app.testing.scenario import KV, Scenario, SeedRecord, Step

EXAMPLES = Path(__file__).resolve().parents[4] / "examples"
CAP = "book_workshop"
BOOK = ["capabilities", CAP]


def load_example(name: str) -> BotSpec:
    return BotSpec.model_validate(json.loads((EXAMPLES / name).read_text(encoding="utf-8")))


def workshop() -> BotSpec:
    return load_example("workshop.botspec.json")


def op(kind: str, path: list[str], value: Any = None, before: str | None = None) -> PatchOp:
    return PatchOp(op=kind, path=path, value=value, before=before)  # type: ignore[arg-type]


def set_cap(field: str, value: Any) -> PatchOp:
    return op("set", [*BOOK, *field.split(".")], value)


def patched(*ops: PatchOp, spec: BotSpec | None = None) -> BotSpec:
    return apply_patch(spec or workshop(), list(ops))


PER_ITEM = [
    op("add", ["resources", "workshop", "fields"], {"key": "seats", "label": "ظرفیت", "type": "integer"}),
    set_cap("capacity", {"mode": "per_item", "field": "seats"}),
]

FORM_FIELDS = [
    op(
        "add",
        [*BOOK, "form_fields"],
        {"key": "level", "label": "سطح", "type": "choice", "choices": ["مبتدی", "پیشرفته"]},
    ),
    op("add", [*BOOK, "form_fields"], {"key": "note", "label": "توضیح", "type": "text", "required": False}),
    op("add", [*BOOK, "form_fields"], {"key": "phone", "label": "تلفن", "type": "phone"}),
    op("add", [*BOOK, "form_fields"], {"key": "tools", "label": "ابزار دارید؟", "type": "boolean"}),
    op("add", [*BOOK, "form_fields"], {"key": "age", "label": "سن", "type": "integer", "required": False}),
    op("add", [*BOOK, "form_fields"], {"key": "budget", "label": "بودجه", "type": "decimal"}),
    op("add", [*BOOK, "form_fields"], {"key": "bio", "label": "معرفی", "type": "long_text"}),
]


def seed_item(ref: str = "w1", title: str = "کارگاه عکاسی", start: str = "+48h", **extra: str) -> SeedRecord:
    values = {
        "title": title,
        "description": "توضیح",
        "teacher": "مریم احمدی",
        "starts_at": start,
        **extra,
    }
    return SeedRecord(ref=ref, collection="workshop", values=[KV(key=k, value=v) for k, v in values.items()])


def step(do: str, **kw: Any) -> Step:
    if do not in ("advance_time", "expect_notified"):
        kw.setdefault("capability", CAP)
    return Step.model_validate({"do": do, **kw})


def scenario(steps: list[Step], seed: list[SeedRecord] | None = None, **kw: Any) -> Scenario:
    return Scenario(
        id=kw.pop("id", "t"),
        title=kw.pop("title", "آزمایش"),
        source="acceptance",
        seed=[seed_item()] if seed is None else seed,
        steps=steps,
        **kw,
    )
