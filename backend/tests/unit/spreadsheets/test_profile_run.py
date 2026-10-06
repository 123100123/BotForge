"""Analysis profiles and deterministic runs (app/spreadsheets/{profile,run,narrative}.py) against real xlsx
files, a scripted FakeLLM and a stand-in session (no database; the database paths are in
tests/integration/test_analysis_api.py)."""

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agent.llm import FakeLLM, LLMError
from app.config import get_settings
from app.db.models import AnalysisProfileRow, AnalysisRunRow, Bot, UploadedFileRow
from app.schemas.business import AnalysisMetricSpec, SchemaDiff, SheetProfile
from app.spreadsheets import profile as profiles
from app.spreadsheets import run as runs
from app.spreadsheets import service
from app.spreadsheets.inspect import column_signature
from app.spreadsheets.profile import ProfileDraft, ProfileError
from app.spreadsheets.storage import LocalFileStorage
from tests.unit.spreadsheets.workbooks import make_xlsx

EMPLOYEES = ["علی", "مریم", "رضا", "سارا", "نیما"]
PRODUCTS = ["چای", "قهوه", "شکر"]
COLUMNS = ["Employee", "Product", "Quantity", "Revenue", "Discount", "Date"]
PLANTED_ROW = 17  # zero-based; its discount is the outlier


def sales_rows(*, shift: int = 0, columns: list[str] | None = None) -> list[list[Any]]:
    rows: list[list[Any]] = [list(columns or COLUMNS)]
    for i in range(30):
        qty = 1 + (i + shift) % 4
        discount = 90 if i == PLANTED_ROW else 2 + (i + shift) % 3
        rows.append(
            [
                EMPLOYEES[i % 5],
                PRODUCTS[(i + shift) % 3],
                qty,
                qty * 1000 * (1 + i % 3),
                discount,
                datetime(2026, 10, 1 + (i % 10)),
            ]
        )
    return rows


def sales_workbook(**kwargs: Any) -> bytes:
    return make_xlsx({"Sales": sales_rows(**kwargs)})


