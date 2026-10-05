"""Scenario driver for ``orders`` capabilities (W1-ORD), registered as ``register_driver("orders", ...)``.

The scenario contract (``testing/scenario.py``) is frozen, so orders reuse the existing step kinds:

  book            actor, item          add one ``item`` to the actor's cart (start -> open main ->
                                       ``item:<id>`` -> ``add:<id>``). expect "confirmed" = added
                                       (the cart quantity grew); "rejected" matches the add's
                                       rejected Outcome (e.g. reason ``out_of_stock``)
  submit_request  actor [item, form]   checkout: with ``item``, first add it as ``book`` does (a
                                       refused add decides the step); then ``cart`` -> ``chk`` ->
                                       answer ``checkout_fields`` by key -> Outcome ``order``
                                       (expect "submitted" or "rejected")
  cancel          actor, item          cancel the actor's latest order containing ``item`` through
                                       "my orders" (``cancel:<order id>``); expect cancelled|rejected
  owner_action    action, target_actor an ``admin`` event ``own:<id>.<action>`` from the acting
                                       actor (default "owner") on target_actor's latest order
  expect_request  actor, expect        the actor's latest order has status key ``expect``
                                       ("none" when the actor has no order)

Buttons are found by parsed callback action and arg, never by label.
"""

from typing import ClassVar

from app.botspec.models import AnyCapability, FieldDef, OrdersCapability
from app.runtime.callbacks import (
    ACT_ADD,
    ACT_ANS,
    ACT_CANCEL,
    ACT_CART,
    ACT_CHK,
    ACT_MINE,
    ACT_OWN,
    ACT_SKIP,
    make_callback,
)
from app.runtime.contracts import RuntimeResponse
from app.runtime.store import Record
from app.testing.drivers import (
    RunContext,
    StepFailure,
    _check_outcome,
    _choice_index,
    _form_answer,
    _last_outcome,
    _missing_button,
    find_button,
    open_menu,
    reach_item,
    register_driver,
    snippet,
)
from app.testing.scenario import OWNER, Step

NONE_STATUS = "none"
ORDER = ("order",)


def _status_label(cap: OrdersCapability, key: str) -> str:
    return next((s.label for s in cap.statuses if s.key == key), key)


async def _latest(ctx: RunContext, cap: OrdersCapability, actor_id: str) -> Record | None:
    rows = await ctx.store.list_records(cap.key, actor_id=actor_id, order_by="-id", limit=1)
    return rows[0] if rows else None


async def _cart_qty(ctx: RunContext, cap: OrdersCapability, actor_id: str, item_id: int) -> int:
    rows = await ctx.store.list_records(f"{cap.key}.cart", actor_id=actor_id, order_by="-id", limit=1)
    items = rows[0].data.get("items") if rows else None
    return sum(
        e.get("qty", 0)
        for e in (items if isinstance(items, list) else [])
        if isinstance(e, dict) and e.get("item_id") == item_id and isinstance(e.get("qty"), int)
    )


