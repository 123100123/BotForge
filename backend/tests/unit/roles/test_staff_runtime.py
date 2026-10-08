"""Roles in the runtime (MemoryStore): owner actions by staff, the request staff queue, the staff persona.

Live events get their role from ``bot_users`` in ``dispatch`` (tested against Postgres in
``tests/integration/test_team_api.py``); here the actor carries it, as sandbox events do.
"""

import typing

from app.botspec.models import BotSpec
from app.runtime import formatting
from app.runtime.contracts import Actor, RuntimeResponse
from app.runtime.engines import request as engine
from app.runtime.texts import common
from app.runtime.texts import request as tx
from app.simulator.service import Persona, persona_actor
from tests.unit.runtime.harness import Harness, button_data, buttons, load_example, text
from tests.unit.runtime.test_gating import is_stale, menu_data, with_cap
from tests.unit.runtime.test_request import ANSWERS, CAP, MENU_MAIN, repair_spec

ALI = "ali"
STAFF = Actor(id="sam", display_name="سام", role="staff")
MANAGER = Actor(id="mina", display_name="مینا", role="manager")
REQUEST = {"device": "یخچال", "problem": "صدا می‌دهد", "phone": "09123456789", "address": "تهران"}
TITLE = "درخواست تعمیر"


def fa(n: int) -> str:
    return formatting.to_persian_digits(n)


async def seed(h: Harness, status: str, actor: str = ALI, **data: object) -> int:
    return await h.seed(CAP, {**REQUEST, **data}, status=status, actor_id=actor)


async def status_of(h: Harness, rid: int) -> str | None:
    record = await h.store.get_record(CAP, rid)
    assert record is not None
    return record.status


def outcome(resp: RuntimeResponse) -> tuple[str, str, str, str | None]:
    assert len(resp.outcomes) == 1, resp.outcomes
    o = resp.outcomes[0]
    return (o.capability, o.action, o.result, o.reason)


def recipients(resp: RuntimeResponse) -> list[str]:
    return [m.to_actor_id for m in resp.messages]


# --- owner actions ------------------------------------------------------------------------------


async def test_staff_run_owner_actions_and_customers_are_refused() -> None:
    h = Harness(repair_spec())
    rid = await seed(h, "new")

    refused = await h.tap("sara", f"{CAP}:own:{rid}.approve")
    assert outcome(refused) == (CAP, "owner_action", "rejected", "not_allowed")
    assert text(refused) == common.NOT_ALLOWED and await status_of(h, rid) == "new"

    done = await h.tap(STAFF, f"{CAP}:own:{rid}.approve")
    assert outcome(done) == (CAP, "owner_action", "ok", None)
    assert await status_of(h, rid) == "approved"
    # the customer hears about it; the owner gets nothing (owner alerts are for new requests only)
    assert recipients(done) == ["sam", ALI]
    assert done.messages[1].notice == "status_changed"
    assert button_data(done, 0) == [f"{CAP}:own:{rid}.mark_done"]  # the same reply the owner gets

    assert outcome(await h.tap(MANAGER, f"{CAP}:own:{rid}.mark_done")) == (CAP, "owner_action", "ok", None)
    assert await status_of(h, rid) == "done"


async def test_admin_events_follow_the_same_rule() -> None:
    h = Harness(repair_spec())
    rid = await seed(h, "new")
    refused = await h.admin(f"{CAP}:own:{rid}.approve", actor=ALI)
    assert outcome(refused) == (CAP, "owner_action", "rejected", "not_allowed")
    assert text(refused) == common.NOT_ALLOWED and await status_of(h, rid) == "new"
    assert outcome(await h.admin(f"{CAP}:own:{rid}.approve", actor=STAFF))[2] == "ok"
    assert await status_of(h, rid) == "approved"
    # staff pass the role check, so an unknown capability is reported as such
    unknown = await h.admin("nope:own:1.approve", actor=STAFF)
    assert outcome(unknown) == ("nope", "owner_action", "rejected", "not_found")


