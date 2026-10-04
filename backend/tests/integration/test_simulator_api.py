"""Simulator endpoints (sandbox adapter over the one runtime). Needs a database."""

import copy
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.models import BotUser, RecordRow
from app.integrations.telegram.client import FakeTelegramClient
from app.revisions.service import activate, create_draft
from app.runtime.pg_store import PgStore
from tests.integration.conftest import MakeBot
from tests.integration.helpers import NOW, SessionFactory
from tests.integration.tg_helpers import ALICE, CAP

BOB = {"X-Test-User": "bob"}

SAMPLE = [
    {
        "ref": "w1",
        "collection": "workshop",
        "values": [
            {"key": "title", "value": "کارگاه نمونه"},
            {"key": "description", "value": "توضیح"},
            {"key": "teacher", "value": "سارا"},
            {"key": "starts_at", "value": "+48h"},
            {"key": "price", "value": "100"},
        ],
    }
]


async def send(
    client: httpx.AsyncClient, bot_id: Any, persona: str, kind: str, revision_id: Any = None, **kw: Any
) -> httpx.Response:
    body = {"revision_id": str(revision_id) if revision_id else None, "persona": persona, "kind": kind, **kw}
    return await client.post(f"/bots/{bot_id}/simulator/events", json=body, headers=ALICE)


async def draft_revision(
    session_factory: SessionFactory, bot_id: Any, spec: dict[str, Any], **kw: Any
) -> uuid.UUID:
    async with session_factory() as session:
        revision = await create_draft(session, bot_id, spec=spec, **kw)
        await session.commit()
        return revision.id


