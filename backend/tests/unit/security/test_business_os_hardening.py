"""Regression tests of the Business OS security pass (Wave 3, I3).

- Spreadsheet Intelligence model calls (profile drafts, strong tier; run summaries, fast tier) are
  capped per owner ACCOUNT per rolling 24 hours (``profile.claim_llm_call``); before the pass a
  signed-in owner could call the strong model in a loop without any limit.
- Analysis run results are bounded (``run.MAX_SERIES_POINTS`` points per series or breakdown, group
  labels cut to ``run.MAX_GROUP_LABEL_CHARS``); before the pass one crafted file stored a result with
  one point per distinct cell value, at any length, which the runs list, the Overview and the
  Copilot then read back fifty at a time.
- An analysis run is evaluated on the spreadsheet parser thread (``service.compute_on_rows``); before
  the pass a run over a large sheet held the event loop, which serves every bot's webhook, for
  seconds per request, with no limit on runs.
- Route guards: every route of a bot goes through ``get_owned_bot`` (ownership, session, CSRF), and
  no route under a body-limit-exempt prefix parses a request body before authentication.

No database, no network: a stand-in session, a temporary ``UPLOAD_DIR`` and a scripted ``FakeLLM``.
"""

import json
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

from app.agent.llm import FakeLLM
from app.api.deps import get_owned_bot
from app.config import get_settings
from app.db.models import AnalysisProfileRow, AnalysisRunRow, Bot, UploadedFileRow
from app.main import create_app
from app.runtime.aggregate import day_label
from app.security.body_limit import EXEMPT_PREFIXES
from app.security.rate_limit import RateLimiter
from app.spreadsheets import profile as profiles
from app.spreadsheets import run as runs
from app.spreadsheets import service
from app.spreadsheets.inspect import column_signature
from app.spreadsheets.storage import LocalFileStorage

WEBHOOK_PATH = "/tg/{bot_id}"


class StubSession:
    """The few AsyncSession calls the spreadsheet code makes, kept in memory."""

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
        return StubResult()


class StubResult:
    def scalar_one_or_none(self) -> None:
        return None  # no stored profile of this layout yet

    def scalar_one(self) -> int:
        return 0  # no runs yet


@pytest.fixture(autouse=True)
def fresh_budget(monkeypatch: pytest.MonkeyPatch) -> RateLimiter:
    """A fresh model-call budget per test (the real one is process-wide)."""
    limiter = RateLimiter(profiles.LLM_WINDOW_SECONDS)
    monkeypatch.setattr(profiles, "llm_call_limiter", limiter)
    return limiter


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(str(tmp_path / "uploads"))


def owned_bot(owner: uuid.UUID) -> Bot:
    return Bot(id=uuid.uuid4(), owner_id=owner, name="ربات")


def csv_bytes(rows: list[list[Any]]) -> bytes:
    return "\n".join(",".join(str(cell) for cell in row) for row in rows).encode("utf-8")


SMALL_CSV = csv_bytes([["Name", "Amount"], ["علی", 10], ["مریم", 20], ["رضا", 30]])


async def upload(session: StubSession, bot: Bot, storage: LocalFileStorage, data: bytes) -> UploadedFileRow:
    await service.ingest(
        session,  # type: ignore[arg-type]
        bot,
        data,
        "report.csv",
        source="web",
        uploaded_by=None,
        settings=get_settings(),
        storage=storage,
    )
    return [r for r in session.added if isinstance(r, UploadedFileRow)][-1]


def small_draft() -> dict[str, Any]:
    return {
        "name": "فروش",
        "sheet": "csv",
        "expected_columns": ["Name", "Amount"],
        "metrics": [{"id": "total", "label": "جمع", "measure": "sum", "field": "Amount"}],
        "checks": [],
    }


def profile_for(bot: Bot, upload_row: UploadedFileRow, **fields: Any) -> AnalysisProfileRow:
    sheet = service.to_upload_out(upload_row).inspection.sheets[0]
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "bot_id": bot.id,
        "name": "گزارش",
        "signature": column_signature(sheet),
        "sheet": sheet.name,
        "expected_columns": [c.name for c in sheet.columns],
        "metrics": [{"id": "total", "label": "جمع", "measure": "sum", "field": "Amount"}],
        "checks": [],
        "daily_report": False,
        **fields,
    }
    return AnalysisProfileRow(**values)


# --- model-call budget (H1) ----------------------------------------------------------------------


