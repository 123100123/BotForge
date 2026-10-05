"""Roles end to end: Team API, the staff deep link through the webhook, dispatch's role read and the
simulator's staff persona. Needs a database."""

import json
import logging
import re
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.botspec.models import BotSpec
from app.db.models import Bot, BotUser, RecordRow
from app.integrations.telegram import texts as telegram_texts
from app.integrations.telegram.client import FakeTelegramClient
from app.roles.service import STAFF_JOINED, STAFF_LINK_INVALID, set_role
from app.runtime.callbacks import make_callback
from app.runtime.contracts import Actor, RuntimeEvent, RuntimeResponse
from app.runtime.pg_store import PgStore
from app.runtime.texts import common
from app.security.csrf import CSRF_HEADER
from app.services.dispatch import dispatch
from tests.integration.conftest import MakeBot
from tests.integration.helpers import NOW, REPO, SessionFactory
from tests.integration.tg_helpers import ALICE, Chat, LiveBot, make_live_bot, message_update

BOB = {"X-Test-User": "bob"}
ANONYMOUS = {"X-Test-User": "anonymous"}
CAP = "repair"
REQUEST = {"device": "یخچال", "problem": "صدا می‌دهد", "phone": "09123456789", "address": "تهران"}
NO_ONE = {"customer": 0, "staff": 0, "manager": 0}


def repair_spec() -> dict[str, Any]:
    """The repair example with its info capability restricted to staff (a staff-only menu item)."""
    spec = json.loads((REPO / "examples" / "repair.botspec.json").read_text(encoding="utf-8"))
    for cap in spec["capabilities"]:
        if cap["key"] == "info":
            cap["audience"] = "staff"
    return spec


@pytest.fixture
async def bot(session_factory: SessionFactory, tg_env: None) -> LiveBot:
    """A connected bot (token, webhook secret, username) with the repair spec and a linked owner."""
    return await make_live_bot(session_factory, repair_spec(), owner_actor_id="900")


def team_url(bot_id: Any, rest: str = "") -> str:
    return f"/bots/{bot_id}/team{rest}"


async def rotate(client: httpx.AsyncClient, bot_id: Any) -> str:
    response = await client.post(team_url(bot_id, "/staff-link"), headers=ALICE)
    assert response.status_code == 200, response.text
    return response.json()["staff_link_code"]


async def add_request(session_factory: SessionFactory, bot_id: uuid.UUID, env: str, actor: str) -> int:
    async with session_factory() as session:
        store = PgStore(session, bot_id, env)  # type: ignore[arg-type]
        record = await store.create_record(CAP, REQUEST, status="new", actor_id=actor, now=NOW)
        await session.commit()
        return record.id


async def status_of(session_factory: SessionFactory, record_id: int) -> str | None:
    async with session_factory() as session:
        row = await session.get(RecordRow, record_id)
        assert row is not None
        return row.status


