"""Owner actions from the web admin go through dispatch and notify customers. Needs a database."""

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.models import RecordRow
from app.integrations.telegram.client import FakeTelegramClient
from app.runtime.pg_store import PgStore
from tests.integration.helpers import NOW, SessionFactory
from tests.integration.test_webhook import WORKSHOP
from tests.integration.tg_helpers import ALICE, CAP, Chat, LiveBot, capacity_spec, make_live_bot

BOB = {"X-Test-User": "bob"}
OWNER_TG_ID = 900


@pytest.fixture
async def bot(session_factory: SessionFactory, golden_spec: dict[str, Any], tg_env: None) -> LiveBot:
    return await make_live_bot(
        session_factory, capacity_spec(golden_spec, 1), owner_actor_id=str(OWNER_TG_ID)
    )


async def add_workshop(client: httpx.AsyncClient, bot: LiveBot) -> int:
    response = await client.post(f"/bots/{bot.id}/data/workshop", json={"data": WORKSHOP}, headers=ALICE)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def bookings(session_factory: SessionFactory, bot: LiveBot) -> dict[str, RecordRow]:
    async with session_factory() as session:
        rows = await session.execute(
            select(RecordRow).where(
                RecordRow.bot_id == bot.id, RecordRow.env == "live", RecordRow.collection == CAP
            )
        )
        return {r.actor_id: r for r in rows.scalars()}


def action(bot: LiveBot, collection: str, record_id: int, name: str) -> str:
    return f"/bots/{bot.id}/data/{collection}/{record_id}/actions/{name}"


