"""Deterministic profile runs: no LLM decides anything here.

``run_profile`` loads the profile's sheet from a stored upload, compares its columns with the profile's
``expected_columns`` (names compared with ``normalize_label``), and either records a ``schema_changed``
run (a missing column; new columns alone are tolerated and listed in ``schema_diff.new``) or evaluates
every metric with ``runtime.aggregate`` and every check, and stores the run. The same file and profile
always give the same metrics (day and week buckets use UTC because spreadsheet datetimes carry no zone).
An optional fast-tier narrative (``narrative.py``) is the only model call, and its failure leaves the
run ``ok`` without a summary.

Checks (anomalies):
- ``outlier_high`` / ``outlier_low``: z-score (population standard deviation) of the per-group sum of
  ``field`` (grouped by ``group_by``) or of the raw values when there is no ``group_by``; needs at least
  four values, flags z > 2 (warning) and z > 3 (critical). Note that with few values a z-score cannot
  exceed 2 at all (four values: at most 1.5; it takes six or more), so small samples stay quiet.
- ``threshold_above`` / ``threshold_below``: the same per-group sums or raw values against ``threshold``.
- ``missing_values``: the number of empty cells in ``field`` (info; critical above 20% of the rows).
At most ``MAX_ANOMALIES_PER_CHECK`` anomalies per check, the most extreme first.

``run_profile`` and ``run_for_upload`` flush; the caller commits.
"""

import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import LLMClient
from app.config import Settings, get_settings
from app.db.models import AnalysisProfileRow, AnalysisRunRow, Bot, UploadedFileRow
from app.runtime.aggregate import QuerySpec, Row, evaluate, to_number
from app.runtime.formatting import to_persian_digits
from app.schemas.business import (
    AnalysisAnomaly,
    AnalysisCheckSpec,
    AnalysisMetricSpec,
    AnalysisRunOut,
    MetricValue,
    SchemaDiff,
    SeriesPoint,
    SheetProfile,
    WorkbookInspection,
)
from app.spreadsheets import service
from app.spreadsheets.errors import SpreadsheetError
from app.spreadsheets.inspect import column_signature, normalize_label
from app.spreadsheets.narrative import narrate
from app.spreadsheets.reader import Cell
from app.spreadsheets.storage import FileStorage, get_storage

log = logging.getLogger(__name__)

MIN_OUTLIER_VALUES = 4
Z_WARNING = 2.0
Z_CRITICAL = 3.0
MISSING_CRITICAL_SHARE = 0.2
MAX_ANOMALIES_PER_CHECK = 10
RUNS_LIMIT = 50


def mismatch_message(profile_name: str) -> str:
    return f"این فایل با پروفایل «{profile_name}» مطابقت ندارد"


# --- layout comparison ------------------------------------------------------------------------------


def diff_columns(expected: list[str], headers: list[str]) -> SchemaDiff:
    have = {normalize_label(h) for h in headers}
    want = {normalize_label(e) for e in expected}
    return SchemaDiff(
        missing=[e for e in expected if normalize_label(e) not in have],
        new=[h for h in headers if normalize_label(h) not in want],
    )


def _sheet_of(inspection: WorkbookInspection, name: str) -> SheetProfile | None:
    wanted = normalize_label(name)
    return next((s for s in inspection.sheets if normalize_label(s.name) == wanted), None)


def _rows_as_dicts(headers: list[str], rows: list[list[Cell]], expected: list[str]) -> list[Row]:
    """Row dicts keyed by the profile's spelling of each column (so a label written differently in a
    later file still reaches the same metric)."""
    canonical = {normalize_label(e): e for e in expected}
    keys = [canonical.get(normalize_label(h), h) for h in headers]
    return [dict(zip(keys, row, strict=False)) for row in rows]


# --- metrics ----------------------------------------------------------------------------------------


def _metric_value(spec: AnalysisMetricSpec, rows: list[Row]) -> MetricValue:
    time_bucketed = spec.group_kind in ("day", "week")
    result = evaluate(
        rows,
        QuerySpec(
            measure=spec.measure,
            field=spec.field,
            group_by=spec.group_by,
            group_kind=spec.group_kind,
            top_n=spec.top_n,
            time_field=spec.group_by if time_bucketed and spec.group_by else "_created_at",
        ),
        tz=UTC,
    )
    if spec.group_by is None:
        return MetricValue(id=spec.id, label=spec.label, kind="scalar", value=result.value)
    return MetricValue(
        id=spec.id,
        label=spec.label,
        kind="series" if time_bucketed else "breakdown",
        value=result.value,
        series=[SeriesPoint(label=label, value=value) for label, value in result.groups],
    )


# --- checks -----------------------------------------------------------------------------------------


