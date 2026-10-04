"""Event-level tests for the request engine (WP8): submission, tracking, owner actions, notices.

All interaction goes through ``BotRuntime.handle`` (via ``Harness``); buttons are located by
parsed callback action and arg, as the scenario drivers do.
"""

import json
from typing import Any

import pytest

from app.botspec.models import BotSpec
from app.botspec.validate import validate_spec
from app.runtime.callbacks import parse_callback
from app.runtime.contracts import Button, Outcome, OutMessage, RuntimeResponse
from app.runtime.engines import get_engine
from app.runtime.engines.request import ENGINE
from app.runtime.texts import request as tx
from tests.unit.runtime.harness import EXAMPLES, Harness, button_data, text

CAP = "repair"
MENU_MAIN = "menu:open:new_request"
MENU_MINE = "menu:open:my_requests"
ANSWERS = ["یخچال", "صدا می‌دهد", "09123456789", "تهران، خیابان آزادی"]


def repair_data() -> dict[str, Any]:
    return json.loads((EXAMPLES / "repair.botspec.json").read_text(encoding="utf-8"))


def repair_spec(*, item_resource: bool = False, **cap: Any) -> BotSpec:
    data = repair_data()
    if item_resource:
        data["resources"].append(
            {
                "key": "appliance",
                "label": "دستگاه",
                "label_plural": "دستگاه‌ها",
                "title_field": "name",
                "fields": [{"key": "name", "label": "نام", "type": "text"}],
            }
        )
        cap["item_resource"] = "appliance"
    request = next(c for c in data["capabilities"] if c["key"] == CAP)
    request.update(cap)
    spec = BotSpec.model_validate(data)
    errors = [i for i in validate_spec(spec) if i.severity == "error"]
    assert not errors, errors
    return spec


def find(resp: RuntimeResponse, action: str, arg: str | int | None = None, msg: int = -1) -> Button:
    for row in resp.messages[msg].buttons:
        for b in row:
            _, act, a = parse_callback(b.data)
            if act == action and (arg is None or a == str(arg)):
                return b
    raise AssertionError(f"no {action}:{arg} button; have {button_data(resp, msg)}")


def actions(resp: RuntimeResponse, msg: int = -1) -> list[tuple[str, str]]:
    return [parse_callback(d)[1:] for d in button_data(resp, msg)]  # type: ignore[misc]


def to(resp: RuntimeResponse, actor: str) -> list[OutMessage]:
    return [m for m in resp.messages if m.to_actor_id == actor]


def notice_to(resp: RuntimeResponse, actor: str, kind: str) -> OutMessage:
    found = [m for m in resp.messages if m.to_actor_id == actor and m.notice == kind]
    assert len(found) == 1, [(m.to_actor_id, m.notice) for m in resp.messages]
    return found[0]


def only_outcome(resp: RuntimeResponse) -> Outcome:
    assert len(resp.outcomes) == 1, resp.outcomes
    return resp.outcomes[0]


async def fill(h: Harness, actor: str, answers: list[str] | None = None) -> RuntimeResponse:
    r = h.last
    assert r is not None
    for answer in answers or ANSWERS:
        r = await h.send(actor, answer)
    return r


async def submit(h: Harness, actor: str = "ali") -> RuntimeResponse:
    """menu -> new -> form answers (no item_resource)."""
    r = await h.tap(actor, MENU_MAIN)
    await h.tap(actor, find(r, "new").data)
    return await fill(h, actor)


async def submit_item(h: Harness, item_id: int, actor: str = "ali") -> RuntimeResponse:
    r = await h.tap(actor, MENU_MAIN)
    r = await h.tap(actor, find(r, "new").data)
    await h.tap(actor, find(r, "pick", item_id).data)
    return await fill(h, actor)


@pytest.fixture
def h() -> Harness:
    return Harness(repair_spec())


# --- registry and texts --------------------------------------------------------------------------


def test_engine_is_registered() -> None:
    assert get_engine("request") is ENGINE
    assert ENGINE.type == "request"


# --- open main ---------------------------------------------------------------------------------


async def test_open_main_offers_new_and_mine(h: Harness) -> None:
    r = await h.tap("ali", MENU_MAIN)
    assert [m.to_actor_id for m in r.messages] == ["ali"]
    assert actions(r) == [("new", ""), ("mine", ""), ("home", "")]
    assert "درخواست تعمیر" in text(r)
    assert r.outcomes == []


