"""Derived scenarios for ``request`` capabilities (WP8), registered with ``register_templates``.

Ids are ``derived:<capability_key>:<template>``. Every template holds for ANY valid spec (a derived
test that fails must mean a real bug). Emitted templates:

  submit_and_track          submit -> latest request has the initial status -> "mine" shows it
  owner_notified            (``submitted`` in notify_owner_on) the owner receives a ``submitted`` notice
  action_<key>              each owner action, applied from an allowed status, lands on ``to_status``.
                            Statuses are reached through other owner actions (shortest path from the
                            initial status); an action no status path can reach is skipped
                            (``unreachable_actions`` lists them)
  action_not_allowed        an action attempted from a status it is not defined for is rejected
                            ``not_allowed`` and the status is unchanged (when such a pair is reachable)
  non_owner_rejected        a customer sending an owner action is rejected ``not_allowed``
                            (when the initial status has an action)
  status_changed_notified   (``status_changed`` in notify_user_on) the customer is notified of the
                            first reachable owner action
  item_tied                 (``item_resource``) the request is tied to the picked (second) item

A capability with no main menu item is skipped: users cannot reach it. "mine" is checked only when
the menu has a ``mine`` item for the capability.
"""

from collections import deque

from app.botspec.models import BotSpec, RequestCapability
from app.testing.derive import (
    BASE_START_HOURS,
    _form_values,
    _has_menu,
    _rendered_title,
    _seed_record,
    register_templates,
)
from app.testing.scenario import Scenario, SeedRecord, Step

OWNER_ID = "owner"
CUSTOMER = "ali"
ITEM_REF = "i1"
OTHER_ITEM_REF = "i2"

Path = list[str]  # owner action keys, in order


def _paths(cap: RequestCapability) -> dict[str, Path]:
    """Shortest owner-action path from the initial status to every reachable status."""
    paths: dict[str, Path] = {cap.initial_status: []}
    queue = deque([cap.initial_status])
    while queue:
        status = queue.popleft()
        for act in cap.owner_actions:
            if status in act.from_statuses and act.to_status not in paths:
                paths[act.to_status] = [*paths[status], act.key]
                queue.append(act.to_status)
    return paths


def _path_for_action(cap: RequestCapability, paths: dict[str, Path], key: str) -> Path | None:
    """Shortest path to a status the action is defined for, or None when none is reachable."""
    act = next(a for a in cap.owner_actions if a.key == key)
    options = [paths[s] for s in act.from_statuses if s in paths]
    return min(options, key=len) if options else None


def unreachable_actions(cap: RequestCapability) -> list[str]:
    """Owner action keys that no sequence of owner actions from the initial status can trigger."""
    paths = _paths(cap)
    return [a.key for a in cap.owner_actions if _path_for_action(cap, paths, a.key) is None]