async def test_admin_cancel_promotes_and_notifies_the_promoted_customer(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    ali, sara = Chat(tg_client, bot, fake_tg, 601), Chat(tg_client, bot, fake_tg, 602)
    await ali.press(f"{CAP}:book:{item}")
    await sara.press(f"{CAP}:book:{item}")
    rows = await bookings(session_factory, bot)
    assert (rows["601"].status, rows["602"].status) == ("confirmed", "waitlisted")

    fake_tg.calls.clear()
    response = await tg_client.post(action(bot, CAP, rows["601"].id, "cancel"), headers=ALICE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["outcome"]["action"] == "cancel" and body["outcome"]["result"] == "cancelled"
    assert body["outcome"]["record_id"] == rows["601"].id
    assert isinstance(body["message"], str) and body["message"]

    after = await bookings(session_factory, bot)
    assert (after["601"].status, after["602"].status) == ("cancelled", "confirmed")

    # both customers are told in Telegram: the cancelled one and the promoted one
    assert len(fake_tg.sent_to(602)) == 1
    assert len(fake_tg.sent_to(601)) == 1
    assert fake_tg.tokens[-1] == bot.token
    # the owner reply is returned to the web admin, not pushed to the owner's chat
    assert fake_tg.sent_to(OWNER_TG_ID) == []
    assert fake_tg.calls_to("answerCallbackQuery") == []


async def test_admin_cancel_ignores_the_cancellation_deadline_and_works_without_a_linked_owner(
    tg_client: httpx.AsyncClient,
    session_factory: SessionFactory,
    golden_spec: dict[str, Any],
    fake_tg: FakeTelegramClient,
) -> None:
    spec = capacity_spec(golden_spec, 1)
    for cap in spec["capabilities"]:
        if cap["key"] == CAP:
            cap["cancellation"]["deadline_hours"] = 100000  # customers can never cancel
    unlinked = await make_live_bot(session_factory, spec)  # owner_actor_id is None
    item = await add_workshop(tg_client, unlinked)
    customer = Chat(tg_client, unlinked, fake_tg, 611)
    await customer.press(f"{CAP}:book:{item}")
    record = (await bookings(session_factory, unlinked))["611"]

    refused = await customer.press(f"{CAP}:cancel:{record.id}")
    assert refused.status_code == 200
    assert (await bookings(session_factory, unlinked))["611"].status == "confirmed"

    response = await tg_client.post(action(unlinked, CAP, record.id, "cancel"), headers=ALICE)
    assert response.json()["ok"] is True
    assert (await bookings(session_factory, unlinked))["611"].status == "cancelled"


async def test_admin_action_on_a_record_that_is_already_cancelled_reports_not_ok(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    await Chat(tg_client, bot, fake_tg, 601).press(f"{CAP}:book:{item}")
    record = (await bookings(session_factory, bot))["601"]
    first = await tg_client.post(action(bot, CAP, record.id, "cancel"), headers=ALICE)
    second = await tg_client.post(action(bot, CAP, record.id, "cancel"), headers=ALICE)
    assert first.json()["ok"] is True
    assert second.status_code == 200 and second.json()["ok"] is False
    assert second.json()["outcome"]["result"] == "rejected"


async def test_invalid_actions_and_collections(
    tg_client: httpx.AsyncClient, bot: LiveBot, fake_tg: FakeTelegramClient, session_factory: SessionFactory
) -> None:
    item = await add_workshop(tg_client, bot)
    await Chat(tg_client, bot, fake_tg, 601).press(f"{CAP}:book:{item}")
    record = (await bookings(session_factory, bot))["601"]

    wrong_action = await tg_client.post(action(bot, CAP, record.id, "approve"), headers=ALICE)
    assert wrong_action.status_code == 400 and wrong_action.json()["error"]["code"] == "invalid_action"

    resource = await tg_client.post(action(bot, "workshop", item, "cancel"), headers=ALICE)  # a resource
    assert resource.status_code == 404 and resource.json()["error"]["code"] == "collection_not_found"
    unknown = await tg_client.post(action(bot, "nothing", 1, "cancel"), headers=ALICE)
    assert unknown.status_code == 404

    missing = await tg_client.post(action(bot, CAP, record.id + 9999, "cancel"), headers=ALICE)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "record_not_found"
    assert (await bookings(session_factory, bot))["601"].status == "confirmed"


async def test_no_active_revision_is_409(
    tg_client: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    bot = await make_live_bot(session_factory, None)
    response = await tg_client.post(action(bot, CAP, 1, "cancel"), headers=ALICE)
    assert response.status_code == 409 and response.json()["error"]["code"] == "no_active_revision"


async def test_another_owners_bot_is_a_404(tg_client: httpx.AsyncClient, bot: LiveBot) -> None:
    response = await tg_client.post(action(bot, CAP, 1, "cancel"), headers=BOB)
    assert response.status_code == 404


async def test_sandbox_bookings_cannot_be_reached_through_the_live_admin(
    tg_client: httpx.AsyncClient, bot: LiveBot, session_factory: SessionFactory
) -> None:
    async with session_factory() as session:
        sandbox = await PgStore(session, bot.id, "sandbox", "owner").create_record(
            CAP, {}, status="confirmed", actor_id="ali", item_id=1, now=NOW
        )
        await session.commit()
    response = await tg_client.post(action(bot, CAP, sandbox.id, "cancel"), headers=ALICE)
    assert response.status_code == 404


async def test_request_actions_are_validated_against_the_spec(
    tg_client: httpx.AsyncClient, session_factory: SessionFactory, tg_env: None
) -> None:
    from tests.integration.helpers import REPO

    repair = json.loads((REPO / "examples" / "repair.botspec.json").read_text(encoding="utf-8"))
    bot = await make_live_bot(session_factory, repair, owner_actor_id=str(OWNER_TG_ID))
    async with session_factory() as session:
        record = await PgStore(session, bot.id, "live", str(OWNER_TG_ID)).create_record(
            "repair", {}, status="new", actor_id="601", now=NOW
        )
        await session.commit()
    bad = await tg_client.post(action(bot, "repair", record.id, "explode"), headers=ALICE)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_action"
    missing = await tg_client.post(action(bot, "repair", record.id + 1, "approve"), headers=ALICE)
    assert missing.status_code == 404
    # a valid key is dispatched; the request engine itself arrives with a later package
    valid = await tg_client.post(action(bot, "repair", record.id, "approve"), headers=ALICE)
    assert valid.status_code == 200
    assert set(valid.json()) == {"ok", "outcome", "message"}