# --- submit without item_resource ----------------------------------------------------------------


async def test_new_starts_the_form_and_asks_in_order(h: Harness) -> None:
    r = await h.tap("ali", MENU_MAIN)
    r = await h.tap("ali", find(r, "new").data)
    assert "نوع دستگاه" in text(r)
    assert text(r).startswith(tx.TEXTS["form_intro"].split("\n")[0].replace("{title}", "درخواست تعمیر"))
    assert ("stop", "") in actions(r)
    assert await h.store.get_session("ali") is not None
    r = await h.send("ali", ANSWERS[0])
    assert "شرح مشکل" in text(r)


async def test_submit_creates_record_confirms_and_notifies_owner(h: Harness) -> None:
    r = await submit(h)
    recs = await h.store.list_records(CAP)
    assert len(recs) == 1
    rec = recs[0]
    assert (rec.actor_id, rec.status, rec.item_id) == ("ali", "new", None)
    assert rec.data == {
        "device": "یخچال",
        "problem": "صدا می‌دهد",
        "phone": "09123456789",
        "address": "تهران، خیابان آزادی",
    }
    assert await h.store.get_session("ali") is None

    out = only_outcome(r)
    assert (out.capability, out.action, out.result, out.record_id) == (CAP, "submit", "submitted", rec.id)

    mine = to(r, "ali")
    assert len(mine) == 1 and mine[0].notice is None
    ref = "".join("۰۱۲۳۴۵۶۷۸۹"[int(c)] for c in str(rec.id))
    assert ref in mine[0].text and "در انتظار بررسی" in mine[0].text
    assert [d[0] for d in actions(r, 0)] == ["mine", "home"]

    n = notice_to(r, "owner", "submitted")
    assert "یخچال" in n.text and "09123456789" in n.text and "نوع دستگاه" in n.text and ref in n.text
    assert "ali" in n.text  # the customer's display name
    # one inline button per owner action allowed FROM the initial status
    assert button_data(r, r.messages.index(n)) == [
        f"repair:own:{rec.id}.approve",
        f"repair:own:{rec.id}.reject",
    ]
    assert [e.kind for e in r.effects] == ["record_created", "notification"]


async def test_submit_status_label_not_key_is_shown(h: Harness) -> None:
    r = await submit(h)
    assert "new" not in text(r, 0).replace("درخواست", "")


async def test_ids_are_distinct_per_submission(h: Harness) -> None:
    await submit(h)
    await submit(h, "sara")
    recs = await h.store.list_records(CAP)
    assert [r.actor_id for r in recs] == ["ali", "sara"] and recs[0].id != recs[1].id


# --- form validation -----------------------------------------------------------------------------


async def test_invalid_answer_is_asked_again(h: Harness) -> None:
    r = await h.tap("ali", MENU_MAIN)
    await h.tap("ali", find(r, "new").data)
    await h.send("ali", "یخچال")
    await h.send("ali", "خراب")
    r = await h.send("ali", "نه-شماره")
    assert "شماره تماس" in text(r) and "پذیرفته نشد" in text(r)
    assert await h.store.list_records(CAP) == []
    r = await h.send("ali", "09123456789")
    assert "نشانی" in text(r)
    r = await h.send("ali", "تهران")
    assert only_outcome(r).result == "submitted"


async def test_stop_cancels_the_form(h: Harness) -> None:
    r = await h.tap("ali", MENU_MAIN)
    r = await h.tap("ali", find(r, "new").data)
    r = await h.tap("ali", find(r, "stop").data)
    assert text(r) == "فرم لغو شد."
    assert await h.store.get_session("ali") is None and await h.store.list_records(CAP) == []
    r = await h.send("ali", "متن")  # no session any more: back to the welcome menu
    assert "خوش آمدید" in text(r)


async def test_new_after_abandoned_form_restarts_cleanly(h: Harness) -> None:
    r = await h.tap("ali", MENU_MAIN)
    r = await h.tap("ali", find(r, "new").data)
    await h.send("ali", "یخچال")
    r = await h.tap("ali", MENU_MAIN)  # navigating away clears the session
    r = await h.tap("ali", find(r, "new").data)
    assert "نوع دستگاه" in text(r)
    assert (await h.store.get_session("ali"))["vars"]["answers"] == {}  # type: ignore[index]