class _Request:
    def __init__(self, spec: BotSpec, cap: RequestCapability) -> None:
        self.spec = spec
        self.cap = cap
        self.form = _form_values(cap)  # type: ignore[arg-type]  # only form_fields is used
        self.paths = _paths(cap)
        self.seeds: list[SeedRecord] = []
        self.titles: dict[str, str] = {}
        resource = spec.resource(cap.item_resource) if cap.item_resource else None
        if resource is not None:
            for n, ref in enumerate((ITEM_REF, OTHER_ITEM_REF), 1):
                seed = _seed_record(resource, ref, n, BASE_START_HOURS)
                self.seeds.append(seed)
                self.titles[ref] = _rendered_title(spec, resource, seed)
        self.out: list[Scenario] = []

    def label(self, status: str) -> str:
        return next((s.label for s in self.cap.statuses if s.key == status), status)

    # --- steps -------------------------------------------------------------------------------

    def submit(self, item: str = ITEM_REF, expect: str = "submitted") -> Step:
        return Step(
            do="submit_request",
            actor=CUSTOMER,
            capability=self.cap.key,
            item=item if self.cap.item_resource else None,
            form=self.form,
            expect=expect,
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

    def expect_status(self, status: str) -> Step:
        return Step(do="expect_request", actor=CUSTOMER, capability=self.cap.key, expect=status)

    def notified(self, actor: str, event: str) -> Step:
        return Step.model_validate({"do": "expect_notified", "actor": actor, "event": event})

    def reach(self, path: Path) -> list[Step]:
        return [self.act(key) for key in path]

    # --- scenarios ---------------------------------------------------------------------------

    def add(self, name: str, title: str, steps: list[Step]) -> None:
        self.out.append(
            Scenario(
                id=f"derived:{self.cap.key}:{name}",
                title=f"{self.cap.title}: {title}",
                source="derived",
                capability_keys=[self.cap.key],
                seed=self.seeds,
                steps=steps,
            )
        )

    def mine_step(self, contains: str) -> Step:
        return Step(do="open", actor=CUSTOMER, capability=self.cap.key, view="mine", contains=contains)

    def build(self) -> list[Scenario]:
        cap = self.cap
        initial_label = self.label(cap.initial_status)
        steps = [self.submit(), self.expect_status(cap.initial_status)]
        if _has_menu(self.spec, cap.key, "mine"):
            steps.append(self.mine_step(initial_label))
        self.add("submit_and_track", "ثبت درخواست و پیگیری آن با وضعیت اولیه", steps)

        if "submitted" in cap.notify_owner_on:
            self.add(
                "owner_notified",
                "مالک از ثبت درخواست مطلع می‌شود",
                [self.submit(), self.notified(OWNER_ID, "submitted")],
            )

        first_usable: tuple[str, Path] | None = None
        for action in cap.owner_actions:
            path = _path_for_action(cap, self.paths, action.key)
            if path is None:
                continue
            first_usable = first_usable or (action.key, path)
            self.add(
                f"action_{action.key}",
                f"اقدام «{action.label}» وضعیت را به «{self.label(action.to_status)}» می‌برد",
                [
                    self.submit(),
                    *self.reach(path),
                    self.act(action.key),
                    self.expect_status(action.to_status),
                ],
            )

        self.disallowed()
        self.non_owner()

        if "status_changed" in cap.notify_user_on and first_usable is not None:
            key, path = first_usable
            self.add(
                "status_changed_notified",
                "مشتری از تغییر وضعیت مطلع می‌شود",
                [self.submit(), *self.reach(path), self.act(key), self.notified(CUSTOMER, "status_changed")],
            )

        if cap.item_resource and OTHER_ITEM_REF in self.titles:
            steps = [self.submit(OTHER_ITEM_REF)]
            if _has_menu(self.spec, cap.key, "mine"):
                steps.append(self.mine_step(self.titles[OTHER_ITEM_REF]))
            self.add("item_tied", "درخواست به مورد انتخاب‌شده وابسته است", steps)
        return self.out

    def disallowed(self) -> None:
        """Shortest (path, action) such that the status reached is not among the action's from_statuses."""
        best: tuple[Path, str, str] | None = None
        for status, path in self.paths.items():
            for act in self.cap.owner_actions:
                if status in act.from_statuses:
                    continue
                if best is None or len(path) < len(best[0]):
                    best = (path, act.key, status)
        if best is None:
            return
        path, key, status = best
        action_label = next(a.label for a in self.cap.owner_actions if a.key == key)
        self.add(
            "action_not_allowed",
            f"اقدام «{action_label}» از وضعیت «{self.label(status)}» رد می‌شود",
            [
                self.submit(),
                *self.reach(path),
                self.act(key, "rejected", "not_allowed"),
                self.expect_status(status),
            ],
        )

    def non_owner(self) -> None:
        allowed = [a for a in self.cap.owner_actions if self.cap.initial_status in a.from_statuses]
        if not allowed:
            return
        self.add(
            "non_owner_rejected",
            "اقدام مالک توسط کاربر عادی رد می‌شود",
            [
                self.submit(),
                self.act(allowed[0].key, "rejected", "not_allowed", actor=CUSTOMER),
                self.expect_status(self.cap.initial_status),
            ],
        )


def request_templates(spec: BotSpec, cap: RequestCapability) -> list[Scenario]:
    if not _has_menu(spec, cap.key, "main"):
        return []  # users cannot reach this capability; nothing a scenario could drive
    if cap.item_resource is not None and spec.resource(cap.item_resource) is None:
        return []
    return _Request(spec, cap).build()


register_templates("request", request_templates)
