"""Analysis profiles: the one LLM call of Spreadsheet Intelligence, and the deterministic validation that
makes its answer safe to run without the model afterwards.

``create_profile`` shows the model the sheet names, per column the inferred type and summary statistics
and at most ten sample rows of the upload's stored inspection (never the whole file), asks for a
``ProfileDraft`` with one strong-tier structured call, and then VALIDATES every entry against the real
columns: a metric or check that names a missing column, applies sum/avg/min/max to a non-numeric column,
buckets a non-datetime column by day or week, repeats an id or lacks a needed value is dropped (logged,
never fatal), so one bad suggestion never fails the profile. The profile is stored once per bot and
layout signature (``column_signature`` of the chosen sheet); creating it again for the same layout
updates the stored one. ``update_profile`` applies the same validation to an owner's edit.

The caller commits. Errors are ``ProfileError`` (Persian ``message_fa``, HTTP ``status``).
"""

import json
import logging
import uuid
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import LLMClient, LLMError
from app.db.models import AnalysisProfileRow, AnalysisRunRow, Bot, UploadedFileRow
from app.schemas.business import (
    AnalysisCheckSpec,
    AnalysisMetricSpec,
    AnalysisProfileOut,
    AnalysisProfileUpdateIn,
    SheetProfile,
    WorkbookInspection,
)
from app.spreadsheets import service
from app.spreadsheets.inspect import column_signature, normalize_label

log = logging.getLogger(__name__)

MAX_METRICS = 8
MAX_CHECKS = 6
MAX_TOP_N = 50
MAX_PROMPT_SHEETS = 6
MAX_PROMPT_COLUMNS = 60
PROMPT_SAMPLE_ROWS = 10
MAX_NAME_CHARS = 120
UPLOADS_SCANNED = 50  # uploads searched for a profile's column types (``update_profile``)
NUMERIC = frozenset({"integer", "decimal"})

LLM_UNAVAILABLE_MESSAGE = "تحلیل هوشمند فایل اکنون در دسترس نیست. کمی بعد دوباره تلاش کنید."
LLM_FAILED_MESSAGE = "ساخت پروفایل تحلیل انجام نشد. دوباره تلاش کنید."
EMPTY_SHEET_MESSAGE = "این فایل هیچ برگهٔ دارای داده‌ای ندارد."
DEFAULT_PROFILE_NAME = "گزارش اکسل"