# --- item_resource -------------------------------------------------------------------------------


@pytest.fixture
def hi() -> Harness:
    return Harness(repair_spec(item_resource=True))


async def test_new_lists_items_with_pick_buttons(hi: Harness) -> None:
    a = await hi.seed("appliance", {"name": "یخچال"})
    b = await hi.seed("appliance", {"name": "لباسشویی"})
    r = await hi.tap("ali", MENU_MAIN)
    r = await hi.tap("ali", find(r, "new").data)
    assert [x for x in actions(r) if x[0] == "pick"] == [("pick", str(a)), ("pick", str(b))]
    assert "یخچال" in text(r) and "لباسشویی" in text(r)
    assert await hi.store.get_session("ali") is None  # the form starts only after pick


async def test_new_pagination(hi: Harness) -> None:
    ids = [await hi.seed("appliance", {"name": f"دستگاه {i}"}) for i in range(10)]
    r = await hi.tap("ali", MENU_MAIN)
    r = await hi.tap("ali", find(r, "new").data)
    assert len([x for x in actions(r) if x[0] == "pick"]) == 8
    assert ("new", "1") in actions(r)
    r = await hi.tap("ali", find(r, "new", "1").data)
    assert [x for x in actions(r) if x[0] == "pick"] == [("pick", str(ids[8])), ("pick", str(ids[9]))]
    assert ("new", "0") in actions(r)


async def test_new_with_no_items_says_so(hi: Harness) -> None:
    r = await hi.tap("ali", MENU_MAIN)
    r = await hi.tap("ali", find(r, "new").data)
    assert text(r) == tx.NO_ITEMS
    assert not [x for x in actions(r) if x[0] == "pick"]


async def test_pick_keeps_item_and_submission_is_tied_to_it(hi: Harness) -> None:
    await hi.seed("appliance", {"name": "یخچال"})
    b = await hi.seed("appliance", {"name": "لباسشویی"})
    r = await hi.tap("ali", MENU_MAIN)
    r = await hi.tap("ali", find(r, "new").data)
    r = await hi.tap("ali", find(r, "pick", b).data)
    assert "لباسشویی" in text(r) and "نوع دستگاه" in text(r)
    assert (await hi.store.get_session("ali"))["vars"]["data"] == {"item_id": b}  # type: ignore[index]
    r = await fill(hi, "ali")
    rec = (await hi.store.list_records(CAP))[0]
    assert rec.item_id == b and "item_id" not in rec.data
    assert only_outcome(r).record_id == rec.id
    assert "لباسشویی" in notice_to(r, "owner", "submitted").text
    mine = await hi.tap("ali", MENU_MINE)
    assert "لباسشویی" in text(mine) and "یخچال" not in text(mine)


async def test_pick_missing_item_is_rejected(hi: Harness) -> None:
    r = await hi.tap("ali", "repair:pick:999")
    out = only_outcome(r)
    assert (out.action, out.result, out.reason) == ("submit", "rejected", "not_found")
    assert await hi.store.get_session("ali") is None


async def test_pick_garbage_arg_is_rejected(hi: Harness) -> None:
    r = await hi.tap("ali", "repair:pick:abc")
    assert only_outcome(r).reason == "not_found"


async def test_item_deleted_during_form_rejects_the_submission(hi: Harness) -> None:
    a = await hi.seed("appliance", {"name": "یخچال"})
    r = await hi.tap("ali", MENU_MAIN)
    r = await hi.tap("ali", find(r, "new").data)
    await hi.tap("ali", find(r, "pick", a).data)
    await hi.store.delete_record("appliance", a)
    r = await fill(hi, "ali")
    out = only_outcome(r)
    assert (out.action, out.result, out.reason) == ("submit", "rejected", "not_found")
    assert await hi.store.list_records(CAP) == []
    assert to(r, "owner") == []  # nothing to notify about


async def test_pick_without_item_resource_is_stale(h: Harness) -> None:
    r = await h.tap("ali", "repair:pick:1")
    assert "دیگر در دسترس نیست" in text(r)
    assert r.outcomes == []


# --- mine ----------------------------------------------------------------------------------------


