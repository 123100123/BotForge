"""Scenario driver for ``request`` capabilities (WP8), registered as ``register_driver("request", ...)``.

Steps: ``submit_request`` (start -> open main -> ``new`` -> ``pick`` when the capability has an
``item_resource`` -> answer the form -> Outcome), ``owner_action`` (an ``admin`` event from the
acting actor, default "owner", on the target actor's latest request) and ``expect_request`` (the
actor's latest request has the given status key). Buttons are found by parsed callback action and
arg, never by label.
"""

from typing import ClassVar

from app.botspec.models import AnyCapability, FieldDef, RequestCapability
from app.runtime.callbacks import ACT_ANS, ACT_NEW, ACT_OWN, ACT_PICK, ACT_SKIP, make_callback
from app.runtime.contracts import RuntimeResponse
from app.runtime.store import Record
from app.testing.drivers import (
    MAX_PAGES,
    RunContext,
    StepFailure,
    _check_outcome,
    _choice_index,
    _form_answer,
    _last_outcome,
    _missing_button,
    find_button,
    open_menu,
    register_driver,
    snippet,
)
from app.testing.scenario import OWNER, Step

NONE_STATUS = "none"


def _status_label(cap: RequestCapability, key: str) -> str:
    return next((s.label for s in cap.statuses if s.key == key), key)


async def _latest(
    ctx: RunContext, cap: RequestCapability, actor_id: str, item_id: int | None = None
) -> Record | None:
    rows = await ctx.store.list_records(cap.key, actor_id=actor_id, item_id=item_id, order_by="-id", limit=1)
    return rows[0] if rows else None