async def test_profile_drafts_are_capped_per_owner_account_across_bots(storage: LocalFileStorage) -> None:
    owner = uuid.uuid4()
    first, second = owned_bot(owner), owned_bot(owner)
    session = StubSession()
    uploads = {bot.id: await upload(session, bot, storage, SMALL_CSV) for bot in (first, second)}
    llm = FakeLLM(structured={"analysis_profile": [small_draft()] * (profiles.LLM_CALLS_PER_DAY + 2)})

    for i in range(profiles.LLM_CALLS_PER_DAY):  # the budget is the account's, whichever bot asks
        bot = (first, second)[i % 2]
        await profiles.create_profile(
            session,  # type: ignore[arg-type]
            bot,
            llm,
            uploads[bot.id],
            name=None,
            daily_report=False,
        )
    for bot in (first, second):
        with pytest.raises(profiles.ProfileError) as refused:
            await profiles.create_profile(
                session,  # type: ignore[arg-type]
                bot,
                llm,
                uploads[bot.id],
                name=None,
                daily_report=False,
            )
        assert (refused.value.status, refused.value.code) == (429, "analysis_daily_cap")
    assert len(llm.calls) == profiles.LLM_CALLS_PER_DAY  # a refused draft never reaches the model

    # Another account has a budget of its own.
    other = owned_bot(uuid.uuid4())
    other_upload = await upload(session, other, storage, SMALL_CSV)
    out = await profiles.create_profile(
        session,  # type: ignore[arg-type]
        other,
        llm,
        other_upload,
        name=None,
        daily_report=False,
    )
    assert out.name == "فروش" and len(llm.calls) == profiles.LLM_CALLS_PER_DAY + 1


async def test_a_run_summary_is_counted_and_skipped_once_the_budget_is_used_up(
    storage: LocalFileStorage,
) -> None:
    bot = owned_bot(uuid.uuid4())
    session = StubSession()
    upload_row = await upload(session, bot, storage, SMALL_CSV)
    profile_row = profile_for(bot, upload_row)

    narrated_llm = FakeLLM(structured={"analysis_narrative": [{"summary": "خلاصه"}]})
    narrated = await runs.run_profile(
        session,  # type: ignore[arg-type]
        bot,
        profile_row,
        upload_row,
        submitted_by=None,
        narrative=True,
        llm=narrated_llm,
        storage=storage,
    )
    assert narrated.narrative == "خلاصه" and len(narrated_llm.calls) == 1

    for _ in range(profiles.LLM_CALLS_PER_DAY - 1):  # the summary above took one call of the budget
        assert profiles.claim_llm_call(bot)
    assert not profiles.claim_llm_call(bot)

    quiet_llm = FakeLLM(structured={"analysis_narrative": [{"summary": "نباید"}]})
    skipped = await runs.run_profile(
        session,  # type: ignore[arg-type]
        bot,
        profile_row,
        upload_row,
        submitted_by=None,
        narrative=True,
        llm=quiet_llm,
        storage=storage,
    )
    assert skipped.status == "ok" and skipped.narrative is None and quiet_llm.calls == []
    assert skipped.metrics == narrated.metrics  # the deterministic result is unaffected


def test_the_budget_refusal_is_the_documented_api_error() -> None:
    refusal = profiles.LLMCapReached()
    assert (refusal.status, refusal.code) == (429, "analysis_daily_cap")
    assert refusal.message_fa == profiles.LLM_CAP_MESSAGE


# --- bounded run results (H2) --------------------------------------------------------------------

ROWS = 300  # more groups and day buckets than a run keeps
LONG_NAME = "N" * 200  # every name is distinct and longer than a stored group label


def big_csv() -> tuple[bytes, list[date]]:
    start = date(2025, 1, 1)
    days = [start + timedelta(days=i) for i in range(ROWS)]
    rows: list[list[Any]] = [["Name", "Amount", "Date"]]
    rows += [[f"{LONG_NAME}-{i:03d}", i + 1, day.isoformat()] for i, day in enumerate(days)]
    return csv_bytes(rows), days


