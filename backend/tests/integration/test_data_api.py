"""Data admin endpoints. Needs TEST_DATABASE_URL."""

import httpx

from app.runtime.pg_store import PgStore
from tests.integration.conftest import MakeBot
from tests.integration.helpers import NOW, SessionFactory

ALICE = {"X-Test-User": "alice"}
BOB = {"X-Test-User": "bob"}

WORKSHOP = {
    "title": "کارگاه عکاسی",
    "description": "مقدماتی",
    "teacher": "سارا",
    "starts_at": "2026-11-01T10:00:00+03:30",
    "price": "۱۲۰۰۰",
}


async def create(client: httpx.AsyncClient, bot_id: object, data: dict | None = None) -> dict:
    response = await client.post(
        f"/bots/{bot_id}/data/workshop", json={"data": data or WORKSHOP}, headers=ALICE
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_collections_describe_the_active_spec(client: httpx.AsyncClient, make_bot: MakeBot) -> None:
    bot_id, _ = await make_bot("alice")
    response = await client.get(f"/bots/{bot_id}/data", headers=ALICE)
    assert response.status_code == 200
    by_key = {c["key"]: c for c in response.json()["collections"]}
    assert set(by_key) == {"workshop", "book_workshop"}  # info capability has no records

    workshop = by_key["workshop"]
    assert workshop["kind"] == "resource" and workshop["writable"] is True
    assert workshop["title_field"] == "title"
    assert [f["key"] for f in workshop["fields"]] == ["title", "description", "teacher", "starts_at", "price"]
    assert {"key": "starts_at", "label": workshop["fields"][3]["label"]}.items() <= workshop["fields"][
        3
    ].items()

    booking = by_key["book_workshop"]
    assert booking["kind"] == "booking" and booking["writable"] is False
    assert booking["resource"] == "workshop"
    assert [c["key"] for c in booking["system_columns"]] == ["actor_id", "item_id", "status", "created_at"]
    assert all(c["label"] for c in booking["system_columns"])
    assert booking["fields"] == []  # the golden booking has no form_fields


async def test_no_active_revision_is_409_with_persian_message(
    client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot("alice", active=False)
    for method, path in (
        ("GET", f"/bots/{bot_id}/data"),
        ("GET", f"/bots/{bot_id}/data/workshop"),
        ("POST", f"/bots/{bot_id}/data/workshop"),
    ):
        response = await client.request(
            method, path, headers=ALICE, **({"json": {"data": {}}} if method == "POST" else {})
        )
        assert response.status_code == 409, path
        error = response.json()["error"]
        assert error["code"] == "no_active_revision"
        assert "نسخه" in error["message"]


async def test_create_list_update_delete_resource_record(
    client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot("alice")
    first = await create(client, bot_id)
    assert first["collection"] == "workshop"
    assert first["data"]["price"] == 12000  # Persian digits normalized
    assert first["data"]["starts_at"] == "2026-11-01T06:30:00+00:00"  # stored as UTC
    second = await create(client, bot_id, {**WORKSHOP, "title": "کارگاه سفال"})
    assert second["id"] > first["id"]

    listed = (await client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)).json()
    assert listed["total"] == 2
    assert [r["id"] for r in listed["items"]] == [second["id"], first["id"]]  # newest first
    page = (await client.get(f"/bots/{bot_id}/data/workshop?limit=1&offset=1", headers=ALICE)).json()
    assert page["total"] == 2 and [r["id"] for r in page["items"]] == [first["id"]]
    assert (await client.get(f"/bots/{bot_id}/data/workshop?limit=0", headers=ALICE)).status_code == 422

    patched = await client.patch(
        f"/bots/{bot_id}/data/workshop/{first['id']}",
        json={"data": {"teacher": "علی", "price": None}},
        headers=ALICE,
    )
    assert patched.status_code == 200, patched.text
    data = patched.json()["data"]
    assert data["teacher"] == "علی" and data["price"] is None  # optional field cleared
    assert data["title"] == "کارگاه عکاسی"  # untouched fields keep their value
    assert patched.json()["updated_at"] >= first["updated_at"]

    deleted = await client.delete(f"/bots/{bot_id}/data/workshop/{first['id']}", headers=ALICE)
    assert deleted.status_code == 204
    assert (await client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)).json()["total"] == 1
    missing = await client.delete(f"/bots/{bot_id}/data/workshop/{first['id']}", headers=ALICE)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "record_not_found"


async def test_validation_errors_are_400_with_persian_field_errors(
    client: httpx.AsyncClient, make_bot: MakeBot
) -> None:
    bot_id, _ = await make_bot("alice")
    response = await client.post(
        f"/bots/{bot_id}/data/workshop", json={"data": {"title": "فقط عنوان", "price": "abc"}}, headers=ALICE
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_record"
    details = error["details"]
    assert any("«" in e and "الزامی" in e for e in details)  # missing required fields
    assert any("عدد" in e for e in details)  # price
    assert all(e in error["message"] for e in details)
    naive = await client.post(
        f"/bots/{bot_id}/data/workshop",
        json={"data": {**WORKSHOP, "starts_at": "2026-11-01T10:00:00"}},
        headers=ALICE,
    )
    assert naive.status_code == 400

    assert (await client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)).json()["total"] == 0

    record = await create(client, bot_id)
    bad_patch = await client.patch(
        f"/bots/{bot_id}/data/workshop/{record['id']}", json={"data": {"title": ""}}, headers=ALICE
    )
    assert bad_patch.status_code == 400 and bad_patch.json()["error"]["code"] == "invalid_record"
    unchanged = (await client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)).json()["items"][0]
    assert unchanged["data"]["title"] == "کارگاه عکاسی"

    assert (await client.post(f"/bots/{bot_id}/data/workshop", json={}, headers=ALICE)).status_code == 422
    assert (
        await client.patch(
            f"/bots/{bot_id}/data/workshop/987654", json={"data": {"title": "x"}}, headers=ALICE
        )
    ).status_code == 404