class OrdersDriver:
    supported: ClassVar[frozenset[str]] = frozenset(
        {"book", "submit_request", "cancel", "owner_action", "expect_request"}
    )

    async def perform(self, ctx: RunContext, step: Step, cap: AnyCapability) -> str:
        if not isinstance(cap, OrdersCapability):  # pragma: no cover - registry guarantees the type
            raise StepFailure(f"«{cap.key}» یک قابلیت سفارش نیست.")
        if step.do == "book":
            return await self._book(ctx, step, cap)
        if step.do == "submit_request":
            return await self._checkout(ctx, step, cap)
        if step.do == "cancel":
            return await self._cancel(ctx, step, cap)
        if step.do == "owner_action":
            return await self._owner_action(ctx, step, cap)
        return await self._expect_order(ctx, step, cap)

    # --- add to cart -----------------------------------------------------------------------------

    async def _add(self, ctx: RunContext, step: Step, cap: OrdersCapability) -> tuple[RuntimeResponse, bool]:
        """Reach the item and press ``add``; return the response and whether the cart grew."""
        actor = step.actor or ""
        item_id = ctx.item_id(step)
        before = await _cart_qty(ctx, cap, actor, item_id)
        resp = await reach_item(ctx, actor, cap, item_id, ctx.item_title(step.item))
        button = find_button(resp, actor, cap.key, ACT_ADD, str(item_id))
        if button is None:
            raise _missing_button(f"افزودن به سبد ({cap.key}:{ACT_ADD}:{item_id})", resp, actor)
        resp = await ctx.press(actor, button)
        return resp, await _cart_qty(ctx, cap, actor, item_id) > before

    async def _book(self, ctx: RunContext, step: Step, cap: OrdersCapability) -> str:
        actor = step.actor or ""
        resp, grew = await self._add(ctx, step, cap)
        if _last_outcome(resp, cap.key, ORDER) is not None:
            return _check_outcome(step, resp, actor, cap.key, ORDER)
        phrase = "به سبد خرید افزوده شد"
        if step.expect == "rejected" or not grew:
            raise StepFailure(
                f"انتظار: {'رد شدن' if step.expect == 'rejected' else 'افزوده شدن به سبد'}؛ "
                f"نتیجهٔ واقعی: {phrase if grew else 'سبد تغییر نکرد'}. پاسخ ربات: «{snippet(resp, actor)}»",
                phrase if grew else "بدون تغییر",
            )
        return phrase

    # --- checkout --------------------------------------------------------------------------------

    async def _checkout(self, ctx: RunContext, step: Step, cap: OrdersCapability) -> str:
        actor = step.actor or ""
        field_keys = {f.key for f in cap.checkout_fields}
        unknown = [kv.key for kv in step.form if kv.key not in field_keys]
        if unknown:
            known = "، ".join(sorted(field_keys)) or "هیچ"
            names = "، ".join(f"«{k}»" for k in unknown)
            raise StepFailure(
                f"کلید فرم {names} جزو فیلدهای سفارش «{cap.key}» نیست (فیلدهای موجود: {known})."
            )
        if step.item is not None:
            resp, _ = await self._add(ctx, step, cap)
            if _last_outcome(resp, cap.key, ORDER) is not None:  # the add itself was refused
                return _check_outcome(step, resp, actor, cap.key, ORDER)
        else:
            await open_menu(ctx, actor, cap, "main")
        resp = await ctx.send(actor, "callback", data=make_callback(cap.key, ACT_CART))
        button = find_button(resp, actor, cap.key, ACT_CHK)
        if button is None:  # an empty cart has no checkout button; press it directly to get the refusal
            resp = await ctx.send(actor, "callback", data=make_callback(cap.key, ACT_CHK))
        else:
            resp = await ctx.press(actor, button)
        resp = await self._fill_form(ctx, step, cap, resp)
        return _check_outcome(step, resp, actor, cap.key, ORDER)

    async def _fill_form(
        self, ctx: RunContext, step: Step, cap: OrdersCapability, resp: RuntimeResponse
    ) -> RuntimeResponse:
        actor = step.actor or ""
        asked: dict[str, int] = {}
        for _ in range(len(cap.checkout_fields) * 2 + 4):
            if _last_outcome(resp, cap.key, ORDER) is not None:
                return resp
            session = await ctx.store.get_session(actor)
            if not session:
                return resp
            key = (session.get("vars") or {}).get("field")
            field = next((f for f in cap.checkout_fields if f.key == key), None)
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
        cap: OrdersCapability,
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

    # --- cancel ----------------------------------------------------------------------------------

    async def _cancel(self, ctx: RunContext, step: Step, cap: OrdersCapability) -> str:
        actor = step.actor or ""
        item_id = ctx.item_id(step)
        orders = await ctx.store.list_records(cap.key, actor_id=actor, order_by="-id")
        order = next(
            (
                o
                for o in orders
                if any(isinstance(e, dict) and e.get("item_id") == item_id for e in o.data.get("items") or [])
            ),
            None,
        )
        if order is None:
            raise StepFailure(
                f"{ctx.name(actor)} سفارشی شامل «{ctx.item_title(step.item)}» ندارد که لغو شود."
            )
        if any(m.capability == cap.key and m.view == "mine" for m in ctx.spec.menu):
            resp = await open_menu(ctx, actor, cap, "mine")
        else:
            await ctx.send(actor, "start")
            resp = await ctx.send(actor, "callback", data=make_callback(cap.key, ACT_MINE))
        button = find_button(resp, actor, cap.key, ACT_CANCEL, str(order.id))
        if button is None:  # not cancellable: no button; a stale button press must still be refused
            resp = await ctx.send(actor, "callback", data=make_callback(cap.key, ACT_CANCEL, str(order.id)))
        else:
            resp = await ctx.press(actor, button)
        return _check_outcome(step, resp, actor, cap.key, ("cancel",))

    # --- owner_action ----------------------------------------------------------------------------

    async def _owner_action(self, ctx: RunContext, step: Step, cap: OrdersCapability) -> str:
        actor = step.actor or OWNER
        target = step.target_actor or ""
        order = await _latest(ctx, cap, target)
        if order is None:
            raise StepFailure(f"{ctx.name(target)} سفارشی در «{cap.title}» ندارد که مدیر روی آن اقدام کند.")
        data = make_callback(cap.key, ACT_OWN, f"{order.id}.{step.action}")
        resp = await ctx.send(actor, "admin", data=data)
        return _check_outcome(step, resp, actor, cap.key, ("owner_action",), ("ok",))

    # --- expect_request --------------------------------------------------------------------------

    async def _expect_order(self, ctx: RunContext, step: Step, cap: OrdersCapability) -> str:
        actor = step.actor or ""
        order = await _latest(ctx, cap, actor)
        actual = (order.status or NONE_STATUS) if order is not None else NONE_STATUS
        phrase = "بدون سفارش" if order is None else _status_label(cap, actual)
        expected = step.expect or ""
        if actual != expected:
            wanted = f"«{_status_label(cap, expected)}» ({expected})"
            raise StepFailure(
                f"انتظار: وضعیت سفارش {ctx.name(actor)} {wanted} باشد؛ نتیجهٔ واقعی: «{phrase}» ({actual})",
                phrase,
            )
        return phrase


register_driver("orders", OrdersDriver())