async def test_run_results_keep_bounded_series_and_short_group_labels(storage: LocalFileStorage) -> None:
    bot = owned_bot(uuid.uuid4())
    session = StubSession()
    data, days = big_csv()
    upload_row = await upload(session, bot, storage, data)
    profile_row = profile_for(
        bot,
        upload_row,
        metrics=[
            {"id": "by_name", "label": "هر نام", "measure": "sum", "field": "Amount", "group_by": "Name"},
            {"id": "per_day", "label": "هر روز", "measure": "count", "group_by": "Date", "group_kind": "day"},
            {"id": "total", "label": "جمع", "measure": "sum", "field": "Amount"},
        ],
        checks=[
            {
                "id": "big",
                "label": "بزرگ",
                "kind": "threshold_above",
                "field": "Amount",
                "group_by": "Name",
                "threshold": 0,
            },
        ],
    )

    out = await runs.run_profile(
        session,  # type: ignore[arg-type]
        bot,
        profile_row,
        upload_row,
        submitted_by=None,
        narrative=False,
        storage=storage,
    )
    assert out.status == "ok"
    metrics = {m.id: m for m in out.metrics}

    # Scalars still see every row.
    assert metrics["total"].value == ROWS * (ROWS + 1) / 2
    assert metrics["by_name"].value == metrics["total"].value

    # A breakdown keeps its largest groups, labels cut.
    by_name = metrics["by_name"].series or []
    assert len(by_name) == runs.MAX_SERIES_POINTS
    assert [p.value for p in by_name] == [float(v) for v in range(ROWS, ROWS - runs.MAX_SERIES_POINTS, -1)]
    assert all(len(p.label) <= runs.MAX_GROUP_LABEL_CHARS for p in by_name)

    # A day series keeps its latest buckets, in time order.
    per_day = metrics["per_day"].series or []
    assert [p.label for p in per_day] == [
        day_label(d, with_year=True) for d in days[-runs.MAX_SERIES_POINTS :]
    ]
    assert all(p.value == 1.0 for p in per_day)

    # Anomaly groups are cut too.
    assert len(out.anomalies) == runs.MAX_ANOMALIES_PER_CHECK
    assert all(a.group is not None and len(a.group) <= runs.MAX_GROUP_LABEL_CHARS for a in out.anomalies)

    # What is stored stays small whatever the file holds.
    [stored] = [r for r in session.added if isinstance(r, AnalysisRunRow)]
    assert len(json.dumps(stored.result, ensure_ascii=False).encode()) < 32 * 1024


# --- runs off the event loop (H3) ----------------------------------------------------------------


async def test_a_run_is_evaluated_on_the_parser_thread_never_on_the_event_loop(
    storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A large sheet is seconds of CPU: on the event loop it would stall every bot's webhook."""
    seen: list[str] = []

    def spy(name: str) -> Any:
        original = getattr(runs, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            seen.append(threading.current_thread().name)
            return original(*args, **kwargs)

        monkeypatch.setattr(runs, name, wrapper)

    for name in ("_rows_as_dicts", "_metric_value", "_run_check"):
        spy(name)
    bot = owned_bot(uuid.uuid4())
    session = StubSession()
    upload_row = await upload(session, bot, storage, SMALL_CSV)
    profile_row = profile_for(
        bot,
        upload_row,
        checks=[{"id": "gaps", "label": "خالی", "kind": "missing_values", "field": "Amount"}],
    )

    out = await runs.run_profile(
        session,  # type: ignore[arg-type]
        bot,
        profile_row,
        upload_row,
        submitted_by=None,
        narrative=False,
        storage=storage,
    )
    assert out.status == "ok" and out.metrics[0].value == 60
    loop_thread = threading.current_thread().name
    assert len(seen) == 3 and loop_thread not in seen
    assert all(name.startswith("spreadsheet-parse") for name in seen)


# --- route guards ----------------------------------------------------------------------------------


def _api_routes() -> list[APIRoute]:
    def walk(routes: Any) -> Any:
        for route in routes:
            inner = getattr(route, "original_router", None)  # FastAPI wraps included routers
            if inner is not None:
                yield from walk(inner.routes)
            elif isinstance(route, APIRoute):
                yield route

    return list(walk(create_app().routes))


def _dependencies(route: APIRoute) -> set[Any]:
    found: set[Any] = set()
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        found.add(dependency.call)
        pending.extend(dependency.dependencies)
    return found


def test_every_route_of_a_bot_resolves_the_bot_through_get_owned_bot() -> None:
    routes = [r for r in _api_routes() if "{bot_id}" in r.path and r.path != WEBHOOK_PATH]
    assert len(routes) > 40  # the Business OS routers are all included
    unguarded = [f"{sorted(r.methods)} {r.path}" for r in routes if get_owned_bot not in _dependencies(r)]
    assert unguarded == []


def test_no_route_under_a_body_limit_exempt_prefix_parses_a_body_before_authentication() -> None:
    exempt = [r for r in _api_routes() if r.path.startswith(EXEMPT_PREFIXES)]
    assert {r.path for r in exempt} == {"/uploads/bots/{bot_id}", WEBHOOK_PATH}
    assert all(r.body_field is None for r in exempt)  # raw-stream readers only, under their own caps