async def test_mine_empty(h: Harness) -> None:
    r = await h.tap("ali", MENU_MINE)
    assert text(r) == "شما هنوز درخواستی ثبت نکرده‌اید."
    assert ("new", "") in actions(r)


async def test_mine_lists_own_requests_newest_first_with_status_and_jalali_date(h: Harness) -> None:
    await submit(h, "ali")
    await submit(h, "sara")
    h.advance(24)
    await submit(h, "ali")
    first, _, third = (r.id for r in await h.store.list_records(CAP))
    for entry in (MENU_MINE, "repair:mine:"):
        r = await h.tap("ali", entry)
        lines = [ln for ln in text(r).splitlines() if ln.startswith("•")]
        assert len(lines) == 2  # sara's request is not listed
        assert f"کد {_p(third)}" in lines[0] and f"کد {_p(first)}" in lines[1]
        assert all("در انتظار بررسی" in ln for ln in lines)
        assert "مهر ۱۴۰۵" in lines[1] and "۱۳ مهر ۱۴۰۵" in lines[0]  # created T0 = 12 Mehr, +24h = 13 Mehr


def _p(n: int) -> str:
    return "".join("۰۱۲۳۴۵۶۷۸۹"[int(c)] for c in str(n))


async def test_mine_reflects_status_changes(h: Harness) -> None:
    await submit(h)
    rid = (await h.store.list_records(CAP))[0].id
    await h.tap("owner", f"repair:own:{rid}.approve")
    r = await h.tap("ali", "repair:mine:")
    assert "تأیید شده" in text(r) and "در انتظار بررسی" not in text(r)


# --- owner actions -------------------------------------------------------------------------------


async def pending(h: Harness) -> int:
    await submit(h)
    return (await h.store.list_records(CAP))[-1].id


@pytest.mark.parametrize("via", ["callback", "admin"])
async def test_owner_action_moves_status_and_notifies_customer(h: Harness, via: str) -> None:
    rid = await pending(h)
    data = f"repair:own:{rid}.approve"
    r = await (h.tap("owner", data) if via == "callback" else h.admin(data))

    assert (await h.store.get_record(CAP, rid)).status == "approved"  # type: ignore[union-attr]
    out = only_outcome(r)
    assert (out.capability, out.action, out.result, out.reason, out.record_id) == (
        CAP,
        "owner_action",
        "ok",
        None,
        rid,
    )
    own = to(r, "owner")
    assert len(own) == 1 and own[0].notice is None
    assert "تأیید شده" in own[0].text and _p(rid) in own[0].text
    # buttons now follow the NEW status: only mark_done is allowed from approved
    assert button_data(r, 0) == [f"repair:own:{rid}.mark_done"]

    n = notice_to(r, "ali", "status_changed")
    assert "تأیید شده" in n.text and _p(rid) in n.text
    assert [d[0] for d in actions(r, r.messages.index(n))] == ["mine", "home"]
    assert [e.kind for e in r.effects] == ["record_updated", "notification"]
    assert r.effects[0].status == "approved"


async def test_full_chain_to_a_status_without_actions(h: Harness) -> None:
    rid = await pending(h)
    await h.tap("owner", f"repair:own:{rid}.approve")
    r = await h.tap("owner", f"repair:own:{rid}.mark_done")
    assert (await h.store.get_record(CAP, rid)).status == "done"  # type: ignore[union-attr]
    assert button_data(r, 0) == []
    assert "انجام شده" in notice_to(r, "ali", "status_changed").text


async def test_owner_action_unknown_record(h: Harness) -> None:
    r = await h.tap("owner", "repair:own:999.approve")
    out = only_outcome(r)
    assert (out.action, out.result, out.reason, out.record_id) == (
        "owner_action",
        "rejected",
        "not_found",
        999,
    )
    assert [m.to_actor_id for m in r.messages] == ["owner"]


async def test_owner_action_unknown_key(h: Harness) -> None:
    rid = await pending(h)
    r = await h.tap("owner", f"repair:own:{rid}.explode")
    out = only_outcome(r)
    assert (out.result, out.reason, out.record_id) == ("rejected", "not_allowed", rid)
    assert (await h.store.get_record(CAP, rid)).status == "new"  # type: ignore[union-attr]
    assert [m.to_actor_id for m in r.messages] == ["owner"]
    assert button_data(r, 0) == [f"repair:own:{rid}.approve", f"repair:own:{rid}.reject"]