async def test_on_internal_workflows_staff_submit_and_only_managers_decide() -> None:
    h = Harness(repair_spec(audience="staff"))  # e.g. leave requests: staff are the submitters
    r = await h.tap(STAFF, MENU_MAIN)
    assert text(r) == f"📝 {TITLE}\n{tx.MAIN_INTRO}"  # no queue: staff cannot decide here
    await h.tap(STAFF, f"{CAP}:new:")
    for answer in ANSWERS:
        r = await h.send(STAFF, answer)
    assert outcome(r)[1:3] == ("submit", "submitted")
    rid = r.outcomes[0].record_id
    assert rid is not None

    approve = f"{CAP}:own:{rid}.approve"
    for attempt in (await h.tap(STAFF, approve), await h.admin(approve, STAFF)):
        assert outcome(attempt) == (CAP, "owner_action", "rejected", "not_allowed")
    assert await status_of(h, rid) == "new"
    queue = await h.tap(MANAGER, MENU_MAIN)
    assert f"{CAP}:own:{rid}.approve" in button_data(queue)
    assert outcome(await h.tap(MANAGER, f"{CAP}:own:{rid}.approve"))[2] == "ok"
    assert outcome(await h.tap("owner", f"{CAP}:own:{rid}.mark_done"))[2] == "ok"


# --- the staff queue ----------------------------------------------------------------------------


async def test_the_queue_lists_pending_requests_newest_first_with_their_actions() -> None:
    h = Harness(repair_spec())
    r1 = await seed(h, "new", device="اول")
    r2 = await seed(h, "approved", actor="sara", device="دوم")
    r3 = await seed(h, "done", actor="reza", device="سوم")  # no owner action starts from done
    r4 = await seed(h, "rejected", device="چهارم")
    r5 = await seed(h, "new", actor="sara", device="پنجم")

    q = await h.tap(STAFF, MENU_MAIN)
    assert recipients(q) == ["sam"]
    body = text(q)
    assert body.startswith(engine._fill(engine.QUEUE_HEADER, title=TITLE))
    positions = [body.index(f"کد {fa(r)} ") for r in (r5, r2, r1)]
    assert positions == sorted(positions)  # newest first
    for gone in (r3, r4):
        assert f"کد {fa(gone)} " not in body
    assert "اول" in body and "پنجم" in body and "سوم" not in body and "09123456789" in body
    assert button_data(q) == [
        f"{CAP}:own:{r5}.approve",
        f"{CAP}:own:{r5}.reject",
        f"{CAP}:own:{r2}.mark_done",
        f"{CAP}:own:{r1}.approve",
        f"{CAP}:own:{r1}.reject",
        f"{CAP}:new:",
        f"{CAP}:mine:",
        "nav:go:home",
    ]
    labels = [b.label for b in buttons(q)]
    assert labels[0] == f"تأیید (کد {fa(r5)})" and labels[2] == f"انجام شد (کد {fa(r2)})"

    # a queue button works for staff
    assert outcome(await h.tap(STAFF, f"{CAP}:own:{r1}.reject"))[2] == "ok"
    assert f"{CAP}:own:{r1}.approve" not in button_data(await h.tap(STAFF, MENU_MAIN))

    # the owner is a manager and sees the queue too; customers keep the plain entry view
    assert button_data(await h.tap("owner", MENU_MAIN))[0] == f"{CAP}:own:{r5}.approve"
    customer = await h.tap(ALI, MENU_MAIN)
    assert text(customer) == f"📝 {TITLE}\n{tx.MAIN_INTRO}"
    assert button_data(customer) == [f"{CAP}:new:", f"{CAP}:mine:", "nav:go:home"]


