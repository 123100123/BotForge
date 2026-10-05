"""Spreadsheet uploads with the REAL dependencies (session cookie, CSRF, ownership) on the test database:
``PUT /uploads/bots/{bot_id}``, ``GET /bots/{bot_id}/uploads[/{upload_id}]`` (app/api/uploads.py) and
the service underneath (app/spreadsheets/service.py). Files land in a temporary ``UPLOAD_DIR``.

Some requests are driven straight through ASGI so the test can count how much of the body the
application pulled: a refused caller must not make the server read (and buffer) the upload.
"""

import hashlib
import stat
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api import uploads as uploads_api
from app.config import get_settings
from app.db.models import Bot, UploadedFileRow
from app.main import create_app
from app.security.body_limit import EXEMPT_PREFIXES, MAX_BODY_BYTES
from app.security.csrf import CSRF_HEADER
from app.security.sessions import SESSION_COOKIE
from app.spreadsheets import service
from app.spreadsheets.errors import MACRO_MESSAGE, UNSUPPORTED_MESSAGE, StoredFileMissing
from app.spreadsheets.storage import get_storage
from tests.integration.conftest import MakeBot
from tests.integration.helpers import CookieAuth, SessionFactory, use_test_database, user_id
from tests.unit.spreadsheets.workbooks import make_xlsx, rewrite_xlsx

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TOO_LARGE = {"code": "upload_too_large", "message": "حجم فایل بیش از حد مجاز است (حداکثر ۵ مگابایت)."}
CHUNK = 64 * 1024


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_DIR", str(root))
    monkeypatch.delenv("UPLOAD_MAX_BYTES", raising=False)  # the default cap: 5 MiB
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()
    assert uploads_api.IN_FLIGHT.count == 0  # every request released its slot


def workbook(*, amounts: tuple[int, ...] = (10, 20, 30), first_column: str = "name") -> bytes:
    sales = [[first_column, "amount", "date", "paid"]]
    sales += [[f"c{i}", a, datetime(2026, 10, i + 1), i % 2 == 0] for i, a in enumerate(amounts)]
    return make_xlsx(
        {
            "Sales": sales,
            "Stock": [["sku", "qty"], ["A-1", "۱۲"], ["A-2", "۳"]],
            "Staff": [["نام", "تلفن"], ["علی", "09121234567"]],
        }
    )