async def test_delete_refused_while_active_bookings_exist(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice")
    item = await create(client, bot_id)
    other_item = await create(client, bot_id, {**WORKSHOP, "title": "دیگر"})

    async def add_booking(status: str, item_id: int, env: str = "live") -> int:
        async with session_factory() as session:
            rec = await PgStore(session, bot_id, env).create_record(  # type: ignore[arg-type]
                "book_workshop", {}, status=status, actor_id="ali", item_id=item_id, now=NOW
            )
            await session.commit()
            return rec.id

    await add_booking("cancelled", item["id"])
    await add_booking("confirmed", other_item["id"])
    await add_booking("confirmed", item["id"], env="sandbox")  # sandbox bookings are irrelevant

    assert (
        await client.delete(f"/bots/{bot_id}/data/workshop/{other_item['id']}", headers=ALICE)
    ).status_code == 409

    async def refused() -> None:
        response = await client.delete(f"/bots/{bot_id}/data/workshop/{item['id']}", headers=ALICE)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "record_has_active_bookings"
        assert "رزرو" in response.json()["error"]["message"]

    waitlisted = await add_booking("waitlisted", item["id"])
    await refused()
    confirmed = await add_booking("confirmed", item["id"])
    await refused()
    assert (await client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)).json()["total"] == 2

    async with session_factory() as session:  # cancel everything that is active
        store = PgStore(session, bot_id, "live")
        for rid in (waitlisted, confirmed):
            await store.update_record("book_workshop", rid, status="cancelled", now=NOW)
        await session.commit()
    assert (
        await client.delete(f"/bots/{bot_id}/data/workshop/{item['id']}", headers=ALICE)
    ).status_code == 204


async def test_booking_collections_are_read_only_and_unknown_collections_404(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice")
    item = await create(client, bot_id)
    async with session_factory() as session:
        rec = await PgStore(session, bot_id, "live").create_record(
            "book_workshop", {}, status="confirmed", actor_id="ali", item_id=item["id"], now=NOW
        )
        await session.commit()

    listed = (await client.get(f"/bots/{bot_id}/data/book_workshop", headers=ALICE)).json()
    assert listed["total"] == 1 and listed["items"][0]["status"] == "confirmed"
    assert listed["items"][0]["item_id"] == item["id"]

    for method, path in (
        ("POST", f"/bots/{bot_id}/data/book_workshop"),
        ("PATCH", f"/bots/{bot_id}/data/book_workshop/{rec.id}"),
        ("DELETE", f"/bots/{bot_id}/data/book_workshop/{rec.id}"),
    ):
        response = await client.request(
            method, path, headers=ALICE, **({} if method == "DELETE" else {"json": {"data": {}}})
        )
        assert response.status_code == 405, (method, response.text)
        assert response.json()["error"]["code"] == "read_only_collection"

    for method, path in (
        ("GET", f"/bots/{bot_id}/data/nope"),
        ("POST", f"/bots/{bot_id}/data/nope"),
        ("PATCH", f"/bots/{bot_id}/data/nope/1"),
        ("DELETE", f"/bots/{bot_id}/data/nope/1"),
        ("GET", f"/bots/{bot_id}/data/info"),  # a capability without records is not a collection
    ):
        response = await client.request(
            method, path, headers=ALICE, **({"json": {"data": {}}} if method in ("POST", "PATCH") else {})
        )
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == "collection_not_found"


async def test_other_users_and_sandbox_data_are_invisible(
    client: httpx.AsyncClient, make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("alice")
    await create(client, bot_id)
    async with session_factory() as session:
        await PgStore(session, bot_id, "sandbox").create_record("workshop", {"title": "sandbox"}, now=NOW)
        await session.commit()

    listed = (await client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)).json()
    assert listed["total"] == 1 and listed["items"][0]["data"]["title"] == "کارگاه عکاسی"

    for method, path in (
        ("GET", f"/bots/{bot_id}/data/workshop"),
        ("POST", f"/bots/{bot_id}/data/workshop"),
        ("DELETE", f"/bots/{bot_id}/data/workshop/{listed['items'][0]['id']}"),
    ):
        response = await client.request(
            method, path, headers=BOB, **({"json": {"data": WORKSHOP}} if method == "POST" else {})
        )
        assert response.status_code == 404, method
    assert (await client.get(f"/bots/{bot_id}/data/workshop", headers=ALICE)).json()["total"] == 1