async def test_the_queue_is_capped_and_says_how_many_more_wait() -> None:
    h = Harness(repair_spec())
    ids = [await seed(h, "new") for _ in range(engine.QUEUE_LIMIT + 2)]
    body = text(await h.tap(STAFF, MENU_MAIN))
    shown = [rid for rid in ids if f"کد {fa(rid)} " in body]
    assert shown == ids[-engine.QUEUE_LIMIT :]
    assert body.endswith(engine._fill(engine.QUEUE_MORE, count=fa(2)))


async def test_staff_home_adds_the_request_queue() -> None:
    """Staff get the customer home plus «📋 صف درخواست‌ها» (``staff.q``), which opens the queue;
    customers never see it and pressing it is stale for them."""
    h = Harness(repair_spec())
    rid = await seed(h, "new")
    staff_home = button_data(await h.start(STAFF))
    assert staff_home[-1] == "nav:go:staff.q"
    assert "nav:go:staff.q" not in button_data(await h.start(ALI))
    q = await h.tap(STAFF, "nav:go:staff.q")
    assert f"{CAP}:own:{rid}.approve" in button_data(q)
    stale = await h.tap(ALI, "nav:go:staff.q")
    assert stale.messages[0].edit is False and f"{CAP}:own:{rid}.approve" not in button_data(stale)


async def test_an_empty_queue_still_offers_the_entries() -> None:
    h = Harness(repair_spec())
    await seed(h, "done")
    q = await h.tap(STAFF, MENU_MAIN)
    assert text(q) == engine._fill(engine.QUEUE_EMPTY, title=TITLE)
    assert button_data(q) == [f"{CAP}:new:", f"{CAP}:mine:", "nav:go:home"]


async def test_queue_values_are_one_line_and_cut_short() -> None:
    h = Harness(repair_spec())
    long_problem = "خط اول\nخط دوم " + "ب" * 200
    await seed(h, "new", problem=long_problem)
    body = text(await h.tap(STAFF, MENU_MAIN))
    line = next(x for x in body.split("\n") if x.strip().startswith("شرح مشکل"))
    assert "خط اول خط دوم" in line and line.endswith("…")
    assert len(line) <= len(engine.QUEUE_DETAIL_LINE) + len("شرح مشکل") + engine.QUEUE_VALUE_CHARS


async def test_queue_entries_name_the_picked_item() -> None:
    h = Harness(repair_spec(item_resource=True))
    item = await h.seed("appliance", {"name": "یخچال ساید"})
    await seed(h, "new")
    await h.store.create_record(CAP, REQUEST, status="new", actor_id=ALI, item_id=item, now=h.now)
    await h.store.create_record(CAP, REQUEST, status="new", actor_id=ALI, item_id=item + 100, now=h.now)
    body = text(await h.tap(STAFF, MENU_MAIN))
    assert "یخچال ساید" in body and f"#{fa(item + 100)}" in body  # a deleted item falls back to its id


# --- the staff persona --------------------------------------------------------------------------


def test_the_simulator_offers_a_staff_persona() -> None:
    assert "staff" in typing.get_args(Persona)
    staff = persona_actor("staff")
    assert (staff.id, staff.role, staff.is_owner, staff.effective_role) == ("staff", "staff", False, "staff")
    assert staff.display_name == "همکار"
    assert persona_actor("ali").effective_role == "customer"
    assert persona_actor("owner").effective_role == "manager"


async def test_staff_only_capabilities_are_visible_to_the_staff_persona() -> None:
    spec: BotSpec = with_cap(load_example("workshop.botspec.json"), "info", audience="staff")
    h = Harness(spec)
    staff, ali = persona_actor("staff"), persona_actor("ali")
    assert "nav:go:info" in menu_data(await h.start(staff))
    assert "nav:go:info" not in menu_data(await h.start(ali))
    assert not is_stale(await h.tap(staff, "info:show:about"))
    assert is_stale(await h.tap(ali, "info:show:about"))