async def user_row(
    session_factory: SessionFactory, bot_id: uuid.UUID, actor_id: str, env: str = "live"
) -> BotUser | None:
    async with session_factory() as session:
        stmt = select(BotUser).where(
            BotUser.bot_id == bot_id, BotUser.env == env, BotUser.actor_id == actor_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def stored_code(session_factory: SessionFactory, bot_id: uuid.UUID) -> str | None:
    async with session_factory() as session:
        row = await session.get(Bot, bot_id)
        assert row is not None
        return row.staff_link_code


def menu_has(chat: Chat, data: str) -> bool:
    return any(b["callback_data"] == data for b in chat.buttons())


# --- Team API: the staff link -------------------------------------------------------------------


async def test_a_new_bot_has_no_staff_link_and_no_members(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    response = await tg_client.get(team_url(bot.id), headers=ALICE)
    assert response.status_code == 200
    assert response.json() == {"staff_link": None, "staff_link_code": None, "members": [], "counts": NO_ONE}


async def test_rotating_gives_a_link_and_a_new_code_kills_the_old_one(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    first = (await tg_client.post(team_url(bot.id, "/staff-link"), headers=ALICE)).json()
    code = first["staff_link_code"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", code)
    assert first["staff_link"] == f"https://t.me/workshop_test_bot?start=staff_{code}"
    assert await stored_code(session_factory, bot.id) == code

    second = await rotate(tg_client, bot.id)
    assert second != code and await stored_code(session_factory, bot.id) == second
    team = (await tg_client.get(team_url(bot.id), headers=ALICE)).json()
    assert team["staff_link_code"] == second and team["staff_link"].endswith(f"start=staff_{second}")

    late = Chat(tg_client, bot, fake_tg, 701)
    await late.say(f"/start staff_{code}")
    assert [m["text"] for m in late.shown()] == [STAFF_LINK_INVALID]
    assert await user_row(session_factory, bot.id, "701") is None


async def test_revoking_kills_the_link_and_keeps_the_staff(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    code = await rotate(tg_client, bot.id)
    await Chat(tg_client, bot, fake_tg, 700).say(f"/start staff_{code}")
    gone = await tg_client.delete(team_url(bot.id, "/staff-link"), headers=ALICE)
    assert gone.status_code == 204 and gone.content == b""
    assert await stored_code(session_factory, bot.id) is None
    team = (await tg_client.get(team_url(bot.id), headers=ALICE)).json()
    assert (team["staff_link"], team["staff_link_code"]) == (None, None)
    assert [m["role"] for m in team["members"]] == ["staff"]  # who joined stays staff

    newcomer = Chat(tg_client, bot, fake_tg, 702)
    await newcomer.say(f"/start staff_{code}")
    assert [m["text"] for m in newcomer.shown()] == [STAFF_LINK_INVALID]
    assert await user_row(session_factory, bot.id, "702") is None
    assert (await tg_client.delete(team_url(bot.id, "/staff-link"), headers=ALICE)).status_code == 204


async def test_a_disconnected_bot_gets_a_code_but_no_link(
    tg_client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot("alice")
    body = (await tg_client.post(team_url(bot_id, "/staff-link"), headers=ALICE)).json()
    assert body["staff_link"] is None and body["staff_link_code"]


async def test_only_the_owner_reaches_the_team_routes(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    routes = [
        ("GET", team_url(bot.id), None),
        ("POST", team_url(bot.id, "/staff-link"), None),
        ("DELETE", team_url(bot.id, "/staff-link"), None),
        ("PATCH", team_url(bot.id, "/members/900"), {"role": "staff"}),
    ]
    for method, url, body in routes:
        other = await tg_client.request(method, url, json=body, headers=BOB)
        assert other.status_code == 404 and other.json()["error"]["code"] == "bot_not_found", url
        assert (await tg_client.request(method, url, json=body, headers=ANONYMOUS)).status_code == 401, url
        if method != "GET":  # a state-changing request without the CSRF header never runs
            forged = await tg_client.request(method, url, json=body, headers={**ALICE, CSRF_HEADER: "0"})
            assert forged.status_code == 403 and forged.json()["error"]["code"] == "csrf_failed", url
    unknown = await tg_client.get(team_url(uuid.uuid4()), headers=ALICE)
    assert unknown.status_code == 404
    team = (await tg_client.get(team_url(bot.id), headers=ALICE)).json()
    assert team["staff_link_code"] is None  # nothing above created a code


# --- the staff deep link through the webhook ------------------------------------------------------


async def test_the_staff_link_makes_the_sender_staff_who_then_works_the_queue(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    code = await rotate(tg_client, bot.id)
    rid = await add_request(session_factory, bot.id, "live", "601")

    # a customer sees no staff item and cannot decide on the request
    customer = Chat(tg_client, bot, fake_tg, 602)
    await customer.say("/start")
    assert menu_has(customer, "menu:open:new_request") and not menu_has(customer, "menu:open:about")
    await customer.press(f"{CAP}:own:{rid}.approve")
    assert customer.last_text() == common.NOT_ALLOWED
    assert await status_of(session_factory, rid) == "new"

    # joining: the confirmation, then the normal start with the staff-only item
    staff = Chat(tg_client, bot, fake_tg, 700)
    await staff.say(f"/start staff_{code}")
    texts = [m["text"] for m in staff.shown()]
    assert texts[0] == STAFF_JOINED and len(texts) == 2 and texts[1].startswith("سلام")
    assert menu_has(staff, "menu:open:about")
    row = await user_row(session_factory, bot.id, "700")
    assert row is not None and row.role == "staff" and row.display_name == "کاربر"

    # the request queue, and an owner action that notifies the customer but not the owner
    await staff.press("menu:open:new_request")
    assert staff.data_with(f"{CAP}:own:{rid}.approve")
    owner_before = len(fake_tg.sent_to(900))
    await staff.press(f"{CAP}:own:{rid}.approve")
    assert await status_of(session_factory, rid) == "approved"
    assert len(fake_tg.sent_to(601)) == 1  # the status_changed notice
    assert len(fake_tg.sent_to(900)) == owner_before

    # the role survives later events (upsert_user rewrites only the display name)
    await staff.say("/start")
    assert menu_has(staff, "menu:open:about")
    row = await user_row(session_factory, bot.id, "700")
    assert row is not None and row.role == "staff"

    assert code not in caplog.text  # the code is never logged


async def test_an_invalid_staff_link_changes_nothing_and_gets_one_generic_reply(
    tg_client: httpx.AsyncClient,
    bot: LiveBot,
    fake_tg: FakeTelegramClient,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    code = await rotate(tg_client, bot.id)
    other = await make_live_bot(session_factory, golden_spec)
    foreign = await rotate(tg_client, other.id)
    last = "A" if code[-1] != "A" else "B"
    payloads = [
        "staff_",  # empty
        f"staff_{code[:-1]}{last}",  # one character off
        f"staff_{code}x",  # a longer value that starts with the code
        f"staff_{code.swapcase()}",
        "staff_" + "x" * 300,
        f"staff_{foreign}",  # a real code, of another bot
    ]
    for i, payload in enumerate(payloads):
        chat = Chat(tg_client, bot, fake_tg, 720 + i)
        assert (await chat.say(f"/start {payload}")).status_code == 200
        assert [m["text"] for m in chat.shown()] == [STAFF_LINK_INVALID], payload  # no menu either
        assert await user_row(session_factory, bot.id, str(720 + i)) is None, payload

    # the right code sent from a group chat does nothing at all
    group = Chat(tg_client, bot, fake_tg, 740)
    in_group = message_update(740_001, 740, f"/start staff_{code}", chat_type="group")
    assert (await group.post(in_group)).status_code == 200
    assert group.shown() == [] and await user_row(session_factory, bot.id, "740") is None


async def test_joining_a_bot_without_an_active_revision_records_the_role(
    tg_client: httpx.AsyncClient, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    bot = await make_live_bot(session_factory, None)
    code = await rotate(tg_client, bot.id)
    chat = Chat(tg_client, bot, fake_tg, 750)
    await chat.say(f"/start staff_{code}")
    assert [m["text"] for m in chat.shown()] == [STAFF_JOINED, telegram_texts.NOT_READY]
    row = await user_row(session_factory, bot.id, "750")
    assert row is not None and row.role == "staff"


async def test_opening_the_link_again_or_as_a_manager_changes_nothing(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    code = await rotate(tg_client, bot.id)
    staff = Chat(tg_client, bot, fake_tg, 700)
    for _ in range(2):
        await staff.say(f"/start staff_{code}")
        assert staff.shown()[-2]["text"] == STAFF_JOINED
        row = await user_row(session_factory, bot.id, "700")
        assert row is not None and row.role == "staff"

    promoted = await tg_client.patch(
        team_url(bot.id, "/members/700"), json={"role": "manager"}, headers=ALICE
    )
    assert promoted.status_code == 200 and promoted.json()["role"] == "manager"
    await staff.say(f"/start staff_{code}")
    row = await user_row(session_factory, bot.id, "700")
    assert row is not None and row.role == "manager"  # the link never demotes

    owner = Chat(tg_client, bot, fake_tg, 900)
    await owner.say(f"/start staff_{code}")
    assert owner.shown()[0]["text"] == STAFF_JOINED and menu_has(owner, "menu:open:about")
    row = await user_row(session_factory, bot.id, "900")
    assert row is not None and row.role == "customer"  # a manager by ownership; nothing that outlives it


# --- Team API: members --------------------------------------------------------------------------


async def test_the_team_lists_the_owner_managers_and_staff_with_counts(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    code = await rotate(tg_client, bot.id)
    for user_id in (900, 601, 603):
        await Chat(tg_client, bot, fake_tg, user_id).say("/start")
    await Chat(tg_client, bot, fake_tg, 602).say(f"/start staff_{code}")
    assert (
        await tg_client.patch(team_url(bot.id, "/members/603"), json={"role": "manager"}, headers=ALICE)
    ).status_code == 200

    team = (await tg_client.get(team_url(bot.id), headers=ALICE)).json()
    assert [(m["actor_id"], m["role"]) for m in team["members"]] == [
        ("900", "manager"),  # the owner, a manager whatever is stored
        ("603", "manager"),
        ("602", "staff"),
    ]
    assert all(m["display_name"] == "کاربر" and m["first_seen"] for m in team["members"])
    assert team["counts"] == {"customer": 1, "staff": 1, "manager": 2}


async def test_member_roles_change_but_the_owner_stays_a_manager(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    for user_id in (900, 601):
        await Chat(tg_client, bot, fake_tg, user_id).say("/start")

    async def patch(actor_id: str, role: str) -> httpx.Response:
        url = team_url(bot.id, f"/members/{actor_id}")
        return await tg_client.patch(url, json={"role": role}, headers=ALICE)

    for role in ("staff", "manager", "customer"):
        response = await patch("601", role)
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["actor_id"], body["role"], body["display_name"]) == ("601", role, "کاربر")
        row = await user_row(session_factory, bot.id, "601")
        assert row is not None and row.role == role

    refused = await patch("900", "staff")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "owner_role_locked"
    row = await user_row(session_factory, bot.id, "900")
    assert row is not None and row.role == "customer"  # untouched (effective role: manager)
    accepted = await patch("900", "manager")
    assert accepted.status_code == 200 and accepted.json()["role"] == "manager"
    row = await user_row(session_factory, bot.id, "900")
    assert row is not None and row.role == "customer"  # still nothing stored for the owner

    missing = await patch("999", "staff")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "member_not_found"
    assert await user_row(session_factory, bot.id, "999") is None
    assert (await patch("601", "admin")).status_code == 422
    assert (await patch("1" * 65, "staff")).status_code == 422


async def test_sandbox_personas_are_not_members(
    tg_client: httpx.AsyncClient, bot: LiveBot, session_factory: SessionFactory
) -> None:
    body = {"revision_id": None, "persona": "ali", "kind": "start"}
    started = await tg_client.post(f"/bots/{bot.id}/simulator/events", json=body, headers=ALICE)
    assert started.status_code == 200
    assert await user_row(session_factory, bot.id, "ali", env="sandbox") is not None
    missing = await tg_client.patch(team_url(bot.id, "/members/ali"), json={"role": "staff"}, headers=ALICE)
    assert missing.status_code == 404
    assert (await tg_client.get(team_url(bot.id), headers=ALICE)).json()["counts"] == NO_ONE


# --- dispatch and the simulator -----------------------------------------------------------------


async def run(
    session_factory: SessionFactory, bot: LiveBot, event: RuntimeEvent, fake: FakeTelegramClient
) -> RuntimeResponse:
    spec = BotSpec.model_validate(repair_spec())
    async with session_factory() as session:
        row = await session.get(Bot, bot.id)
        assert row is not None
        return await dispatch(session, row, spec, event, telegram=fake.provider)


def own_event(bot: LiveBot, env: str, rid: int, role: str) -> RuntimeEvent:
    return RuntimeEvent(
        bot_id=str(bot.id),
        env=env,  # type: ignore[arg-type]
        actor=Actor(id="650", display_name="x", role=role),  # type: ignore[arg-type]
        kind="callback",
        data=make_callback(CAP, "own", f"{rid}.approve"),
        now=NOW,
    )


async def test_dispatch_takes_a_live_role_from_the_database_never_from_the_event(
    session_factory: SessionFactory, bot: LiveBot, fake_tg: FakeTelegramClient
) -> None:
    rid = await add_request(session_factory, bot.id, "live", "601")
    forged = await run(session_factory, bot, own_event(bot, "live", rid, "manager"), fake_tg)
    assert [(o.result, o.reason) for o in forged.outcomes] == [("rejected", "not_allowed")]
    assert await status_of(session_factory, rid) == "new"

    async with session_factory() as session:
        await set_role(session, bot.id, "live", "650", "staff", display_name="x")
        await session.commit()
    allowed = await run(session_factory, bot, own_event(bot, "live", rid, "customer"), fake_tg)
    assert [o.result for o in allowed.outcomes] == ["ok"]
    assert await status_of(session_factory, rid) == "approved"

    # sandbox events keep the persona's role: the live role of the same id plays no part
    srid = await add_request(session_factory, bot.id, "sandbox", "ali")
    refused = await run(session_factory, bot, own_event(bot, "sandbox", srid, "customer"), fake_tg)
    assert [(o.result, o.reason) for o in refused.outcomes] == [("rejected", "not_allowed")]
    done = await run(session_factory, bot, own_event(bot, "sandbox", srid, "staff"), fake_tg)
    assert [o.result for o in done.outcomes] == ["ok"]


async def test_the_simulator_staff_persona_sees_staff_items_and_works_the_queue(
    tg_client: httpx.AsyncClient, bot: LiveBot, session_factory: SessionFactory
) -> None:
    srid = await add_request(session_factory, bot.id, "sandbox", "ali")

    async def sim(persona: str, kind: str, **kw: Any) -> httpx.Response:
        body = {"revision_id": None, "persona": persona, "kind": kind, **kw}
        return await tg_client.post(f"/bots/{bot.id}/simulator/events", json=body, headers=ALICE)

    def data(response: httpx.Response) -> list[str]:
        return [b["data"] for m in response.json()["messages"] for row in m["buttons"] for b in row]

    assert "menu:open:about" in data(await sim("staff", "start"))
    assert "menu:open:about" not in data(await sim("ali", "start"))
    assert f"{CAP}:own:{srid}.approve" in data(await sim("staff", "callback", data="menu:open:new_request"))
    refused = (await sim("sara", "callback", data=f"{CAP}:own:{srid}.approve")).json()
    assert [(o["result"], o["reason"]) for o in refused["outcomes"]] == [("rejected", "not_allowed")]
    done = (await sim("staff", "callback", data=f"{CAP}:own:{srid}.approve")).json()
    assert [o["result"] for o in done["outcomes"]] == ["ok"]
    persona = await user_row(session_factory, bot.id, "staff", env="sandbox")
    assert persona is not None and persona.display_name == "همکار"
    assert (await sim("manager", "start")).status_code == 422  # still a closed list