class ProfileError(Exception):
    """A refusal the API reports as is: stable ``code``, Persian ``message_fa``, HTTP ``status``."""

    def __init__(self, status: int, code: str, message_fa: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message_fa = message_fa


class LLMUnavailable(ProfileError):
    def __init__(self, message_fa: str = LLM_UNAVAILABLE_MESSAGE, *, code: str = "llm_unavailable") -> None:
        super().__init__(503, code, message_fa)


class ProfileDraft(BaseModel):
    """What the model returns (see ``prompts/profile.md``)."""

    name: str
    sheet: str
    expected_columns: list[str] = Field(default_factory=list)
    metrics: list[AnalysisMetricSpec] = Field(default_factory=list)
    checks: list[AnalysisCheckSpec] = Field(default_factory=list)
    time_column: str | None = None
    entity_column: str | None = None


@cache
def load_prompt(name: str) -> str:
    return (Path(__file__).resolve().parent / "prompts" / f"{name}.md").read_text(encoding="utf-8").strip()


# --- validation -------------------------------------------------------------------------------------


class Columns:
    """The columns of one sheet (name -> inferred type; ``None`` type = unknown, not checked), with
    the tolerant name matching of the layout signature (``normalize_label``)."""

    def __init__(self, types: dict[str, str | None]) -> None:
        self.types = types
        self._by_label: dict[str, str] = {}
        for name in types:
            self._by_label.setdefault(normalize_label(name), name)

    @classmethod
    def of_sheet(cls, sheet: SheetProfile) -> "Columns":
        return cls({c.name: c.inferred_type for c in sheet.columns})

    def resolve(self, name: str | None) -> str | None:
        """The sheet's own spelling of ``name``, or None when the sheet has no such column."""
        if not name:
            return None
        return name if name in self.types else self._by_label.get(normalize_label(name))

    def kind(self, name: str) -> str | None:
        return self.types.get(name)

    def numeric(self, name: str) -> bool:
        kind = self.kind(name)
        return kind is None or kind in NUMERIC

    def datetime(self, name: str) -> bool:
        kind = self.kind(name)
        return kind is None or kind == "datetime"


@dataclass
class Validated:
    metrics: list[AnalysisMetricSpec]
    checks: list[AnalysisCheckSpec]
    dropped: list[str]


def _unique_id(raw: str, seen: set[str]) -> str | None:
    base = "_".join(raw.strip().split())[:60]
    if not base:
        return None
    candidate, n = base, 2
    while candidate in seen:
        candidate, n = f"{base}_{n}", n + 1
    seen.add(candidate)
    return candidate


def _metric(spec: AnalysisMetricSpec, columns: Columns) -> tuple[AnalysisMetricSpec | None, str | None]:
    field = None
    if spec.field:
        field = columns.resolve(spec.field)
        if field is None:
            return None, "unknown column"
    if spec.measure == "count":
        pass
    elif field is None:
        return None, f"{spec.measure} needs a field"
    elif not columns.numeric(field):
        return None, f"{spec.measure} needs a numeric column"
    group_by = None
    group_kind = spec.group_kind
    if spec.group_by:
        group_by = columns.resolve(spec.group_by)
        if group_by is None:
            return None, "unknown group column"
        group_kind = group_kind or "field"
        if group_kind in ("day", "week") and not columns.datetime(group_by):
            return None, "day/week grouping needs a datetime column"
    elif group_kind is not None:
        return None, "group_kind without group_by"
    top_n = None if group_by is None or spec.top_n is None else min(max(spec.top_n, 1), MAX_TOP_N)
    label = " ".join(spec.label.split()) or spec.id
    return (
        AnalysisMetricSpec(
            id=spec.id,
            label=label[:MAX_NAME_CHARS],
            measure=spec.measure,
            field=field,
            group_by=group_by,
            group_kind=group_kind if group_by else None,
            top_n=top_n,
        ),
        None,
    )


def _check(spec: AnalysisCheckSpec, columns: Columns) -> tuple[AnalysisCheckSpec | None, str | None]:
    field = columns.resolve(spec.field)
    if field is None:
        return None, "unknown column"
    if spec.kind != "missing_values" and not columns.numeric(field):
        return None, f"{spec.kind} needs a numeric column"
    if spec.kind in ("threshold_above", "threshold_below") and spec.threshold is None:
        return None, "threshold check without a threshold"
    group_by = None
    if spec.group_by and spec.kind != "missing_values":
        group_by = columns.resolve(spec.group_by)
        if group_by is None:
            return None, "unknown group column"
    label = " ".join(spec.label.split()) or spec.id
    return (
        AnalysisCheckSpec(
            id=spec.id,
            label=label[:MAX_NAME_CHARS],
            kind=spec.kind,
            field=field,
            group_by=group_by,
            threshold=spec.threshold,
        ),
        None,
    )


def validate_entries(
    metrics: list[AnalysisMetricSpec], checks: list[AnalysisCheckSpec], columns: Columns
) -> Validated:
    """Keep the valid metrics (at most 8) and checks (at most 6); everything else is logged and dropped.
    Ids are made unique (a repeat gets ``_2``, ``_3``...); entries beyond the limits are dropped."""
    dropped: list[str] = []
    out_metrics: list[AnalysisMetricSpec] = []
    out_checks: list[AnalysisCheckSpec] = []
    seen: set[str] = set()
    for spec in metrics:
        fixed, why = _metric(spec, columns)
        new_id = _unique_id(spec.id, seen) if fixed is not None else None
        if fixed is None or new_id is None:
            dropped.append(f"metric {spec.id!r}: {why or 'empty id'}")
        elif len(out_metrics) >= MAX_METRICS:
            dropped.append(f"metric {spec.id!r}: over the limit of {MAX_METRICS}")
        else:
            out_metrics.append(fixed.model_copy(update={"id": new_id}))
    seen = set()
    for check in checks:
        fixed_check, why = _check(check, columns)
        new_id = _unique_id(check.id, seen) if fixed_check is not None else None
        if fixed_check is None or new_id is None:
            dropped.append(f"check {check.id!r}: {why or 'empty id'}")
        elif len(out_checks) >= MAX_CHECKS:
            dropped.append(f"check {check.id!r}: over the limit of {MAX_CHECKS}")
        else:
            out_checks.append(fixed_check.model_copy(update={"id": new_id}))
    return Validated(out_metrics, out_checks, dropped)


def _fallback_metrics(draft: ProfileDraft, columns: Columns) -> list[AnalysisMetricSpec]:
    """A profile must not come out empty: a row count, plus a daily count and a per-entity count when
    the model named a usable time / entity column."""
    metrics = [AnalysisMetricSpec(id="row_count", label="تعداد ردیف‌ها", measure="count")]
    time_column = columns.resolve(draft.time_column)
    if time_column is not None and columns.kind(time_column) in ("datetime", None):
        metrics.append(
            AnalysisMetricSpec(
                id="rows_per_day",
                label="تعداد ردیف در هر روز",
                measure="count",
                group_by=time_column,
                group_kind="day",
            )
        )
    entity = columns.resolve(draft.entity_column)
    if entity is not None:
        metrics.append(
            AnalysisMetricSpec(
                id="rows_per_entity",
                label=f"تعداد ردیف بر اساس {entity}",
                measure="count",
                group_by=entity,
                group_kind="field",
            )
        )
    return metrics


def _referenced(metrics: list[AnalysisMetricSpec], checks: list[AnalysisCheckSpec]) -> set[str]:
    names: set[str] = set()
    for m in metrics:
        names.update(n for n in (m.field, m.group_by) if n)
    for c in checks:
        names.update(n for n in (c.field, c.group_by) if n)
    return names


def _expected(columns: Columns, wanted: list[str], referenced: set[str]) -> list[str]:
    """The columns the profile relies on, in sheet order: the model's list (those that exist) plus every
    referenced column; all columns when that leaves nothing."""
    chosen = {n for w in wanted if (n := columns.resolve(w)) is not None} | referenced
    if not chosen:
        return list(columns.types)
    return [name for name in columns.types if name in chosen]


# --- prompt and creation ----------------------------------------------------------------------------


def _find_sheet(inspection: WorkbookInspection, name: str) -> SheetProfile | None:
    wanted = normalize_label(name)
    for sheet in inspection.sheets:
        if normalize_label(sheet.name) == wanted:
            return sheet
    return None


def _prompt_payload(inspection: WorkbookInspection, filename: str) -> dict[str, Any]:
    sheets = []
    for sheet in [s for s in inspection.sheets if s.rows][:MAX_PROMPT_SHEETS]:
        columns = []
        for c in sheet.columns[:MAX_PROMPT_COLUMNS]:
            entry: dict[str, Any] = {"name": c.name, "type": c.inferred_type, "non_empty": c.non_null}
            entry["distinct"] = c.distinct
            for key in ("min", "max", "mean"):
                value = getattr(c, key)
                if value is not None:
                    entry[key] = value
            columns.append(entry)
        sheets.append(
            {
                "name": sheet.name,
                "rows": sheet.rows,
                "columns": columns,
                "sample_rows": sheet.sample_rows[:PROMPT_SAMPLE_ROWS],
            }
        )
    return {"filename": filename, "sheets": sheets}


def _out(row: AnalysisProfileRow, runs_count: int) -> AnalysisProfileOut:
    return AnalysisProfileOut(
        id=row.id,
        name=row.name,
        signature=row.signature,
        sheet=row.sheet,
        expected_columns=[str(c) for c in row.expected_columns],
        metrics=[AnalysisMetricSpec.model_validate(m) for m in row.metrics],
        checks=[AnalysisCheckSpec.model_validate(c) for c in row.checks],
        daily_report=row.daily_report,
        created_at=row.created_at,
        runs_count=runs_count,
    )


async def count_runs(session: AsyncSession, profile_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(AnalysisRunRow).where(AnalysisRunRow.profile_id == profile_id)
    return (await session.execute(stmt)).scalar_one()


def profile_out(row: AnalysisProfileRow, runs_count: int = 0) -> AnalysisProfileOut:
    return _out(row, runs_count)


def clean_name(name: str | None) -> str:
    return " ".join((name or "").split())[:MAX_NAME_CHARS]


async def create_profile(
    session: AsyncSession,
    bot: Bot,
    llm: LLMClient,
    upload_row: UploadedFileRow,
    *,
    name: str | None,
    daily_report: bool,
) -> AnalysisProfileOut:
    """One strong structured LLM call, then deterministic validation; upserts the profile of the
    upload's layout (see the module docstring). ``ProfileError`` when the file has no data sheet or the
    model is unavailable or answers nothing usable."""
    inspection = service.to_upload_out(upload_row).inspection
    if not any(s.rows for s in inspection.sheets):
        raise ProfileError(422, "empty_workbook", EMPTY_SHEET_MESSAGE)
    payload = _prompt_payload(inspection, upload_row.filename)
    try:
        result, _usage = await llm.structured(
            task="analysis_profile",
            tier="strong",
            system=load_prompt("profile"),
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
            schema=ProfileDraft,
        )
    except LLMError as exc:
        log.warning("bot %s: profile creation failed (%s)", bot.id, exc.code)
        raise LLMUnavailable(LLM_FAILED_MESSAGE, code="llm_failed") from None
    except Exception:
        log.exception("bot %s: profile creation could not reach the model", bot.id)
        raise LLMUnavailable() from None
    draft = ProfileDraft.model_validate(result)

    sheet = _find_sheet(inspection, draft.sheet)
    if sheet is None or not sheet.rows:
        sheet = next(s for s in inspection.sheets if s.rows)
    columns = Columns.of_sheet(sheet)
    valid = validate_entries(draft.metrics, draft.checks, columns)
    for item in valid.dropped:
        log.info("bot %s: profile draft: dropped %s", bot.id, item)
    metrics = valid.metrics or _fallback_metrics(draft, columns)
    expected = _expected(columns, draft.expected_columns, _referenced(metrics, valid.checks))
    profile_name = clean_name(name) or clean_name(draft.name) or DEFAULT_PROFILE_NAME

    signature = column_signature(sheet)
    stmt = select(AnalysisProfileRow).where(
        AnalysisProfileRow.bot_id == bot.id, AnalysisProfileRow.signature == signature
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    metric_dicts = [m.model_dump(mode="json") for m in metrics]
    check_dicts = [c.model_dump(mode="json") for c in valid.checks]
    if row is None:
        row = AnalysisProfileRow(
            id=uuid.uuid4(),
            bot_id=bot.id,
            name=profile_name,
            signature=signature,
            sheet=sheet.name,
            expected_columns=expected,
            metrics=metric_dicts,
            checks=check_dicts,
            daily_report=daily_report,
        )
        session.add(row)
    else:
        row.name = profile_name
        row.sheet = sheet.name
        row.expected_columns = expected
        row.metrics = metric_dicts
        row.checks = check_dicts
        row.daily_report = daily_report
    await session.flush()
    await session.refresh(row)
    return _out(row, await count_runs(session, row.id))


# --- update -----------------------------------------------------------------------------------------


async def _columns_of(session: AsyncSession, bot_id: uuid.UUID, row: AnalysisProfileRow) -> Columns:
    """The typed columns of the profile's sheet, from the newest upload of that layout; names only
    (types not checked) when no stored upload has it."""
    stmt = (
        select(UploadedFileRow)
        .where(UploadedFileRow.bot_id == bot_id)
        .order_by(UploadedFileRow.created_at.desc(), UploadedFileRow.id.desc())
        .limit(UPLOADS_SCANNED)
    )
    for upload in (await session.execute(stmt)).scalars():
        try:
            inspection = WorkbookInspection.model_validate(upload.inspection)
        except ValidationError:
            continue
        for sheet in inspection.sheets:
            if column_signature(sheet) == row.signature:
                return Columns.of_sheet(sheet)
    return Columns({str(name): None for name in row.expected_columns})


async def update_profile(
    session: AsyncSession, bot: Bot, row: AnalysisProfileRow, body: AnalysisProfileUpdateIn
) -> AnalysisProfileOut:
    """Apply an owner's partial edit; metrics and checks go through the same validation as a draft
    (invalid entries are dropped), and every column they use becomes an expected column."""
    if body.name is not None:
        name = clean_name(body.name)
        if name:
            row.name = name
    if body.daily_report is not None:
        row.daily_report = body.daily_report
    if body.metrics is not None or body.checks is not None:
        columns = await _columns_of(session, bot.id, row)
        metrics = body.metrics
        if metrics is None:
            metrics = [AnalysisMetricSpec.model_validate(m) for m in row.metrics]
        checks = body.checks
        if checks is None:
            checks = [AnalysisCheckSpec.model_validate(c) for c in row.checks]
        valid = validate_entries(metrics, checks, columns)
        for item in valid.dropped:
            log.info("bot %s: profile %s update: dropped %s", bot.id, row.id, item)
        row.metrics = [m.model_dump(mode="json") for m in valid.metrics]
        row.checks = [c.model_dump(mode="json") for c in valid.checks]
        referenced = _referenced(valid.metrics, valid.checks)
        row.expected_columns = [
            *(str(c) for c in row.expected_columns),
            *sorted(referenced - {str(c) for c in row.expected_columns}),
        ]
    await session.flush()
    await session.refresh(row)
    return _out(row, await count_runs(session, row.id))
