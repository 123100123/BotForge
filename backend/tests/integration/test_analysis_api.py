"""Spreadsheet analysis end to end with the REAL dependencies (session cookie, CSRF, ownership) on the test
database: the profile / run / runs / submissions API (app/api/analysis.py), ``run_for_upload``,
``who_submitted`` and the Overview KPIs. The LLM is a ``FakeLLM`` injected through the
``get_llm_optional`` dependency; files land in a temporary ``UPLOAD_DIR``."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent.llm import FakeLLM
from app.api import analysis as analysis_api
from app.config import get_settings
from app.db.models import AnalysisRunRow, Bot, BotModuleRow
from app.main import create_app
from app.roles.service import set_role
from app.spreadsheets import service
from app.spreadsheets.run import run_for_upload
from app.spreadsheets.submissions import today_tehran
from tests.integration.conftest import MakeBot
from tests.integration.helpers import SessionFactory, signed_in_client
from tests.unit.spreadsheets.test_profile_run import (
    COLUMNS,
    good_draft,
    sales_rows,
    sales_workbook,
)
from tests.unit.spreadsheets.workbooks import make_xlsx

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BOB = {"X-Test-User": "bob"}


class Holder:
    """The LLM the app under test gets (None: no model reachable)."""

    def __init__(self) -> None:
        self.llm: FakeLLM | None = FakeLLM(structured={"analysis_profile": [good_draft()]})


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    yield tmp_path / "uploads"
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def api(
    session_factory: SessionFactory, upload_dir: Path
) -> AsyncIterator[tuple[httpx.AsyncClient, Holder]]:
    holder = Holder()
    app = create_app()
    app.dependency_overrides[analysis_api.get_llm_optional] = lambda: holder.llm
    async with signed_in_client(app, session_factory) as client:
        yield client, holder


async def put(client: httpx.AsyncClient, bot_id: uuid.UUID, data: bytes, *, user: str = "alice") -> str:
    response = await client.put(
        f"/uploads/bots/{bot_id}",
        params={"filename": "sales.xlsx"},
        content=data,
        headers={"X-Test-User": user, "Content-Type": XLSX},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def url(bot_id: uuid.UUID, rest: str = "") -> str:
    return f"/bots/{bot_id}/analysis{rest}"


async def create(
    client: httpx.AsyncClient, bot_id: uuid.UUID, upload_id: str, **extra: Any
) -> dict[str, Any]:
    response = await client.post(url(bot_id, "/profiles"), json={"upload_id": upload_id, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def test_the_api_round_trip(
    api: tuple[httpx.AsyncClient, Holder], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    client, holder = api
    llm = holder.llm
    assert llm is not None
    bot_id, _ = await make_bot()
    first = await put(client, bot_id, sales_workbook())

    profile = await create(client, bot_id, first, daily_report=True)
    assert len(llm.calls) == 1 and llm.calls[0].tier == "strong"  # one strong call for the profile
    assert profile["name"] == "گزارش فروش روزانه" and profile["daily_report"] is True
    assert profile["sheet"] == "Sales" and profile["expected_columns"] == COLUMNS
    assert [m["id"] for m in profile["metrics"]][:2] == ["total_revenue", "row_count"]
    assert profile["runs_count"] == 0
    pid = profile["id"]

    # The same layout again updates the stored profile instead of adding a second one.
    holder.llm = FakeLLM(structured={"analysis_profile": [good_draft(name="گزارش فروش")]})
    again = await create(client, bot_id, first, name="گزارش ویژه")
    assert again["id"] == pid and again["name"] == "گزارش ویژه"
    listed = (await client.get(url(bot_id, "/profiles"))).json()
    assert [p["id"] for p in listed] == [pid]

    run = await client.post(url(bot_id, f"/profiles/{pid}/run"), json={"upload_id": first})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "ok" and body["filename"] == "sales.xlsx" and body["upload_id"] == first
    assert body["narrative"] is None and body["schema_diff"] is None and body["submitted_by"] is None
    metrics = {m["id"]: m for m in body["metrics"]}
    assert metrics["row_count"]["value"] == 30
    assert [a["check_id"] for a in body["anomalies"]] == ["high_discount"]

    # A narrative runs on the fast tier and sees only the results.
    holder.llm = FakeLLM(structured={"analysis_narrative": [{"summary": "خلاصهٔ فروش."}]})
    narrated = await client.post(
        url(bot_id, f"/profiles/{pid}/run"), json={"upload_id": first, "narrative": True}
    )
    assert narrated.json()["narrative"] == "خلاصهٔ فروش." and narrated.json()["metrics"] == body["metrics"]
    assert holder.llm.calls[0].tier == "fast"

    # No model reachable: a run without a narrative still works.
    holder.llm = None
    plain = await client.post(
        url(bot_id, f"/profiles/{pid}/run"), json={"upload_id": first, "narrative": True}
    )
    assert plain.status_code == 200 and plain.json()["narrative"] is None

    runs = (await client.get(url(bot_id, "/runs"), params={"profile_id": pid})).json()
    assert len(runs) == 3 and runs[0]["id"] == plain.json()["id"]  # newest first
    assert (await client.get(url(bot_id, "/runs"), params={"profile_id": str(uuid.uuid4())})).json() == []
    assert (await client.get(url(bot_id, "/profiles"))).json()[0]["runs_count"] == 3

    # A renamed column is a result, not an error.
    renamed = rows_with_renamed_column()
    changed = await put(client, bot_id, renamed)
    result = await client.post(url(bot_id, f"/profiles/{pid}/run"), json={"upload_id": changed})
    assert result.status_code == 200
    assert result.json()["status"] == "schema_changed"
    assert result.json()["schema_diff"] == {"missing": ["Quantity"], "new": ["Qty"]}
    assert result.json()["error"] == "این فایل با پروفایل «گزارش ویژه» مطابقت ندارد"
    assert result.json()["metrics"] == []


def rows_with_renamed_column() -> bytes:
    return make_xlsx(
        {"Sales": sales_rows(columns=["Employee", "Product", "Qty", "Revenue", "Discount", "Date"])}
    )


async def test_run_for_upload_picks_the_matching_profile(
    api: tuple[httpx.AsyncClient, Holder], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    client, _ = api
    bot_id, _ = await make_bot()
    first = await put(client, bot_id, sales_workbook())
    profile = await create(client, bot_id, first)
    same_layout = await put(client, bot_id, sales_workbook(shift=1))
    renamed = await put(client, bot_id, rows_with_renamed_column())
    wider = await put(client, bot_id, make_xlsx({"Sales": [[*r, "x"] for r in sales_rows()]}))

    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        rows = {
            name: await service.get_upload(session, bot_id, uuid.UUID(uid))
            for name, uid in {"same": same_layout, "renamed": renamed, "wider": wider}.items()
        }
        run = await run_for_upload(session, bot, rows["same"], submitted_by="555", llm=None)  # type: ignore[arg-type]
        assert run is not None and run.status == "ok" and run.submitted_by == "555"
        assert str(run.profile_id) == profile["id"] and run.metrics and len(run.anomalies) == 1
        # Same sheet name with every expected column present (an extra column): still this profile.
        extra = await run_for_upload(session, bot, rows["wider"], submitted_by=None)  # type: ignore[arg-type]
        assert extra is not None and extra.status == "ok" and str(extra.profile_id) == profile["id"]
        assert extra.schema_diff is not None and extra.schema_diff.new == ["x"]
        # A renamed column matches nothing: no profile, no run stored.
        before = len((await session.execute(select(AnalysisRunRow))).scalars().all())
        assert await run_for_upload(session, bot, rows["renamed"], submitted_by="555", llm=None) is None  # type: ignore[arg-type]
        after = len((await session.execute(select(AnalysisRunRow))).scalars().all())
        assert after == before
        await session.commit()


async def test_submissions_list_who_sent_the_report(
    api: tuple[httpx.AsyncClient, Holder], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    client, _ = api
    bot_id, _ = await make_bot()
    first = await put(client, bot_id, sales_workbook())
    profile = await create(client, bot_id, first)
    async with session_factory() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        bot.owner_actor_id = "900"
        await set_role(session, bot_id, "live", "900", "manager", display_name="مالک")
        await set_role(session, bot_id, "live", "555", "staff", display_name="سارا")
        await set_role(session, bot_id, "live", "556", "staff", display_name="نیما")
        await set_role(session, bot_id, "live", "557", "manager", display_name="مدیر")
        await set_role(session, bot_id, "live", "558", "customer", display_name="مشتری")
        upload = await service.get_upload(session, bot_id, uuid.UUID(first))
        assert upload is not None
        run = await run_for_upload(session, bot, upload, submitted_by="555")
        assert run is not None
        failed_id = uuid.uuid4()
        session.add(
            AnalysisRunRow(
                id=failed_id,
                bot_id=bot_id,
                profile_id=uuid.UUID(profile["id"]),
                upload_id=None,
                status="failed",
                submitted_by="556",
                error="x",
            )
        )
        await session.commit()

    today = today_tehran().isoformat()
    response = await client.get(url(bot_id, f"/profiles/{profile['id']}/submissions"), params={"date": today})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == today
    assert [(s["actor_id"], s["display_name"], s["run_id"]) for s in body["submitted"]] == [
        ("555", "سارا", str(run.id))
    ]
    assert [(m["actor_id"], m["display_name"]) for m in body["missing"]] == [("557", "مدیر"), ("556", "نیما")]
    assert "900" not in str(body) and "558" not in str(body)  # not the owner, not a customer

    yesterday = await client.get(
        url(bot_id, f"/profiles/{profile['id']}/submissions"), params={"date": "2020-01-01"}
    )
    assert yesterday.json()["submitted"] == [] and len(yesterday.json()["missing"]) == 3
    default_day = await client.get(url(bot_id, f"/profiles/{profile['id']}/submissions"))
    assert default_day.json()["date"] == today
    bad = await client.get(url(bot_id, f"/profiles/{profile['id']}/submissions"), params={"date": "soon"})
    assert bad.status_code == 422


async def test_overview_kpis_follow_the_module_toggle(
    api: tuple[httpx.AsyncClient, Holder], make_bot: MakeBot, session_factory: SessionFactory
) -> None:
    client, _ = api
    bot_id, _ = await make_bot()
    first = await put(client, bot_id, sales_workbook())
    profile = await create(client, bot_id, first)
    for _ in range(2):
        run = await client.post(url(bot_id, f"/profiles/{profile['id']}/run"), json={"upload_id": first})
        assert run.status_code == 200

    def kpis(body: dict[str, Any]) -> dict[str, float]:
        return {k["id"]: k["value"] for k in body["kpis"] if k["id"] in ("reports_uploaded", "anomaly_count")}

    overview = await client.get(f"/bots/{bot_id}/reports/overview")
    assert overview.status_code == 200, overview.text
    assert kpis(overview.json()) == {}  # the module is off until the owner enables it

    async with session_factory() as session:
        session.add(BotModuleRow(bot_id=bot_id, module="spreadsheet_intelligence", enabled=True))
        await session.commit()
    on = await client.get(f"/bots/{bot_id}/reports/overview")
    assert kpis(on.json()) == {"reports_uploaded": 2, "anomaly_count": 2}

    async with session_factory() as session:
        row = await session.get(BotModuleRow, (bot_id, "spreadsheet_intelligence"))
        assert row is not None
        row.enabled = False
        await session.commit()
    off = await client.get(f"/bots/{bot_id}/reports/overview")
    assert kpis(off.json()) == {}  # the toggle governs the KPIs, not web analysis
    still = await client.post(url(bot_id, f"/profiles/{profile['id']}/run"), json={"upload_id": first})
    assert still.status_code == 200


async def test_patch_a_profile(api: tuple[httpx.AsyncClient, Holder], make_bot: MakeBot) -> None:
    client, _ = api
    bot_id, _ = await make_bot()
    first = await put(client, bot_id, sales_workbook())
    profile = await create(client, bot_id, first)
    patch = await client.patch(
        url(bot_id, f"/profiles/{profile['id']}"),
        json={
            "name": "  گزارش   جدید ",
            "daily_report": True,
            "metrics": [
                {"id": "avg_discount", "label": "میانگین تخفیف", "measure": "avg", "field": "discount"},
                {"id": "bad", "label": "نادرست", "measure": "sum", "field": "Employee"},
                {"id": "ghost", "label": "ناموجود", "measure": "sum", "field": "Cost"},
            ],
        },
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["name"] == "گزارش جدید" and body["daily_report"] is True
    assert [(m["id"], m["field"]) for m in body["metrics"]] == [("avg_discount", "Discount")]
    assert [c["id"] for c in body["checks"]] == ["high_discount"]  # untouched
    assert body["expected_columns"] == COLUMNS

    only_name = await client.patch(url(bot_id, f"/profiles/{profile['id']}"), json={"name": "فقط نام"})
    assert only_name.json()["name"] == "فقط نام" and len(only_name.json()["metrics"]) == 1
    missing = await client.patch(url(bot_id, f"/profiles/{uuid.uuid4()}"), json={"name": "x"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "profile_not_found"


async def test_errors_and_ownership(api: tuple[httpx.AsyncClient, Holder], make_bot: MakeBot) -> None:
    client, holder = api
    bot_id, _ = await make_bot()
    other_bot, _ = await make_bot("bob")
    first = await put(client, bot_id, sales_workbook())

    unknown = await client.post(url(bot_id, "/profiles"), json={"upload_id": str(uuid.uuid4())})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "upload_not_found"
    foreign_upload = await client.post(url(other_bot, "/profiles"), json={"upload_id": first}, headers=BOB)
    assert foreign_upload.status_code == 404  # another bot's upload is like a missing one

    holder.llm = None  # no API key
    down = await client.post(url(bot_id, "/profiles"), json={"upload_id": first})
    assert down.status_code == 503 and down.json()["error"]["code"] == "llm_unavailable"
    assert down.json()["error"]["message"]

    holder.llm = FakeLLM(structured={"analysis_profile": [RuntimeError("provider down")]})
    failing = await client.post(url(bot_id, "/profiles"), json={"upload_id": first})
    assert failing.status_code == 503 and failing.json()["error"]["code"] == "llm_unavailable"
    assert (await client.get(url(bot_id, "/profiles"))).json() == []  # nothing stored

    holder.llm = FakeLLM(structured={"analysis_profile": [good_draft()]})
    profile = await create(client, bot_id, first)
    pid = profile["id"]
    for method, rest, payload in (
        ("GET", "/profiles", None),
        ("GET", "/runs", None),
        ("PATCH", f"/profiles/{pid}", {"name": "x"}),
        ("POST", f"/profiles/{pid}/run", {"upload_id": first}),
        ("GET", f"/profiles/{pid}/submissions", None),
    ):
        stolen = await client.request(method, url(bot_id, rest), json=payload, headers=BOB)
        assert stolen.status_code == 404, (method, rest)  # bob does not own this bot
    own_bot_foreign_profile = await client.post(
        url(other_bot, f"/profiles/{pid}/run"), json={"upload_id": first}, headers=BOB
    )
    assert own_bot_foreign_profile.status_code == 404  # alice's profile is not found under bob's bot
    anonymous = await client.get(url(bot_id, "/profiles"), headers={"X-Test-User": "anonymous"})
    assert anonymous.status_code == 401