async def test_stale_button_after_status_changed_is_rejected_not_a_crash(h: Harness) -> None:
    rid = await pending(h)
    await h.tap("owner", f"repair:own:{rid}.approve")
    for stale in ("approve", "reject"):  # both buttons of the original notice are now stale
        r = await h.tap("owner", f"repair:own:{rid}.{stale}")
        out = only_outcome(r)
        assert (out.action, out.result, out.reason) == ("owner_action", "rejected", "not_allowed")
        assert "تأیید شده" in text(r, 0)  # names the CURRENT status
        assert button_data(r, 0) == [f"repair:own:{rid}.mark_done"]  # fresh buttons for it
        assert [m.to_actor_id for m in r.messages] == ["owner"]  # customer is not notified
    assert (await h.store.get_record(CAP, rid)).status == "approved"  # type: ignore[union-attr]


async def test_action_from_a_disallowed_status_via_admin(h: Harness) -> None:
    rid = await pending(h)
    r = await h.admin(f"repair:own:{rid}.mark_done")
    out = only_outcome(r)
    assert (out.result, out.reason) == ("rejected", "not_allowed")
    assert "در انتظار بررسی" in text(r) and r.effects == []


async def test_malformed_owner_arg_is_invalid_input(h: Harness) -> None:
    for arg in ("approve", "x.approve", "5."):
        r = await h.tap("owner", f"repair:own:{arg}")
        assert only_outcome(r).reason == "invalid_input"


# --- non-owners ----------------------------------------------------------------------------------


async def test_non_owner_cannot_use_own_button(h: Harness) -> None:
    rid = await pending(h)
    r = await h.tap("ali", f"repair:own:{rid}.approve")
    out = only_outcome(r)
    assert (out.action, out.result, out.reason) == ("owner_action", "rejected", "not_allowed")
    assert (await h.store.get_record(CAP, rid)).status == "new"  # type: ignore[union-attr]
    assert [m.to_actor_id for m in r.messages] == ["ali"]


async def test_non_owner_admin_event_is_rejected(h: Harness) -> None:
    rid = await pending(h)
    r = await h.admin(f"repair:own:{rid}.approve", actor="sara")
    out = only_outcome(r)
    assert (out.action, out.result, out.reason) == ("owner_action", "rejected", "not_allowed")
    assert (await h.store.get_record(CAP, rid)).status == "new"  # type: ignore[union-attr]
    assert not [m for m in r.messages if m.to_actor_id == "ali"]


# --- notifications -------------------------------------------------------------------------------


async def test_notifications_can_be_turned_off() -> None:
    h = Harness(repair_spec(notify_owner_on=[], notify_user_on=[]))
    r = await submit(h)
    assert [m.to_actor_id for m in r.messages] == ["ali"] and only_outcome(r).result == "submitted"
    rid = (await h.store.list_records(CAP))[0].id
    r = await h.tap("owner", f"repair:own:{rid}.approve")
    assert [m.to_actor_id for m in r.messages] == ["owner"] and only_outcome(r).result == "ok"
    assert [e.kind for e in r.effects] == ["record_updated"]


async def test_owner_off_but_user_on() -> None:
    h = Harness(repair_spec(notify_owner_on=[]))
    r = await submit(h)
    assert [m.to_actor_id for m in r.messages] == ["ali"]
    rid = (await h.store.list_records(CAP))[0].id
    r = await h.tap("owner", f"repair:own:{rid}.reject")
    assert notice_to(r, "ali", "status_changed")


async def test_owner_submitting_is_not_self_notified(h: Harness) -> None:
    r = await submit(h, "owner")
    assert [m.to_actor_id for m in r.messages] == ["owner"]
    rid = (await h.store.list_records(CAP))[0].id
    r = await h.tap("owner", f"repair:own:{rid}.approve")
    assert [m.to_actor_id for m in r.messages] == ["owner"]  # customer == owner: no duplicate


async def test_no_owner_linked_skips_owner_notice() -> None:
    from app.runtime.memory_store import MemoryStore

    h = Harness(repair_spec(), store=MemoryStore(owner_actor_id=None))
    r = await submit(h)
    assert [m.to_actor_id for m in r.messages] == ["ali"]


