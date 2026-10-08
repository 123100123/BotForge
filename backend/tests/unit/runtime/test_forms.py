from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

from app.botspec.models import BotSpec
from app.runtime import forms
from app.runtime.callbacks import FORM_ACTIONS
from app.runtime.ctx import Ctx
from app.runtime.engines import override_engine
from app.runtime.engines.base import EngineBase
from app.runtime.texts import common
from app.runtime.texts import nav as nav_texts
from tests.unit.runtime.harness import Harness, button_data, buttons, text

FIELDS: list[dict[str, Any]] = [
    {"key": "name", "label": "نام", "type": "text"},
    {"key": "size", "label": "اندازه", "type": "choice", "choices": ["کوچک", "متوسط", "بزرگ"]},
    {"key": "urgent", "label": "فوری", "type": "boolean", "required": False},
    {"key": "phone", "label": "تلفن", "type": "phone"},
    {"key": "count", "label": "تعداد", "type": "integer", "required": False, "default": "1"},
]


def make_spec(fields: list[dict[str, Any]] = FIELDS, texts: list[dict[str, str]] | None = None) -> BotSpec:
    return BotSpec.model_validate(
        {
            "bot": {"name": "فرم", "welcome_text": "خوش آمدید"},
            "resources": [],
            "capabilities": [
                {
                    "type": "request",
                    "key": "order",
                    "title": "سفارش",
                    "form_fields": fields,
                    "statuses": [{"key": "new", "label": "جدید"}],
                    "initial_status": "new",
                    "owner_actions": [],
                    "texts": texts or [],
                }
            ],
            "menu": [{"key": "order_menu", "label": "سفارش", "capability": "order"}],
        }
    )


class FakeFormEngine(EngineBase):
    """Minimal form host: open starts the form; completion is recorded."""

    type: ClassVar[str] = "request"

    def __init__(self) -> None:
        self.done: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def open(self, ctx: Ctx, cap: Any, view: str) -> None:
        await forms.start(ctx, self, cap, data={"view": view}, intro="فرم سفارش")

    async def on_callback(self, ctx: Ctx, cap: Any, action: str, arg: str) -> None:
        if action in FORM_ACTIONS:
            await forms.handle_callback(ctx, self, cap, action, arg)
        else:
            ctx.stale()

    async def on_text(self, ctx: Ctx, cap: Any, text: str) -> None:
        await forms.handle_text(ctx, self, cap, text)

    async def on_form_done(self, ctx: Ctx, cap: Any, values: dict[str, Any], data: dict[str, Any]) -> None:
        self.done.append((values, data))
        ctx.reply("ثبت شد")


@pytest.fixture
def engine() -> Iterator[FakeFormEngine]:
    fake = FakeFormEngine()
    with override_engine("request", fake):
        yield fake


@pytest.fixture
def h() -> Harness:
    return Harness(make_spec())


async def field_in_session(h: Harness, actor: str = "ali") -> str | None:
    s = await h.store.get_session(actor)
    return None if s is None else s["vars"]["field"]


async def test_full_form_happy_path(h: Harness, engine: FakeFormEngine) -> None:
    r = await h.tap("ali", "menu:open:order_menu")
    assert text(r) == "فرم سفارش\nلطفاً «نام» را وارد کنید:"
    assert button_data(r) == ["order:stop:"]
    assert await h.store.get_session("ali") == {
        "capability": "order",
        "step": "form",
        "vars": {"field": "name", "answers": {}, "data": {"view": "main"}},
    }

    r = await h.send("ali", "  علی  ")
    assert text(r).startswith("لطفاً «اندازه» را وارد کنید:\n" + common.CHOOSE_HINT)
    assert button_data(r) == ["order:ans:0", "order:ans:1", "order:ans:2", "order:stop:"]
    assert [b.label for b in buttons(r)][:3] == ["کوچک", "متوسط", "بزرگ"]
    assert r.messages[0].edit is False

    r = await h.tap("ali", "order:ans:2")
    assert r.messages[0].edit is True
    assert "«فوری»" in text(r) and common.OPTIONAL_HINT in text(r)
    assert button_data(r) == ["order:ans:0", "order:ans:1", "order:skip:", "order:stop:"]
    assert [b.label for b in buttons(r)][:2] == [common.YES, common.NO]

    r = await h.tap("ali", "order:ans:0")
    assert "«تلفن»" in text(r)
    r = await h.send("ali", "۰۹۱۲ ۱۲۳ ۴۵۶۷")
    assert "«تعداد»" in text(r)
    r = await h.tap("ali", "order:skip:")
    assert text(r) == "ثبت شد"
    assert engine.done == [
        (
            {"name": "علی", "size": "بزرگ", "urgent": True, "phone": "09121234567", "count": 1},
            {"view": "main"},
        )
    ]
    assert await h.store.get_session("ali") is None
    r = await h.send("ali", "متن بعدی")  # the form no longer captures text
    assert text(r) == "خوش آمدید"