def _points(check: AnalysisCheckSpec, rows: list[Row]) -> list[tuple[str | None, float]]:
    """(group label, value): per-group sums, or one entry per row with a number."""
    if check.group_by:
        result = evaluate(rows, QuerySpec(measure="sum", field=check.field, group_by=check.group_by), tz=UTC)
        return list(result.groups)
    points: list[tuple[str | None, float]] = []
    for index, row in enumerate(rows, start=1):
        number = to_number(row.get(check.field))
        if number is not None:
            points.append((f"ردیف {to_persian_digits(index)}", number))
    return points


def _anomaly(
    check: AnalysisCheckSpec, group: str | None, value: float | None, expected: float | None, severity: str
) -> AnalysisAnomaly:
    return AnalysisAnomaly.model_validate(
        {
            "check_id": check.id,
            "label": check.label,
            "field": check.field,
            "group": group,
            "value": value,
            "expected": expected,
            "severity": severity,
        }
    )


def _outliers(check: AnalysisCheckSpec, rows: list[Row]) -> list[AnalysisAnomaly]:
    points = _points(check, rows)
    if len(points) < MIN_OUTLIER_VALUES:
        return []
    values = [v for _, v in points]
    mean = math.fsum(values) / len(values)
    std = math.sqrt(math.fsum((v - mean) ** 2 for v in values) / len(values))
    if std == 0:
        return []
    high = check.kind == "outlier_high"
    found: list[tuple[float, str | None, float]] = []
    for group, value in points:
        z = (value - mean) / std
        if (z > Z_WARNING) if high else (z < -Z_WARNING):
            found.append((abs(z), group, value))
    found.sort(key=lambda item: (-item[0], item[1] or ""))
    return [
        _anomaly(check, group, value, mean, "critical" if z > Z_CRITICAL else "warning")
        for z, group, value in found[:MAX_ANOMALIES_PER_CHECK]
    ]


def _thresholds(check: AnalysisCheckSpec, rows: list[Row]) -> list[AnalysisAnomaly]:
    limit = check.threshold
    if limit is None:
        return []
    above = check.kind == "threshold_above"
    hits = [(g, v) for g, v in _points(check, rows) if (v > limit if above else v < limit)]
    hits.sort(key=lambda item: ((-item[1] if above else item[1]), item[0] or ""))
    return [_anomaly(check, g, v, limit, "warning") for g, v in hits[:MAX_ANOMALIES_PER_CHECK]]


def _missing(check: AnalysisCheckSpec, rows: list[Row]) -> list[AnalysisAnomaly]:
    empty = sum(1 for r in rows if r.get(check.field) in (None, ""))
    if empty == 0:
        return []
    severity = "critical" if empty / len(rows) > MISSING_CRITICAL_SHARE else "info"
    return [_anomaly(check, None, float(empty), 0.0, severity)]


def _run_check(check: AnalysisCheckSpec, rows: list[Row]) -> list[AnalysisAnomaly]:
    if check.kind in ("outlier_high", "outlier_low"):
        return _outliers(check, rows)
    if check.kind in ("threshold_above", "threshold_below"):
        return _thresholds(check, rows)
    return _missing(check, rows)


# --- running ----------------------------------------------------------------------------------------


def run_out(row: AnalysisRunRow, filename: str | None) -> AnalysisRunOut:
    result: dict[str, Any] = row.result or {}
    return AnalysisRunOut(
        id=row.id,
        profile_id=row.profile_id,
        upload_id=row.upload_id,
        filename=filename,
        status=row.status,  # type: ignore[arg-type]
        submitted_by=row.submitted_by,
        created_at=row.created_at,
        metrics=[MetricValue.model_validate(m) for m in result.get("metrics", [])],
        anomalies=[AnalysisAnomaly.model_validate(a) for a in result.get("anomalies", [])],
        narrative=result.get("narrative"),
        schema_diff=None if row.schema_diff is None else SchemaDiff.model_validate(row.schema_diff),
        error=row.error,
    )