async def test_start_against_the_active_revision(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, fake_tg: FakeTelegramClient
) -> None:
    bot_id, _ = await make_bot("alice")
    response = await send(tg_client, bot_id, "ali", "start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"messages", "outcomes", "effects"}
    [message] = body["messages"]
    assert message["to_actor_id"] == "ali" and message["text"].startswith("سلام")
    assert [b["data"] for row in message["buttons"] for b in row][:1] == ["menu:open:workshops"]
    assert fake_tg.calls == []  # the sandbox never talks to Telegram


async def test_booking_flow_in_the_sandbox_returns_messages_for_other_personas(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice")
    reset = await tg_client.post(f"/bots/{bot_id}/simulator/reset", json={"revision_id": None}, headers=ALICE)
    assert reset.json() == {"ok": True, "loaded": 0}  # no sample data on this revision

    async with session_factory() as session:
        item = (
            await PgStore(session, bot_id, "sandbox", "owner").create_record(
                "workshop", {"title": "کارگاه", "starts_at": "2027-11-01T06:30:00+00:00"}, now=NOW
            )
        ).id
        await session.commit()

    first = await send(tg_client, bot_id, "ali", "callback", data=f"{CAP}:book:{item}")
    outcomes = first.json()["outcomes"]
    assert outcomes[0]["result"] == "confirmed" and outcomes[0]["capability"] == CAP
    # the owner persona is told (notify_owner_on: booked), in the same response
    assert {m["to_actor_id"] for m in first.json()["messages"]} == {"ali", "owner"}

    # the owner persona can act: cancel through the admin-style callback is refused for customers
    denied = await send(tg_client, bot_id, "sara", "callback", data="book_workshop:cancel:999")
    assert denied.status_code == 200


async def test_text_event_needs_text_and_callback_needs_data(
    tg_client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot("alice")
    for kind in ("text", "callback"):
        response = await send(tg_client, bot_id, "ali", kind)
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_event"
    ok = await send(tg_client, bot_id, "ali", "text", text="سلام")
    assert ok.status_code == 200


async def test_unknown_persona_or_kind_is_a_validation_error(
    tg_client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot("alice")
    assert (await send(tg_client, bot_id, "mallory", "start")).status_code == 422
    assert (await send(tg_client, bot_id, "ali", "admin")).status_code == 422


async def test_no_active_revision_is_409(tg_client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    response = await send(tg_client, bot_id, "ali", "start")
    assert response.status_code == 409 and response.json()["error"]["code"] == "no_active_revision"
    reset = await tg_client.post(f"/bots/{bot_id}/simulator/reset", json={}, headers=ALICE)
    assert reset.status_code == 409


async def test_a_draft_revision_can_be_simulated_with_its_own_spec(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, active_id = await make_bot("alice")
    spec = copy.deepcopy(golden_spec)
    spec["bot"]["welcome_text"] = "خوش آمدید به نسخهٔ پیش‌نویس"
    draft_id = await draft_revision(session_factory, bot_id, spec, parent_id=active_id)
    draft = await send(tg_client, bot_id, "ali", "start", revision_id=draft_id)
    active = await send(tg_client, bot_id, "ali", "start", revision_id=active_id)
    assert draft.json()["messages"][0]["text"] == "خوش آمدید به نسخهٔ پیش‌نویس"
    assert active.json()["messages"][0]["text"] != draft.json()["messages"][0]["text"]
    # null means active, not the draft
    assert (await send(tg_client, bot_id, "ali", "start")).json() == active.json()


async def test_a_foreign_or_unknown_revision_is_refused(
    tg_client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    mine, _ = await make_bot("alice")
    _, foreign_revision = await make_bot("bob")  # a real revision, of another bot
    for revision_id in (foreign_revision, uuid.uuid4()):
        events = await send(tg_client, mine, "ali", "start", revision_id=revision_id)
        assert events.status_code == 404 and events.json()["error"]["code"] == "revision_not_found"
        reset = await tg_client.post(
            f"/bots/{mine}/simulator/reset", json={"revision_id": str(revision_id)}, headers=ALICE
        )
        assert reset.status_code == 404


async def test_a_superseded_revision_cannot_be_simulated(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, first = await make_bot("alice")
    second = await draft_revision(session_factory, bot_id, golden_spec, parent_id=first)
    async with session_factory() as session:
        await activate(session, second)
        await session.commit()
    response = await send(tg_client, bot_id, "ali", "start", revision_id=first)
    assert response.status_code == 409 and response.json()["error"]["code"] == "revision_not_simulatable"


async def test_reset_reloads_the_chosen_revisions_sample_data_and_wipes_sandbox_state(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
) -> None:
    bot_id, active_id = await make_bot("alice")
    draft_id = await draft_revision(
        session_factory, bot_id, golden_spec, parent_id=active_id, sample_data=SAMPLE
    )

    response = await tg_client.post(
        f"/bots/{bot_id}/simulator/reset", json={"revision_id": str(draft_id)}, headers=ALICE
    )
    assert response.json() == {"ok": True, "loaded": 1}

    async def sandbox_titles() -> list[str]:
        async with session_factory() as session:
            rows = await session.execute(
                select(RecordRow).where(
                    RecordRow.bot_id == bot_id, RecordRow.env == "sandbox", RecordRow.collection == "workshop"
                )
            )
            return [r.data["title"] for r in rows.scalars()]

    assert await sandbox_titles() == ["کارگاه نمونه"]
    # the sandbox shows the seeded workshop; reset again with the active revision empties it
    listing = await send(
        tg_client, bot_id, "ali", "callback", data="menu:open:workshops", revision_id=draft_id
    )
    assert "کارگاه نمونه" in str(listing.json()["messages"])
    await tg_client.post(f"/bots/{bot_id}/simulator/reset", json={"revision_id": None}, headers=ALICE)
    assert await sandbox_titles() == []


async def test_reset_does_not_touch_live_data(
    tg_client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice")
    created = await tg_client.post(
        f"/bots/{bot_id}/data/workshop",
        json={
            "data": {
                "title": "زنده",
                "description": "توضیح",
                "teacher": "سارا",
                "starts_at": "2027-01-01T10:00:00+03:30",
                "price": 10,
            }
        },
        headers=ALICE,
    )
    assert created.status_code == 201
    await tg_client.post(f"/bots/{bot_id}/simulator/reset", json={}, headers=ALICE)
    listing = await tg_client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)
    assert listing.json()["total"] == 1


async def test_another_owners_bot_is_a_404(tg_client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice")
    body = {"revision_id": None, "persona": "ali", "kind": "start"}
    assert (
        await tg_client.post(f"/bots/{bot_id}/simulator/events", json=body, headers=BOB)
    ).status_code == 404
    assert (await tg_client.post(f"/bots/{bot_id}/simulator/reset", json={}, headers=BOB)).status_code == 404


@pytest.mark.parametrize("persona,owner", [("ali", False), ("owner", True)])
async def test_personas_have_the_documented_identity(
    tg_client: httpx.AsyncClient,
    make_bot: MakeBot,
    session_factory: SessionFactory,
    persona: str,
    owner: bool,
) -> None:
    bot_id, _ = await make_bot("alice")
    await send(tg_client, bot_id, persona, "start")
    async with session_factory() as session:
        user = (
            await session.execute(
                select(BotUser).where(BotUser.bot_id == bot_id, BotUser.actor_id == persona)
            )
        ).scalar_one()
    assert user.env == "sandbox" and user.display_name == ("مدیر" if owner else "علی")