async def test_invalid_input_reasks_same_field(h: Harness, engine: FakeFormEngine) -> None:
    await h.tap("ali", "menu:open:order_menu")
    await h.send("ali", "علی")
    r = await h.send("ali", "خیلی بزرگ")  # not a choice
    assert text(r).startswith("پاسخ «اندازه» پذیرفته نشد: «اندازه» باید یکی از این گزینه‌ها باشد")
    assert text(r).endswith("لطفاً دوباره وارد کنید.")
    assert button_data(r) == ["order:ans:0", "order:ans:1", "order:ans:2", "order:stop:"]
    assert await field_in_session(h) == "size"
    r = await h.send("ali", "متوسط")  # typed choice text is accepted
    assert "«فوری»" in text(r)
    r = await h.send("ali", "شاید")  # not a boolean
    assert "«فوری» باید «بله» یا «خیر» باشد" in text(r)
    r = await h.send("ali", "خیر")
    r = await h.send("ali", "abc")
    assert "شمارهٔ تلفن معتبر نیست" in text(r)
    assert await field_in_session(h) == "phone"
    assert engine.done == []


async def test_skip_required_field_is_refused(h: Harness, engine: FakeFormEngine) -> None:
    await h.tap("ali", "menu:open:order_menu")
    r = await h.tap("ali", "order:skip:")
    assert "«نام» الزامی است." in text(r)
    assert await field_in_session(h) == "name"


async def test_optional_skip_stores_none(engine: FakeFormEngine) -> None:
    h = Harness(make_spec([{"key": "note", "label": "توضیح", "type": "long_text", "required": False}]))
    await h.tap("ali", "menu:open:order_menu")
    await h.tap("ali", "order:skip:")
    assert engine.done == [({"note": None}, {"view": "main"})]


async def test_stop_aborts(h: Harness, engine: FakeFormEngine) -> None:
    await h.tap("ali", "menu:open:order_menu")
    await h.send("ali", "علی")
    r = await h.tap("ali", "order:stop:")
    assert text(r) == "فرم لغو شد."
    assert button_data(r) == ["nav:go:sup"]  # the compiled home, not spec.menu
    assert await h.store.get_session("ali") is None
    assert engine.done == []
    r = await h.tap("ali", "order:stop:")  # nothing to stop any more
    assert text(r) == nav_texts.STALE


async def test_bad_answer_index_and_no_session(h: Harness, engine: FakeFormEngine) -> None:
    r = await h.tap("ali", "order:ans:0")
    assert text(r) == nav_texts.STALE
    await h.tap("ali", "menu:open:order_menu")
    r = await h.tap("ali", "order:ans:0")  # "name" is a text field: no choices
    assert text(r).startswith(common.STALE + "\nلطفاً «نام»")
    await h.send("ali", "علی")
    for arg in ("3", "-1", "x", ""):
        r = await h.tap("ali", f"order:ans:{arg}")
        assert text(r).startswith(common.STALE)
        assert await field_in_session(h) == "size"


async def test_forms_are_per_actor(h: Harness, engine: FakeFormEngine) -> None:
    await h.tap("ali", "menu:open:order_menu")
    await h.tap("sara", "menu:open:order_menu")
    await h.send("ali", "علی")
    assert await field_in_session(h, "ali") == "size"
    assert await field_in_session(h, "sara") == "name"


async def test_no_fields_completes_immediately(engine: FakeFormEngine) -> None:
    h = Harness(make_spec([]))
    r = await h.tap("ali", "menu:open:order_menu")
    assert text(r) == "ثبت شد"
    assert engine.done == [({}, {"view": "main"})]
    assert await h.store.get_session("ali") is None


async def test_text_overrides_apply(engine: FakeFormEngine) -> None:
    spec = make_spec(
        texts=[
            {"key": "ask_field", "value": "{label}؟"},
            {"key": "invalid_answer", "value": "خطا در {label}: {error}"},
            {"key": "form_stopped", "value": "باشد، لغو شد."},
        ]
    )
    h = Harness(spec)
    r = await h.tap("ali", "menu:open:order_menu")
    assert text(r) == "فرم سفارش\nنام؟"
    await h.send("ali", "علی")
    r = await h.send("ali", "غول")
    assert text(r).startswith("خطا در اندازه: ")
    r = await h.tap("ali", "order:stop:")
    assert text(r) == "باشد، لغو شد."


async def test_spec_change_mid_form_is_keyed_by_field(h: Harness, engine: FakeFormEngine) -> None:
    await h.tap("ali", "menu:open:order_menu")
    await h.send("ali", "علی")
    await h.tap("ali", "order:ans:1")  # متوسط
    # the owner removes "متوسط" and the "urgent" field while the form is open
    fields = [dict(f) for f in FIELDS if f["key"] != "urgent"]
    fields[1]["choices"] = ["کوچک", "بزرگ"]
    h.spec = make_spec(fields)
    r = await h.send("ali", "09121234567")  # was asked "urgent", which is gone: re-ask next field
    assert "«تلفن»" in text(r)
    r = await h.send("ali", "09121234567")
    assert "«تعداد»" in text(r)
    r = await h.send("ali", "۳")
    assert "«اندازه»" in text(r)  # stored "متوسط" is no longer valid: asked again
    r = await h.tap("ali", "order:ans:1")
    assert text(r) == "ثبت شد"
    values, _ = engine.done[0]
    assert values == {"name": "علی", "size": "بزرگ", "phone": "09121234567", "count": 3}