async def _store(
    session: AsyncSession,
    bot: Bot,
    profile_row: AnalysisProfileRow,
    upload_row: UploadedFileRow,
    *,
    status: str,
    submitted_by: str | None,
    result: dict[str, Any] | None = None,
    schema_diff: SchemaDiff | None = None,
    error: str | None = None,
) -> AnalysisRunOut:
    row = AnalysisRunRow(
        id=uuid.uuid4(),
        bot_id=bot.id,
        profile_id=profile_row.id,
        upload_id=upload_row.id,
        status=status,
        submitted_by=submitted_by,
        result=result,
        schema_diff=None if schema_diff is None else schema_diff.model_dump(mode="json"),
        error=error,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return run_out(row, upload_row.filename)


async def run_profile(
    session: AsyncSession,
    bot: Bot,
    profile_row: AnalysisProfileRow,
    upload_row: UploadedFileRow,
    *,
    submitted_by: str | None,
    narrative: bool,
    llm: LLMClient | None = None,
    storage: FileStorage | None = None,
    settings: Settings | None = None,
) -> AnalysisRunOut:
    """Run ``profile_row`` over ``upload_row`` and store the run (see the module docstring)."""
    cfg = settings if settings is not None else get_settings()
    store = storage if storage is not None else get_storage(cfg)
    expected = [str(c) for c in profile_row.expected_columns]
    changed_message = mismatch_message(profile_row.name)

    inspection = service.to_upload_out(upload_row).inspection
    sheet = _sheet_of(inspection, profile_row.sheet)
    if sheet is None:  # the profile's sheet is not in this file at all
        diff = SchemaDiff(missing=list(expected), new=[])
        return await _store(
            session, bot, profile_row, upload_row, status="schema_changed", submitted_by=submitted_by,
            schema_diff=diff, error=changed_message,
        )  # fmt: skip
    try:
        headers, rows = await service.load_rows(
            store,
            upload_row,
            sheet=sheet.name,
            max_rows=cfg.SPREADSHEET_MAX_ROWS,
            max_cols=cfg.SPREADSHEET_MAX_COLUMNS,
        )
    except SpreadsheetError as exc:
        log.warning("bot %s: run of profile %s failed to read upload (%s)", bot.id, profile_row.id, exc.code)
        return await _store(
            session, bot, profile_row, upload_row, status="failed", submitted_by=submitted_by,
            error=exc.message_fa,
        )  # fmt: skip

    diff = diff_columns(expected, headers)
    if diff.missing:
        return await _store(
            session, bot, profile_row, upload_row, status="schema_changed", submitted_by=submitted_by,
            schema_diff=diff, error=changed_message,
        )  # fmt: skip

    data = _rows_as_dicts(headers, rows, expected)
    metrics = [_metric_value(AnalysisMetricSpec.model_validate(m), data) for m in profile_row.metrics]
    anomalies: list[AnalysisAnomaly] = []
    for raw in profile_row.checks:
        anomalies.extend(_run_check(AnalysisCheckSpec.model_validate(raw), data))
    summary = None
    if narrative and llm is not None:
        summary = await narrate(llm, profile_row.name, metrics, anomalies)
    result = {
        "metrics": [m.model_dump(mode="json") for m in metrics],
        "anomalies": [a.model_dump(mode="json") for a in anomalies],
        "narrative": summary,
    }
    return await _store(
        session, bot, profile_row, upload_row, status="ok", submitted_by=submitted_by,
        result=result, schema_diff=diff if diff.new else None,
    )  # fmt: skip


async def run_for_upload(
    session: AsyncSession,
    bot: Bot,
    upload_row: UploadedFileRow,
    *,
    submitted_by: str | None,
    llm: LLMClient | None = None,
    storage: FileStorage | None = None,
    settings: Settings | None = None,
) -> AnalysisRunOut | None:
    """Run the bot's profile that fits ``upload_row`` (no narrative): the one whose signature equals a
    sheet's, else one whose sheet has the same name and every expected column. ``None`` when no
    profile fits (a renamed column is therefore "no profile", and the caller says so)."""
    inspection = service.to_upload_out(upload_row).inspection
    if not inspection.sheets:
        return None
    signatures = {column_signature(s) for s in inspection.sheets}
    stmt = (
        select(AnalysisProfileRow)
        .where(AnalysisProfileRow.bot_id == bot.id)
        .order_by(AnalysisProfileRow.created_at.desc(), AnalysisProfileRow.id)
    )
    profiles = list((await session.execute(stmt)).scalars())
    chosen = next((p for p in profiles if p.signature in signatures), None)
    if chosen is None:
        for profile in profiles:
            sheet = _sheet_of(inspection, profile.sheet)
            if (
                sheet is not None
                and not diff_columns(
                    [str(c) for c in profile.expected_columns], [c.name for c in sheet.columns]
                ).missing
            ):
                chosen = profile
                break
    if chosen is None:
        return None
    return await run_profile(
        session, bot, chosen, upload_row, submitted_by=submitted_by, narrative=False, llm=llm,
        storage=storage, settings=settings,
    )  # fmt: skip


async def list_runs(
    session: AsyncSession, bot_id: uuid.UUID, profile_id: uuid.UUID | None = None, limit: int = RUNS_LIMIT
) -> list[AnalysisRunOut]:
    """The bot's latest runs (newest first), optionally of one profile."""
    stmt = (
        select(AnalysisRunRow, UploadedFileRow.filename)
        .outerjoin(UploadedFileRow, UploadedFileRow.id == AnalysisRunRow.upload_id)
        .where(AnalysisRunRow.bot_id == bot_id)
        .order_by(AnalysisRunRow.created_at.desc(), AnalysisRunRow.id.desc())
        .limit(limit)
    )
    if profile_id is not None:
        stmt = stmt.where(AnalysisRunRow.profile_id == profile_id)
    return [run_out(row, filename) for row, filename in (await session.execute(stmt)).all()]