# --- statuses, owner action variants, texts ------------------------------------------------------


async def test_owner_actions_available_from_several_statuses() -> None:
    owner_actions = [
        {"key": "approve", "label": "تأیید", "from_statuses": ["new"], "to_status": "approved"},
        {
            "key": "reopen",
            "label": "بازگشایی",
            "from_statuses": ["new", "approved", "done"],
            "to_status": "new",
        },
        {"key": "mark_done", "label": "انجام شد", "from_statuses": ["approved"], "to_status": "done"},
    ]
    h = Harness(repair_spec(owner_actions=owner_actions))
    r = await submit(h)
    n = notice_to(r, "owner", "submitted")
    rid = (await h.store.list_records(CAP))[0].id
    assert button_data(r, r.messages.index(n)) == [f"repair:own:{rid}.approve", f"repair:own:{rid}.reopen"]
    r = await h.tap("owner", f"repair:own:{rid}.approve")
    assert button_data(r, 0) == [f"repair:own:{rid}.reopen", f"repair:own:{rid}.mark_done"]
    r = await h.tap("owner", f"repair:own:{rid}.reopen")
    assert (await h.store.get_record(CAP, rid)).status == "new"  # type: ignore[union-attr]


async def test_text_overrides() -> None:
    texts = [
        {"key": "submitted", "value": "ثبت شد! {title} #{id}"},
        {"key": "owner_submitted", "value": "جدید از {user}"},
        {"key": "status_changed", "value": "وضعیت شما: {status}"},
        {"key": "action_done", "value": "انجام: {status}"},
        {"key": "mine_empty", "value": "خالی"},
        {"key": "ask_field", "value": "بنویسید {label}"},
        {"key": "not_allowed", "value": "ممنوع"},
    ]
    h = Harness(repair_spec(texts=texts))
    r = await h.tap("ali", MENU_MINE)
    assert text(r) == "خالی"
    r = await h.tap("ali", MENU_MAIN)
    r = await h.tap("ali", find(r, "new").data)
    assert text(r).endswith("بنویسید نوع دستگاه (مثلاً یخچال یا لباسشویی)")
    r = await fill(h, "ali", ANSWERS)
    rid = (await h.store.list_records(CAP))[0].id
    assert text(r, 0).startswith(f"ثبت شد! درخواست تعمیر #{_p(rid)}")
    assert "در انتظار بررسی" in text(r, 0)  # the fixed status line is still appended
    assert notice_to(r, "owner", "submitted").text == "جدید از ali"
    r = await h.tap("owner", f"repair:own:{rid}.approve")
    assert text(r, 0) == "انجام: تأیید شده"
    assert notice_to(r, "ali", "status_changed").text == "وضعیت شما: تأیید شده"
    r = await h.tap("owner", f"repair:own:{rid}.nope")
    assert text(r, 0) == "ممنوع"


async def test_values_are_formatted_with_ctx_helpers() -> None:
    h = Harness(
        repair_spec(
            form_fields=[
                {"key": "device", "label": "دستگاه", "type": "text"},
                {"key": "count", "label": "تعداد", "type": "integer"},
                {"key": "urgent", "label": "فوری", "type": "boolean", "required": False},
            ]
        )
    )
    r = await h.tap("ali", MENU_MAIN)
    await h.tap("ali", find(r, "new").data)
    await h.send("ali", "یخچال")
    await h.send("ali", "۱۲۳۴")
    r = await h.tap("ali", "repair:skip:")
    n = notice_to(r, "owner", "submitted")
    assert "تعداد: ۱٬۲۳۴" in n.text and "فوری: —" in n.text


async def test_request_without_form_fields_is_created_immediately() -> None:
    h = Harness(repair_spec(form_fields=[]))
    r = await h.tap("ali", MENU_MAIN)
    r = await h.tap("ali", find(r, "new").data)
    assert only_outcome(r).result == "submitted"
    assert (await h.store.list_records(CAP))[0].data == {}


async def test_unknown_action_for_the_capability_is_stale(h: Harness) -> None:
    r = await h.tap("ali", "repair:list:0")  # a booking action: refused by the runtime
    assert "دیگر در دسترس نیست" in text(r)
    assert r.outcomes == []