class StubSession:
    """The few AsyncSession calls the code under test makes, kept in memory."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if getattr(row, "created_at", None) is None:
                row.created_at = datetime.now(UTC)
            if isinstance(row, AnalysisProfileRow) and row.daily_report is None:
                row.daily_report = False

    async def refresh(self, row: Any) -> None:
        return None

    async def execute(self, stmt: Any) -> "StubResult":
        return StubResult([r for r in self.added if isinstance(r, AnalysisProfileRow)])


class StubResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalar_one_or_none(self) -> None:
        return None  # no stored profile of this layout yet

    def scalar_one(self) -> int:
        return 0  # no runs yet


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(str(tmp_path / "uploads"))


@pytest.fixture
def bot() -> Bot:
    return Bot(id=uuid.uuid4(), name="ربات")


async def upload(session: StubSession, bot: Bot, storage: LocalFileStorage, data: bytes) -> UploadedFileRow:
    await service.ingest(
        session,  # type: ignore[arg-type]
        bot,
        data,
        "sales.xlsx",
        source="web",
        uploaded_by=None,
        settings=get_settings(),
        storage=storage,
    )
    return [r for r in session.added if isinstance(r, UploadedFileRow)][-1]


def sheet_of(row: UploadedFileRow) -> SheetProfile:
    return service.to_upload_out(row).inspection.sheets[0]


def good_draft(**overrides: Any) -> ProfileDraft:
    data: dict[str, Any] = {
        "name": "گزارش فروش روزانه",
        "sheet": "Sales",
        "expected_columns": COLUMNS,
        "metrics": [
            {"id": "total_revenue", "label": "کل فروش", "measure": "sum", "field": "Revenue"},
            {"id": "row_count", "label": "تعداد فروش", "measure": "count"},
            {
                "id": "top_products",
                "label": "پرفروش‌ترین کالاها",
                "measure": "sum",
                "field": "Revenue",
                "group_by": "Product",
                "group_kind": "field",
                "top_n": 2,
            },
            {
                "id": "by_employee",
                "label": "فروش هر فروشنده",
                "measure": "sum",
                "field": "Revenue",
                "group_by": "Employee",
                "group_kind": "field",
            },
            {
                "id": "daily",
                "label": "فروش روزانه",
                "measure": "sum",
                "field": "Revenue",
                "group_by": "Date",
                "group_kind": "day",
            },
        ],
        "checks": [
            {"id": "high_discount", "label": "تخفیف بالا", "kind": "outlier_high", "field": "Discount"},
        ],
        "time_column": "Date",
        "entity_column": "Employee",
    }
    data.update(overrides)
    return ProfileDraft.model_validate(data)


async def make_profile(
    session: StubSession, bot: Bot, storage: LocalFileStorage, draft: ProfileDraft | None = None
) -> tuple[Any, UploadedFileRow, FakeLLM]:
    first = await upload(session, bot, storage, sales_workbook())
    llm = FakeLLM(structured={"analysis_profile": [draft or good_draft()]})
    out = await profiles.create_profile(
        session,  # type: ignore[arg-type]
        bot,
        llm,
        first,
        name=None,
        daily_report=True,
    )
    return out, first, llm


async def test_a_profile_takes_one_strong_call_and_sees_only_the_sample(
    bot: Bot, storage: LocalFileStorage
) -> None:
    session = StubSession()
    out, first, llm = await make_profile(session, bot, storage)

    [call] = llm.calls
    assert (call.task, call.tier, call.kind) == ("analysis_profile", "strong", "structured")
    sent = json.loads(call.messages[0]["content"])
    [sheet] = sent["sheets"]
    assert sheet["name"] == "Sales" and sheet["rows"] == 30
    assert len(sheet["sample_rows"]) == 10  # never the 30 rows of the file
    assert {c["name"]: c["type"] for c in sheet["columns"]}["Revenue"] == "integer"
    assert [r["Discount"] for r in sheet["sample_rows"]].count(90) == 0  # the planted row is row 18

    assert out.name == "گزارش فروش روزانه" and out.daily_report is True
    assert out.signature == column_signature(sheet_of(first))
    assert out.sheet == "Sales" and out.expected_columns == COLUMNS
    assert [m.id for m in out.metrics] == [
        "total_revenue",
        "row_count",
        "top_products",
        "by_employee",
        "daily",
    ]
    assert [c.id for c in out.checks] == ["high_discount"]


async def test_invalid_entries_are_dropped_not_fatal(bot: Bot, storage: LocalFileStorage) -> None:
    metrics = [
        {"id": "total_revenue", "label": "کل فروش", "measure": "sum", "field": "Revenue"},
        {"id": "ghost", "label": "ستون ناموجود", "measure": "sum", "field": "Profit"},
        {"id": "sum_text", "label": "جمع نام", "measure": "sum", "field": "Product"},
        {"id": "avg_none", "label": "میانگین بدون ستون", "measure": "avg"},
        {
            "id": "bad_day",
            "label": "روز از روی نام",
            "measure": "count",
            "group_by": "Employee",
            "group_kind": "day",
        },
        {"id": "orphan_kind", "label": "بدون گروه", "measure": "count", "group_kind": "day"},
        {"id": "total_revenue", "label": "کل تعداد", "measure": "sum", "field": "Quantity"},
        {"id": "case", "label": "ستون با حروف دیگر", "measure": "max", "field": "revenue"},
        {"id": "", "label": "بدون شناسه", "measure": "count"},
    ]
    checks = [
        {"id": "disc", "label": "تخفیف", "kind": "outlier_high", "field": "Discount"},
        {"id": "ghost_check", "label": "ناموجود", "kind": "outlier_high", "field": "Nope"},
        {"id": "text_check", "label": "متن", "kind": "outlier_low", "field": "Product"},
        {"id": "no_limit", "label": "بدون حد", "kind": "threshold_above", "field": "Revenue"},
        {"id": "empty_dates", "label": "تاریخ خالی", "kind": "missing_values", "field": "Date"},
    ]
    out, _, llm = await make_profile(StubSession(), bot, storage, good_draft(metrics=metrics, checks=checks))
    assert len(llm.calls) == 1
    assert [m.id for m in out.metrics] == ["total_revenue", "total_revenue_2", "case"]
    assert (
        out.metrics[1].field == "Quantity" and out.metrics[2].field == "Revenue"
    )  # spelled as the sheet has it
    assert [c.id for c in out.checks] == ["disc", "empty_dates"]


async def test_an_empty_profile_falls_back_to_a_row_count(bot: Bot, storage: LocalFileStorage) -> None:
    draft = good_draft(
        metrics=[{"id": "ghost", "label": "x", "measure": "sum", "field": "Profit"}],
        checks=[],
        sheet="Nonexistent",
        expected_columns=[],
    )
    out, _, _ = await make_profile(StubSession(), bot, storage, draft)
    assert out.sheet == "Sales"  # the model's sheet name did not exist: the first data sheet
    assert [m.id for m in out.metrics] == ["row_count", "rows_per_day", "rows_per_entity"]
    assert out.expected_columns == ["Employee", "Date"]  # what the fallback metrics use, in sheet order


async def test_metric_limits_and_a_failing_model(bot: Bot, storage: LocalFileStorage) -> None:
    many = [{"id": f"m{i}", "label": f"m{i}", "measure": "count"} for i in range(12)]
    out, _, _ = await make_profile(StubSession(), bot, storage, good_draft(metrics=many, checks=[]))
    assert len(out.metrics) == profiles.MAX_METRICS

    session = StubSession()
    first = await upload(session, bot, storage, sales_workbook())
    for error in (LLMError("refusal", "no"), RuntimeError("no key")):
        llm = FakeLLM(structured={"analysis_profile": [error]})
        with pytest.raises(ProfileError) as caught:
            await profiles.create_profile(session, bot, llm, first, name=None, daily_report=False)  # type: ignore[arg-type]
        assert caught.value.status == 503 and caught.value.code in ("llm_failed", "llm_unavailable")
        assert caught.value.message_fa


async def run_on(
    session: StubSession,
    bot: Bot,
    storage: LocalFileStorage,
    profile_out: Any,
    upload_row: UploadedFileRow,
    **kwargs: Any,
) -> Any:
    profile_row = next(r for r in session.added if isinstance(r, AnalysisProfileRow))
    kwargs.setdefault("submitted_by", None)
    kwargs.setdefault("narrative", False)
    return await runs.run_profile(session, bot, profile_row, upload_row, storage=storage, **kwargs)  # type: ignore[arg-type]


async def test_a_run_computes_metrics_and_flags_the_planted_discount(
    bot: Bot, storage: LocalFileStorage
) -> None:
    session = StubSession()
    out, first, _ = await make_profile(session, bot, storage)
    rows = sales_rows()[1:]
    result = await run_on(session, bot, storage, out, first)

    assert result.status == "ok" and result.schema_diff is None and result.narrative is None
    by_id = {m.id: m for m in result.metrics}
    assert by_id["total_revenue"].kind == "scalar" and by_id["total_revenue"].value == sum(r[3] for r in rows)
    assert by_id["row_count"].value == 30

    revenue_by_product: dict[str, float] = defaultdict(float)
    revenue_by_employee: dict[str, float] = defaultdict(float)
    for r in rows:
        revenue_by_product[r[1]] += r[3]
        revenue_by_employee[r[0]] += r[3]
    top = by_id["top_products"]
    assert top.kind == "breakdown"
    expected_top = sorted(revenue_by_product.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    assert [(p.label, p.value) for p in top.series or []] == expected_top
    by_employee = by_id["by_employee"]
    assert {p.label: p.value for p in by_employee.series or []} == dict(revenue_by_employee)

    daily = by_id["daily"]
    assert daily.kind == "series" and len(daily.series or []) == 10
    assert sum(p.value for p in daily.series or []) == sum(r[3] for r in rows)

    [anomaly] = result.anomalies
    assert (anomaly.check_id, anomaly.field, anomaly.severity) == ("high_discount", "Discount", "critical")
    assert anomaly.value == 90 and anomaly.group == "ردیف ۱۸"  # row 18 of the data (index 17)
    assert anomaly.expected is not None and anomaly.expected < 10

    stored = next(r for r in session.added if isinstance(r, AnalysisRunRow))
    assert stored.status == "ok" and stored.upload_id == first.id and stored.result is not None
    assert runs.run_out(stored, first.filename).metrics == result.metrics  # the stored form round-trips


async def test_the_same_layout_with_other_data_runs_the_same_way(bot: Bot, storage: LocalFileStorage) -> None:
    session = StubSession()
    out, first, _ = await make_profile(session, bot, storage)
    second = await upload(session, bot, storage, sales_workbook(shift=1))
    assert column_signature(sheet_of(second)) == out.signature  # one layout: one profile

    again = await run_on(session, bot, storage, out, first)
    other = await run_on(session, bot, storage, out, second, submitted_by="555")
    repeat = await run_on(session, bot, storage, out, first)
    assert again.metrics == repeat.metrics and again.anomalies == repeat.anomalies  # deterministic
    assert other.status == "ok" and other.submitted_by == "555"
    assert other.metrics != again.metrics  # other products per row: other breakdown
    assert [a.value for a in other.anomalies] == [90]


async def test_a_renamed_column_is_a_schema_change(bot: Bot, storage: LocalFileStorage) -> None:
    session = StubSession()
    out, _, _ = await make_profile(session, bot, storage)
    renamed = ["Employee", "Product", "Qty", "Revenue", "Discount", "Date"]
    changed = await upload(session, bot, storage, make_xlsx({"Sales": sales_rows(columns=renamed)}))
    assert column_signature(sheet_of(changed)) != out.signature

    result = await run_on(session, bot, storage, out, changed)
    assert result.status == "schema_changed"
    assert result.schema_diff == SchemaDiff(missing=["Quantity"], new=["Qty"])
    assert result.metrics == [] and result.anomalies == []
    assert result.error == "این فایل با پروفایل «گزارش فروش روزانه» مطابقت ندارد"
    stored = [r for r in session.added if isinstance(r, AnalysisRunRow)][-1]
    assert stored.status == "schema_changed" and stored.schema_diff == {
        "missing": ["Quantity"],
        "new": ["Qty"],
    }

    other_sheet = await upload(session, bot, storage, make_xlsx({"Other": sales_rows()}))
    gone = await run_on(session, bot, storage, out, other_sheet)
    assert gone.status == "schema_changed" and gone.schema_diff == SchemaDiff(missing=COLUMNS, new=[])


async def test_new_columns_alone_are_tolerated(bot: Bot, storage: LocalFileStorage) -> None:
    session = StubSession()
    out, first, _ = await make_profile(session, bot, storage)
    wider = [[*row, "x" if i else "Note"] for i, row in enumerate(sales_rows())]
    extra = await upload(session, bot, storage, make_xlsx({"Sales": wider}))
    result = await run_on(session, bot, storage, out, extra)
    assert result.status == "ok" and result.schema_diff == SchemaDiff(missing=[], new=["Note"])
    baseline = await run_on(session, bot, storage, out, first)
    assert result.metrics == baseline.metrics


async def test_threshold_low_and_missing_value_checks(bot: Bot, storage: LocalFileStorage) -> None:
    checks = [
        {"id": "big", "label": "فروش بزرگ", "kind": "threshold_above", "field": "Revenue", "threshold": 5000},
        {
            "id": "per_emp",
            "label": "جمع هر فروشنده",
            "kind": "threshold_below",
            "field": "Discount",
            "group_by": "Employee",
            "threshold": 1000,
        },
        {"id": "gaps", "label": "تخفیف خالی", "kind": "missing_values", "field": "Discount"},
        {"id": "low", "label": "کم", "kind": "outlier_low", "field": "Quantity"},
    ]
    session = StubSession()
    out, _, _ = await make_profile(session, bot, storage, good_draft(checks=checks))
    rows = sales_rows()
    for index in (3, 4, 5, 6, 7, 8):  # 6 of 30 rows without a discount: 20% is not above 20%
        rows[index][4] = None
    holes = await upload(session, bot, storage, make_xlsx({"Sales": rows}))
    result = await run_on(session, bot, storage, out, holes)
    by_check: dict[str, list[Any]] = defaultdict(list)
    for a in result.anomalies:
        by_check[a.check_id].append(a)

    big = by_check["big"]
    expected_big = sorted((r[3] for r in rows[1:] if r[3] > 5000), reverse=True)[:10]
    assert [a.value for a in big] == expected_big and {a.severity for a in big} == {"warning"}
    assert len(by_check["per_emp"]) == 5  # each employee's discounts sum to far below 1000
    [gap] = by_check["gaps"]
    assert (gap.value, gap.expected, gap.severity, gap.group) == (6, 0, "info", None)
    assert "low" not in by_check  # quantities 1..4: no outlier

    for index in (9, 10):
        rows[index][4] = None
    worse = await upload(session, bot, storage, make_xlsx({"Sales": rows}))
    [gap2] = [a for a in (await run_on(session, bot, storage, out, worse)).anomalies if a.check_id == "gaps"]
    assert (gap2.value, gap2.severity) == (8, "critical")  # 8 of 30 rows: over 20%


async def test_outliers_need_enough_values_and_variation(bot: Bot, storage: LocalFileStorage) -> None:
    session = StubSession()
    out, _, _ = await make_profile(session, bot, storage)
    few = await upload(session, bot, storage, make_xlsx({"Sales": [sales_rows()[0], *sales_rows()[1:4]]}))
    flat_rows = [[*r[:4], 5, r[5]] for r in sales_rows()]
    flat_rows[0] = sales_rows()[0]
    flat = await upload(session, bot, storage, make_xlsx({"Sales": flat_rows}))
    assert (await run_on(session, bot, storage, out, few)).anomalies == []  # three values
    assert (await run_on(session, bot, storage, out, flat)).anomalies == []  # no variation


async def test_the_narrative_sees_only_the_computed_results(bot: Bot, storage: LocalFileStorage) -> None:
    session = StubSession()
    out, first, _ = await make_profile(session, bot, storage)
    llm = FakeLLM(
        structured={"analysis_narrative": [{"summary": "  فروش خوب بود. ۱ مورد غیرعادی دیده شد.  "}]}
    )
    result = await run_on(session, bot, storage, out, first, narrative=True, llm=llm)
    assert result.narrative == "فروش خوب بود. ۱ مورد غیرعادی دیده شد."
    [call] = llm.calls
    assert (call.task, call.tier) == ("analysis_narrative", "fast")
    sent = json.loads(call.messages[0]["content"])
    assert set(sent) == {"report", "metrics", "anomalies"}
    assert sent["anomalies"][0]["value"] == 90
    assert "Employee" not in json.dumps(sent["metrics"][:2])  # aggregates, not rows

    quiet = FakeLLM()
    skipped = await run_on(session, bot, storage, out, first, narrative=False, llm=quiet)
    assert skipped.narrative is None and quiet.calls == []
    no_llm = await run_on(session, bot, storage, out, first, narrative=True, llm=None)
    assert no_llm.narrative is None and no_llm.status == "ok"

    failing = FakeLLM(structured={"analysis_narrative": [RuntimeError("down")]})
    survived = await run_on(session, bot, storage, out, first, narrative=True, llm=failing)
    assert survived.status == "ok" and survived.narrative is None and survived.metrics == result.metrics


def test_update_validation_uses_the_sheets_columns() -> None:
    columns = profiles.Columns({"Revenue": "integer", "Date": "datetime", "Product": "text"})
    fixed = profiles.validate_entries(
        [
            AnalysisMetricSpec(
                id="a", label="a", measure="sum", field="revenue", group_by="date", group_kind="day"
            ),
            AnalysisMetricSpec(id="b", label="b", measure="avg", field="Product"),
            AnalysisMetricSpec(
                id="c", label="c", measure="sum", field="Revenue", group_by="Product", top_n=500
            ),
        ],
        [],
        columns,
    )
    assert [m.id for m in fixed.metrics] == ["a", "c"]
    assert (fixed.metrics[0].field, fixed.metrics[0].group_by) == ("Revenue", "Date")
    assert fixed.metrics[1].group_kind == "field" and fixed.metrics[1].top_n == profiles.MAX_TOP_N
    assert len(fixed.dropped) == 1