async def put(
    client: httpx.AsyncClient,
    bot_id: uuid.UUID,
    content: Any,
    *,
    filename: str = "report.xlsx",
    user: str = "alice",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.put(
        f"/uploads/bots/{bot_id}",
        params={"filename": filename},
        content=content,
        headers={"X-Test-User": user, "Content-Type": XLSX, **(headers or {})},
    )


def stored_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


async def upload_rows(session_factory: SessionFactory, *bot_ids: uuid.UUID) -> int:
    """How many upload rows these bots have (the test database is shared by the whole session)."""
    stmt = select(func.count()).select_from(UploadedFileRow).where(UploadedFileRow.bot_id.in_(bot_ids))
    async with session_factory() as session:
        return (await session.execute(stmt)).scalar_one()


# --- Happy path ----------------------------------------------------------------------------------


async def test_upload_a_three_sheet_workbook(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot(active=False)
    data = workbook()
    response = await put(client, bot_id, data, filename="../../گزارش مهر.xlsx")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "گزارش مهر.xlsx"  # a label: the path part is gone
    assert (body["size"], body["content_type"]) == (len(data), XLSX)
    assert body["sha256"] == hashlib.sha256(data).hexdigest()

    inspection = body["inspection"]
    types = {s["name"]: {c["name"]: c["inferred_type"] for c in s["columns"]} for s in inspection["sheets"]}
    assert types == {
        "Sales": {"name": "text", "amount": "integer", "date": "datetime", "paid": "boolean"},
        "Stock": {"sku": "text", "qty": "integer"},  # Persian digits are numbers
        "Staff": {"نام": "text", "تلفن": "text"},  # a leading zero keeps a phone number text
    }
    assert len(inspection["signature"]) == 40 and inspection["row_limit_hit"] is False
    assert inspection["sheets"][0]["sample_rows"][0] == {
        "name": "c0", "amount": 10, "date": "2026-10-01", "paid": True,
    }  # fmt: skip

    [stored] = stored_files(upload_dir)  # server-generated key: <bot id>/<uuid4 hex>.xlsx
    assert stored.parent == upload_dir.resolve() / str(bot_id)
    assert stored.suffix == ".xlsx" and len(stored.stem) == 32
    assert stored.read_bytes() == data
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert stat.S_IMODE(stored.parent.stat().st_mode) == 0o700

    async with session_factory() as session:
        row = await session.get(UploadedFileRow, uuid.UUID(body["id"]))
    assert row is not None
    assert (row.bot_id, row.source, row.storage_key) == (bot_id, "web", f"{bot_id}/{stored.name}")
    assert row.uploaded_by == str(await user_id(session_factory, "alice"))

    listed = await client.get(f"/bots/{bot_id}/uploads")
    assert listed.status_code == 200 and [u["id"] for u in listed.json()] == [body["id"]]
    one = await client.get(f"/bots/{bot_id}/uploads/{body['id']}")
    assert one.status_code == 200
    assert {**one.json(), "created_at": None} == {**body, "created_at": None}
    assert datetime.fromisoformat(one.json()["created_at"]) == datetime.fromisoformat(body["created_at"])


async def test_the_signature_is_stable_for_one_layout(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path
) -> None:
    bot_id, _ = await make_bot(active=False)
    first = (await put(client, bot_id, workbook())).json()
    second = (await put(client, bot_id, workbook(amounts=(5, 7)))).json()
    renamed = (await put(client, bot_id, workbook(first_column="customer"))).json()
    assert first["inspection"]["signature"] == second["inspection"]["signature"]
    assert renamed["inspection"]["signature"] != first["inspection"]["signature"]
    listed = (await client.get(f"/bots/{bot_id}/uploads")).json()
    assert [u["id"] for u in listed] == [renamed["id"], second["id"], first["id"]]  # newest first
    assert len(stored_files(upload_dir)) == 3


async def test_a_file_over_the_global_body_limit_is_accepted(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path
) -> None:
    bot_id, _ = await make_bot(active=False)
    data = ("sku,qty,note\n" + "".join(f"S-{i},{i},{'x' * 40}\n" for i in range(30_000))).encode()
    assert MAX_BODY_BYTES < len(data) < 5 * 1024 * 1024
    response = await put(client, bot_id, data, filename="stock.csv", headers={"Content-Type": "text/csv"})
    assert response.status_code == 201, response.text
    assert response.json()["content_type"] == "text/csv"
    assert response.json()["inspection"]["sheets"][0]["rows"] == 30_000


async def test_the_content_type_header_is_advisory(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path
) -> None:
    bot_id, _ = await make_bot(active=False)
    csv_as_png = await put(
        client, bot_id, b"a,b\n1,2\n", filename="x.csv", headers={"Content-Type": "image/png"}
    )
    assert csv_as_png.status_code == 201 and csv_as_png.json()["content_type"] == "text/csv"
    png_as_csv = await put(client, bot_id, PNG, filename="x.csv", headers={"Content-Type": "text/csv"})
    assert png_as_csv.status_code == 415


async def test_a_hostile_file_name_cannot_choose_the_path(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path, tmp_path: Path
) -> None:
    bot_id, _ = await make_bot(active=False)
    response = await put(client, bot_id, b"a\n1\n", filename="../../../../etc/cron.d/evil.csv")
    assert response.status_code == 201 and response.json()["filename"] == "evil.csv"
    [stored] = stored_files(upload_dir)
    assert stored.parent == upload_dir.resolve() / str(bot_id) and stored.name != "evil.csv"
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [stored]


# --- Refusals ------------------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"


async def test_an_oversized_body_is_refused(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot(active=False)
    six_megabytes = b"a,b\n" + b"1,2\n" * (6 * 1024 * 1024 // 4)
    declared = await put(client, bot_id, six_megabytes, filename="big.csv")
    assert declared.status_code == 413 and declared.json()["error"] == TOO_LARGE

    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: the stream is counted
        for _ in range(96):
            yield b"1,2\n" * (CHUNK // 4)

    streamed = await put(client, bot_id, chunks(), filename="big.csv")
    assert streamed.status_code == 413 and streamed.json()["error"] == TOO_LARGE
    assert stored_files(upload_dir) == [] and await upload_rows(session_factory, bot_id) == 0


@pytest.mark.parametrize(
    ("payload", "filename", "message"),
    [
        (PNG, "photo.png", UNSUPPORTED_MESSAGE),
        (
            rewrite_xlsx(workbook(), {"xl/vbaProject.bin": b"\xd0\xcf\x11\xe0vba"}),
            "report.xlsx",
            MACRO_MESSAGE,
        ),
        (workbook(), "report.xlsm", MACRO_MESSAGE),
    ],
    ids=["png", "vba-part", "xlsm-name"],
)
async def test_unsupported_files_are_refused(
    client: httpx.AsyncClient,
    make_bot: MakeBot,
    upload_dir: Path,
    session_factory: SessionFactory,
    payload: bytes,
    filename: str,
    message: str,
) -> None:
    bot_id, _ = await make_bot(active=False)
    response = await put(client, bot_id, payload, filename=filename)
    assert response.status_code == 415
    assert response.json()["error"] == {"code": "unsupported_file_type", "message": message}
    assert stored_files(upload_dir) == [] and await upload_rows(session_factory, bot_id) == 0


async def test_an_empty_body_is_an_empty_workbook(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path
) -> None:
    bot_id, _ = await make_bot(active=False)
    response = await put(client, bot_id, b"", filename="empty.csv")
    assert response.status_code == 422 and response.json()["error"]["code"] == "empty_workbook"


async def test_another_owners_bot_is_a_404(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot("bob", active=False)
    response = await put(client, bot_id, workbook())
    assert response.status_code == 404 and response.json()["error"]["code"] == "bot_not_found"
    assert (await client.get(f"/bots/{bot_id}/uploads")).status_code == 404
    assert stored_files(upload_dir) == [] and await upload_rows(session_factory, bot_id) == 0


async def test_an_upload_is_only_reachable_through_its_own_bot(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path
) -> None:
    first, _ = await make_bot(active=False)
    second, _ = await make_bot(active=False)
    upload = (await put(client, first, workbook())).json()
    other_bot = await client.get(f"/bots/{second}/uploads/{upload['id']}")
    assert other_bot.status_code == 404 and other_bot.json()["error"]["code"] == "upload_not_found"
    assert (await client.get(f"/bots/{second}/uploads")).json() == []
    assert (await client.get(f"/bots/{first}/uploads/{uuid.uuid4()}")).status_code == 404
    bob = await client.get(f"/bots/{first}/uploads/{upload['id']}", headers={"X-Test-User": "bob"})
    assert bob.status_code == 404 and bob.json()["error"]["code"] == "bot_not_found"


async def test_a_missing_csrf_header_is_refused(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot(active=False)
    response = await put(client, bot_id, workbook(), headers={CSRF_HEADER: "0"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_failed"
    assert stored_files(upload_dir) == [] and await upload_rows(session_factory, bot_id) == 0


async def test_uploads_in_flight_are_capped(
    client: httpx.AsyncClient, make_bot: MakeBot, upload_dir: Path
) -> None:
    bot_id, _ = await make_bot(active=False)
    uploads_api.IN_FLIGHT.count = uploads_api.MAX_UPLOADS_IN_FLIGHT  # as if that many were running
    try:
        response = await put(client, bot_id, workbook())
        assert uploads_api.IN_FLIGHT.count == uploads_api.MAX_UPLOADS_IN_FLIGHT  # a refusal takes no slot
    finally:
        uploads_api.IN_FLIGHT.count = 0
    assert response.status_code == 503 and response.json()["error"]["code"] == "uploads_busy"
    assert response.headers["retry-after"] == "5"


async def test_a_storage_failure_is_a_structured_error(
    client: httpx.AsyncClient,
    make_bot: MakeBot,
    upload_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
) -> None:
    bot_id, _ = await make_bot(active=False)
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    monkeypatch.setenv("UPLOAD_DIR", str(blocker / "uploads"))  # cannot be created
    get_settings.cache_clear()
    response = await put(client, bot_id, workbook())
    assert response.status_code == 503 and response.json()["error"]["code"] == "storage_unavailable"
    assert await upload_rows(session_factory, bot_id) == 0


# --- Nothing is read before the checks (raw ASGI) ------------------------------------------------


async def raw_put(
    app: Any, path: str, headers: dict[str, str], total: int, *, declare_length: bool
) -> tuple[int, int, bytes]:
    """PUT ``total`` bytes straight through ASGI. Returns (status, bytes pulled by the app, body)."""
    remaining, pulled = total, 0
    status: list[int] = []
    body = bytearray()

    async def receive() -> dict[str, Any]:
        nonlocal remaining, pulled
        if remaining <= 0:
            return {"type": "http.disconnect"}
        size = min(CHUNK, remaining)
        remaining -= size
        pulled += size
        return {"type": "http.request", "body": b"x" * size, "more_body": remaining > 0}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status.append(message["status"])
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    raw_headers = [(b"host", b"test"), *((k.lower().encode(), v.encode()) for k, v in headers.items())]
    if declare_length:
        raw_headers.append((b"content-length", str(total).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"filename=data.csv",
        "headers": raw_headers,
        "client": ("203.0.113.9", 4000),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    return status[0], pulled, bytes(body)


async def test_refused_callers_never_get_the_body_read(
    make_bot: MakeBot, upload_dir: Path, session_factory: SessionFactory
) -> None:
    app = create_app()
    use_test_database(app, session_factory)
    cookie = f"{SESSION_COOKIE}={await CookieAuth(session_factory).token('alice')}"
    own, _ = await make_bot(active=False)
    foreign, _ = await make_bot("bob", active=False)
    huge = 50 * 1024 * 1024
    cases = [
        ("anonymous", own, {}, 401),
        ("no csrf header", own, {"Cookie": cookie}, 403),
        ("foreign origin", own, {"Cookie": cookie, CSRF_HEADER: "1", "Origin": "https://evil.example"}, 403),
        ("someone else's bot", foreign, {"Cookie": cookie, CSRF_HEADER: "1"}, 404),
    ]
    for label, bot_id, headers, expected in cases:
        for declare_length in (True, False):
            status, pulled, _ = await raw_put(
                app, f"/uploads/bots/{bot_id}", headers, huge, declare_length=declare_length
            )
            assert (status, pulled) == (expected, 0), (label, declare_length)

    owner = {"Cookie": cookie, CSRF_HEADER: "1"}
    status, pulled, body = await raw_put(app, f"/uploads/bots/{own}", owner, huge, declare_length=True)
    assert (status, pulled) == (413, 0) and b"upload_too_large" in body  # declared too large: unread
    status, pulled, body = await raw_put(app, f"/uploads/bots/{own}", owner, huge, declare_length=False)
    assert status == 413 and b"upload_too_large" in body
    assert 5 * 1024 * 1024 < pulled <= 5 * 1024 * 1024 + CHUNK  # cut off just past the cap
    assert stored_files(upload_dir) == [] and await upload_rows(session_factory, own, foreign) == 0


def test_only_the_raw_upload_route_lives_under_the_exempt_prefix() -> None:
    """``/uploads/`` skips the global body limit, so a JSON route added there would be parsed before
    authentication with no cap at all. Guard: the raw-body PUT is the only route under it."""
    assert "/uploads/" in EXEMPT_PREFIXES
    paths = create_app().openapi()["paths"]
    under = {path: sorted(ops) for path, ops in paths.items() if path.startswith("/uploads")}
    assert under == {"/uploads/bots/{bot_id}": ["put"]}


# --- Service --------------------------------------------------------------------------------------


async def test_load_rows_reads_a_stored_upload_back(
    make_bot: MakeBot, upload_dir: Path, session_factory: SessionFactory
) -> None:
    bot_id, _ = await make_bot(active=False)
    settings = get_settings()
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        upload = await service.ingest(
            session, bot, workbook(), "r.xlsx", source="telegram", uploaded_by="12345", settings=settings
        )
        await session.commit()
        row = await service.get_upload(session, bot_id, upload.id)
    assert row is not None and (row.source, row.uploaded_by) == ("telegram", "12345")
    storage = get_storage(settings)
    headers, rows = await service.load_rows(storage, row, sheet="Stock")
    assert (headers, rows) == (["sku", "qty"], [["A-1", 12], ["A-2", 3]])
    assert (await service.load_rows(storage, row))[0] == ["name", "amount", "date", "paid"]
    await storage.delete(row.storage_key)
    with pytest.raises(StoredFileMissing):
        await service.load_rows(storage, row)


async def test_a_failed_insert_removes_the_stored_file(
    upload_dir: Path, session_factory: SessionFactory
) -> None:
    phantom = Bot(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="missing")  # not in the database
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await service.ingest(
                session, phantom, b"a\n1\n", "x.csv", source="web", uploaded_by=None, settings=get_settings()
            )
        await session.rollback()
    assert stored_files(upload_dir) == []
