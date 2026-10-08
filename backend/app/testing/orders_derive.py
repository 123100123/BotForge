"""Derived scenarios for ``orders`` capabilities (W1-ORD), registered with ``register_templates``.

Ids are ``derived:<capability_key>:<template>``. Every template holds for ANY valid spec (a derived
test that fails must mean a real bug). Steps use the orders driver mapping (``orders_driver.py``):
``submit_request`` = add the item and check out, ``book`` = add to cart, ``expect_request`` = the
latest order's status. Emitted templates:

  checkout             add -> checkout -> order in ``initial_status``; the owner is notified
                       (``placed`` in notify_owner_on); when an owner action is allowed from the
                       initial status, the owner applies it, the order lands on its ``to_status``
                       and the customer is notified (``status_changed`` in notify_user_on)
  out_of_stock         (``stock_field``) one item in stock: the first customer orders it, a second
                       customer's add is rejected ``out_of_stock`` and has no order
  cancel_restocks      (initial status cancellable and a "cancelled" status declared) the customer
                       cancels; with ``stock_field`` the single unit in stock can be ordered again
  non_owner_rejected   a customer sending an owner action is rejected ``not_allowed`` and the
                       status is unchanged (when the initial status has an owner action)

A capability with no main entry in ``nav.virtual_menu``, or whose resource is missing, is
skipped. Restricted audiences and disabled capabilities are handled by
``derive.derive_scenarios`` (multi-customer templates such as ``out_of_stock`` are dropped there
when driven as the owner).
"""

from types import SimpleNamespace

from app.botspec.models import BotSpec, OrdersCapability, Resource
from app.testing.derive import BASE_START_HOURS, _form_values, _has_menu, _seed_record, register_templates
from app.testing.scenario import Scenario, SeedRecord, Step

OWNER_ID = "owner"
CUSTOMER = "ali"
OTHER = "sara"
ITEM_REF = "i1"
PRICE = "120000"
CANCELLED = "cancelled"


class _Orders:
    def __init__(self, spec: BotSpec, cap: OrdersCapability, resource: Resource) -> None:
        self.spec = spec
        self.cap = cap
        self.resource = resource
        self.form = _form_values(SimpleNamespace(form_fields=cap.checkout_fields))  # type: ignore[arg-type]
        self.out: list[Scenario] = []

    def seeds(self, stock: int) -> list[SeedRecord]:
        overrides = {self.cap.price_field: PRICE}
        if self.cap.stock_field is not None:
            overrides[self.cap.stock_field] = str(stock)
        return [_seed_record(self.resource, ITEM_REF, 1, BASE_START_HOURS, overrides)]

    # --- steps -------------------------------------------------------------------------------

    def order(self, actor: str = CUSTOMER, expect: str = "submitted") -> Step:
        return Step(
            do="submit_request",
            actor=actor,
            capability=self.cap.key,
            item=ITEM_REF,
            form=self.form,
            expect=expect,
        )

    def add_rejected(self, actor: str, reason: str) -> Step:
        return Step.model_validate(
            {
                "do": "book",
                "actor": actor,
                "capability": self.cap.key,
                "item": ITEM_REF,
                "expect": "rejected",
                "reason": reason,
            }
        )

    def act(self, key: str, expect: str = "ok", reason: str | None = None, actor: str = OWNER_ID) -> Step:
        return Step.model_validate(
            {
                "do": "owner_action",
                "actor": actor,
                "capability": self.cap.key,
                "action": key,
                "target_actor": CUSTOMER,
                "expect": expect,
                **({"reason": reason} if reason else {}),
            }
        )

    def status(self, status: str, actor: str = CUSTOMER) -> Step:
        return Step(do="expect_request", actor=actor, capability=self.cap.key, expect=status)

    def notified(self, actor: str, event: str) -> Step:
        return Step.model_validate({"do": "expect_notified", "actor": actor, "event": event})

    def add(self, name: str, title: str, steps: list[Step], stock: int = 5) -> None:
        self.out.append(
            Scenario(
                id=f"derived:{self.cap.key}:{name}",
                title=f"{self.cap.title}: {title}",
                source="derived",
                capability_keys=[self.cap.key],
                seed=self.seeds(stock),
                steps=steps,
            )
        )

    # --- scenarios ---------------------------------------------------------------------------

    def build(self) -> list[Scenario]:
        cap = self.cap
        first = next((a for a in cap.owner_actions if cap.initial_status in a.from_statuses), None)

        steps = [self.order(), self.status(cap.initial_status)]
        if "placed" in cap.notify_owner_on:
            steps.append(self.notified(OWNER_ID, "ordered"))
        if first is not None:
            steps += [self.act(first.key), self.status(first.to_status)]
            if "status_changed" in cap.notify_user_on and first.to_status != cap.initial_status:
                steps.append(self.notified(CUSTOMER, "order_status_changed"))
        self.add("checkout", "افزودن به سبد، ثبت سفارش و پیگیری وضعیت", steps)

        if cap.stock_field is not None:
            self.add(
                "out_of_stock",
                "پس از تمام شدن موجودی، افزودن کالا رد می‌شود",
                [self.order(), self.add_rejected(OTHER, "out_of_stock"), self.status("none", OTHER)],
                stock=1,
            )

        statuses = {s.key for s in cap.statuses}
        if CANCELLED in statuses and cap.initial_status in cap.cancellable_statuses:
            cancel = Step(do="cancel", actor=CUSTOMER, capability=cap.key, item=ITEM_REF, expect="cancelled")
            steps = [self.order(), cancel, self.status(CANCELLED)]
            if cap.stock_field is not None:  # the single unit is back in stock
                steps += [self.order(), self.status(cap.initial_status)]
            self.add("cancel_restocks", "لغو سفارش توسط مشتری و بازگشت موجودی", steps, stock=1)

        if first is not None:
            self.add(
                "non_owner_rejected",
                "اقدام مالک روی سفارش توسط مشتری رد می‌شود",
                [
                    self.order(),
                    self.act(first.key, "rejected", "not_allowed", actor=CUSTOMER),
                    self.status(cap.initial_status),
                ],
            )
        return self.out


def orders_templates(spec: BotSpec, cap: OrdersCapability) -> list[Scenario]:
    resource = spec.resource(cap.resource)
    if resource is None or not _has_menu(spec, cap.key, "main"):
        return []  # users cannot reach this capability; nothing a scenario could drive
    return _Orders(spec, cap, resource).build()


register_templates("orders", orders_templates)