class RequestDriver:
    supported: ClassVar[frozenset[str]] = frozenset({"submit_request", "owner_action", "expect_request"})

    async def perform(self, ctx: RunContext, step: Step, cap: AnyCapability) -> str:
        if not isinstance(cap, RequestCapability):  # pragma: no cover - registry guarantees the type
            raise StepFailure(f"«{cap.key}» یک قابلیت درخواست نیست.")
        if step.do == "submit_request":
            return await self._submit(ctx, step, cap)
        if step.do == "owner_action":
            return await self._owner_action(ctx, step, cap)
        return await self._expect_request(ctx, step, cap)

    # --- submit_request --------------------------------------------------------------------------

    async def _submit(self, ctx: RunContext, step: Step, cap: RequestCapability) -> str:
        actor = step.actor or ""
        field_keys = {f.key for f in cap.form_fields}
        unknown = [kv.key for kv in step.form if kv.key not in field_keys]
        if unknown:
            known = "، ".join(sorted(field_keys)) or "هیچ"
            names = "، ".join(f"«{k}»" for k in unknown)
            raise StepFailure(f"کلید فرم {names} جزو فیلدهای فرم «{cap.key}» نیست (فیلدهای موجود: {known}).")
        if cap.item_resource is None and step.item is not None:
            raise StepFailure(
                f"قابلیت «{cap.key}» انتخاب مورد ندارد (item_resource تنظیم نشده) ولی گام item دارد."
            )
        item_id = ctx.item_id(step) if cap.item_resource is not None else None

        resp = await open_menu(ctx, actor, cap, "main")
        button = find_button(resp, actor, cap.key, ACT_NEW)
        if button is None:
            raise _missing_button(f"درخواست جدید ({cap.key}:{ACT_NEW})", resp, actor)
        resp = await ctx.press(actor, button)
        if item_id is not None:
            resp = await self._pick(ctx, actor, cap, item_id, ctx.item_title(step.item), resp)
        resp = await self._fill_form(ctx, step, cap, resp)
        return _check_outcome(step, resp, actor, cap.key, ("submit",))

    @staticmethod
    async def _pick(
        ctx: RunContext, actor: str, cap: RequestCapability, item_id: int, title: str, resp: RuntimeResponse
    ) -> RuntimeResponse:
        """Page through the item list (``new:<page>``) until ``pick:<id>`` shows, then press it."""
        for page in range(MAX_PAGES):
            button = find_button(resp, actor, cap.key, ACT_PICK, str(item_id))
            if button is not None:
                return await ctx.press(actor, button)
            nxt = find_button(resp, actor, cap.key, ACT_NEW, str(page + 1))
            if nxt is None:
                break
            resp = await ctx.press(actor, nxt)
        raise _missing_button(f"انتخاب مورد «{title}» ({cap.key}:{ACT_PICK}:{item_id})", resp, actor)

    async def _fill_form(
        self, ctx: RunContext, step: Step, cap: RequestCapability, resp: RuntimeResponse
    ) -> RuntimeResponse:
        """Answer the form questions the bot asks, by field key, until the request is decided."""
        actor = step.actor or ""
        asked: dict[str, int] = {}
        for _ in range(len(cap.form_fields) * 2 + 4):
            if _last_outcome(resp, cap.key, ("submit",)) is not None:
                return resp
            session = await ctx.store.get_session(actor)
            if not session:
                return resp
            key = (session.get("vars") or {}).get("field")
            field = next((f for f in cap.form_fields if f.key == key), None)
            if field is None:
                return resp
            asked[field.key] = asked.get(field.key, 0) + 1
            if asked[field.key] > 1:
                raise StepFailure(
                    f"پاسخ فیلد «{field.label}» ({field.key}) از سوی ربات پذیرفته نشد. "
                    f"پیام ربات: «{snippet(resp, actor)}»"
                )
            resp = await self._answer(ctx, actor, cap, field, _form_answer(step, field), resp)
        return resp

    @staticmethod
    async def _answer(
        ctx: RunContext,
        actor: str,
        cap: RequestCapability,
        field: FieldDef,
        raw: str | None,
        resp: RuntimeResponse,
    ) -> RuntimeResponse:
        if raw is None:
            if field.required:
                raise StepFailure(
                    f"فیلد الزامی «{field.label}» ({field.key}) در form این گام مقدار ندارد "
                    "ولی ربات آن را می‌پرسد."
                )
            skip = find_button(resp, actor, cap.key, ACT_SKIP)
            if skip is None:
                raise _missing_button(f"«رد کردن» ({cap.key}:{ACT_SKIP}) برای «{field.label}»", resp, actor)
            return await ctx.press(actor, skip)
        index = _choice_index(field, raw)
        if index is not None:
            button = find_button(resp, actor, cap.key, ACT_ANS, str(index))
            if button is None:
                raise _missing_button(f"گزینهٔ «{raw}» ({cap.key}:{ACT_ANS}:{index})", resp, actor)
            return await ctx.press(actor, button)
        return await ctx.send(actor, "text", text=raw)

    # --- owner_action ----------------------------------------------------------------------------

    async def _owner_action(self, ctx: RunContext, step: Step, cap: RequestCapability) -> str:
        actor = step.actor or OWNER
        target = step.target_actor or ""
        item_id = ctx.item_id(step) if step.item is not None else None
        request = await _latest(ctx, cap, target, item_id)
        if request is None:
            raise StepFailure(f"{ctx.name(target)} درخواستی در «{cap.title}» ندارد که مدیر روی آن اقدام کند.")
        data = make_callback(cap.key, ACT_OWN, f"{request.id}.{step.action}")
        resp = await ctx.send(actor, "admin", data=data)
        return _check_outcome(step, resp, actor, cap.key, ("owner_action",), ("ok",))

    # --- expect_request --------------------------------------------------------------------------

    async def _expect_request(self, ctx: RunContext, step: Step, cap: RequestCapability) -> str:
        actor = step.actor or ""
        request = await _latest(ctx, cap, actor)
        actual = (request.status or NONE_STATUS) if request is not None else NONE_STATUS
        phrase = "بدون درخواست" if request is None else _status_label(cap, actual)
        expected = step.expect or ""
        if actual != expected:
            wanted = f"«{_status_label(cap, expected)}» ({expected})"
            raise StepFailure(
                f"انتظار: وضعیت درخواست {ctx.name(actor)} {wanted} باشد؛ نتیجهٔ واقعی: «{phrase}» ({actual})",
                phrase,
            )
        return phrase


register_driver("request", RequestDriver())
