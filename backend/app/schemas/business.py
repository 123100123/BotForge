"""REST models of the Business OS APIs, in one place.

Routers: capabilities, reports, uploads, analysis, copilot, team, groups, announcements, schedules
(roadmap, Business OS "API surface"). ``frontend/lib/types.ts`` mirrors these models field for field:
rename nothing here without changing it there.

Conventions: every timestamp is timezone-aware (``AwareDatetime``; a naive datetime is rejected, so
the JSON always carries an offset), ids of database rows are ``uuid.UUID``, request models (``*In``)
validate their bounds, response models (``*Out`` and their parts) do not add rules beyond types.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator

# --- Capabilities ---------------------------------------------------------------------------------

CapabilityCategory = Literal["commerce", "operations", "team", "intelligence", "customer"]


class CapabilityOut(BaseModel):
    id: str
    name: str
    description: str
    category: CapabilityCategory
    kind: Literal["spec", "module"]
    enabled: bool
    configurable: bool
    requires: list[str]
    requires_any: list[str]
    conflicts: list[str]
    features: list[str]
    metrics: list[str]
    audience: str | None
    spec_keys: list[str]
    config: dict[str, Any]
    needs_agent: bool
    handoff_prompt: str | None


class CapabilityCategoryOut(BaseModel):
    id: CapabilityCategory
    name: str
    capabilities: list[CapabilityOut]


class CapabilityListOut(BaseModel):
    categories: list[CapabilityCategoryOut]


class CapabilityToggleIn(BaseModel):
    dry_run: bool = False


class CapabilityTogglePlan(BaseModel):
    capability: str
    action: Literal["enable", "disable"]
    will_enable: list[str]
    will_disable: list[str]
    blocked_by: list[str]
    needs_agent: bool
    handoff_prompt: str | None
    compat_warnings: list[str]


class CapabilityToggleOut(BaseModel):
    plan: CapabilityTogglePlan
    applied: bool
    revision_id: uuid.UUID | None
    revision_number: int | None
    message: str


class CapabilityConfigIn(BaseModel):
    config: dict[str, Any]


# --- Reports --------------------------------------------------------------------------------------

Period = Literal["today", "yesterday", "7d", "30d", "this_week", "last_week", "this_month", "all"]


class SeriesPoint(BaseModel):
    label: str
    value: float


class MetricValue(BaseModel):
    """One metric. ``kind`` says which payload is set: ``scalar`` → ``value`` (and ``previous``, the
    same metric over the preceding period, when known); ``series`` → ``series``; ``breakdown`` →
    ``series`` (one point per group); ``table`` → ``rows``."""

    id: str
    label: str
    kind: Literal["scalar", "series", "breakdown", "table"]
    value: float | None = None
    unit: str | None = None
    series: list[SeriesPoint] | None = None
    rows: list[dict[str, Any]] | None = None
    previous: float | None = None


class CapabilityReportOut(BaseModel):
    capability_key: str
    capability_id: str
    label: str
    period: Period
    since: AwareDatetime
    until: AwareDatetime
    metrics: list[MetricValue]


class ActivityItem(BaseModel):
    at: AwareDatetime
    text: str
    kind: str


class OverviewOut(BaseModel):
    period: Period
    kpis: list[MetricValue]
    activity: list[ActivityItem]
    enabled_capabilities: list[str]


# --- Uploads and spreadsheet inspection -----------------------------------------------------------


class ColumnProfile(BaseModel):
    name: str
    inferred_type: Literal["text", "integer", "decimal", "datetime", "boolean", "empty"]
    non_null: int
    distinct: int
    sample: list[str]
    min: str | None = None
    max: str | None = None
    mean: float | None = None


class SheetProfile(BaseModel):
    name: str
    rows: int
    columns: list[ColumnProfile]
    sample_rows: list[dict[str, Any]]


class WorkbookInspection(BaseModel):
    sheets: list[SheetProfile]
    signature: str
    row_limit_hit: bool


class UploadOut(BaseModel):
    id: uuid.UUID
    filename: str
    size: int
    content_type: str
    sha256: str
    created_at: AwareDatetime
    inspection: WorkbookInspection


# --- Analysis profiles and runs -------------------------------------------------------------------


class AnalysisMetricSpec(BaseModel):
    id: str
    label: str
    measure: Literal["count", "sum", "avg", "min", "max"]
    field: str | None = None
    group_by: str | None = None
    group_kind: Literal["field", "day", "week"] | None = None
    top_n: int | None = None


class AnalysisCheckSpec(BaseModel):
    id: str
    label: str
    kind: Literal["outlier_high", "outlier_low", "threshold_above", "threshold_below", "missing_values"]
    field: str
    group_by: str | None = None
    threshold: float | None = None


class AnalysisProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    signature: str
    sheet: str
    expected_columns: list[str]
    metrics: list[AnalysisMetricSpec]
    checks: list[AnalysisCheckSpec]
    daily_report: bool
    created_at: AwareDatetime
    runs_count: int


class AnalysisProfileCreateIn(BaseModel):
    upload_id: uuid.UUID
    name: str | None = None
    daily_report: bool = False


class AnalysisProfileUpdateIn(BaseModel):
    """Partial update: a field left as None is unchanged."""

    name: str | None = None
    daily_report: bool | None = None
    metrics: list[AnalysisMetricSpec] | None = None
    checks: list[AnalysisCheckSpec] | None = None


class AnalysisRunIn(BaseModel):
    upload_id: uuid.UUID
    narrative: bool = False


class SchemaDiff(BaseModel):
    missing: list[str]
    new: list[str]


class AnalysisAnomaly(BaseModel):
    check_id: str
    label: str
    field: str
    group: str | None = None
    value: float | None = None
    expected: float | None = None
    severity: Literal["info", "warning", "critical"]


class AnalysisRunOut(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    upload_id: uuid.UUID | None
    filename: str | None
    status: Literal["ok", "schema_changed", "failed"]
    submitted_by: str | None
    created_at: AwareDatetime
    metrics: list[MetricValue]
    anomalies: list[AnalysisAnomaly]
    narrative: str | None = None
    schema_diff: SchemaDiff | None = None
    error: str | None = None


# --- Copilot --------------------------------------------------------------------------------------

COPILOT_MAX_TURNS = 12
COPILOT_MAX_TURN_CHARS = 4000


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=COPILOT_MAX_TURN_CHARS)]


class CopilotMessageIn(BaseModel):
    """The last turns of the conversation, oldest first (the endpoint is stateless). The newest turn
    must be the owner's question."""

    messages: list[ChatTurn] = Field(min_length=1, max_length=COPILOT_MAX_TURNS)

    @field_validator("messages")
    @classmethod
    def _last_turn_is_user(cls, messages: list[ChatTurn]) -> list[ChatTurn]:
        if messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return messages


class ToolCallOut(BaseModel):
    name: str
    arguments: dict[str, Any]
    summary: str


class CopilotMessageOut(BaseModel):
    reply: str
    tool_calls: list[ToolCallOut]
    usage: dict[str, Any]


# --- Team and roles -------------------------------------------------------------------------------

Role = Literal["customer", "staff", "manager"]


class TeamMemberOut(BaseModel):
    actor_id: str
    display_name: str | None
    role: Role
    first_seen: AwareDatetime


class TeamOut(BaseModel):
    staff_link: str | None
    staff_link_code: str | None
    members: list[TeamMemberOut]
    counts: dict[str, int]


class StaffLinkOut(BaseModel):
    staff_link: str | None
    staff_link_code: str | None


class MemberRoleIn(BaseModel):
    role: Role


# --- Groups ---------------------------------------------------------------------------------------


class GroupOut(BaseModel):
    chat_id: int
    title: str
    kind: Literal["group", "supergroup", "channel"]
    added_at: AwareDatetime
    active: bool


class PublishIn(BaseModel):
    collection: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    record_id: int = Field(ge=1)


class PublishOut(BaseModel):
    queued: bool
    message: str


# --- Announcements --------------------------------------------------------------------------------

Audience = Literal["everyone", "customers", "staff", "managers", "subscribers"]
ANNOUNCEMENT_MAX_CHARS = 3500  # below Telegram's 4096-character message limit, leaving room for a header


class AnnouncementIn(BaseModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=ANNOUNCEMENT_MAX_CHARS)
    ]
    audience: Audience
    category: str | None = None
    group_chat_ids: list[int] = Field(default_factory=list, max_length=50)


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    text: str
    audience: Audience
    recipients: int
    created_at: AwareDatetime
    status: str


# --- Scheduled reports ----------------------------------------------------------------------------


class ScheduleOut(BaseModel):
    """A scheduled report. ``time`` is HH:MM (24-hour) in the bot's timezone; ``weekday`` (0 = Monday …
    6 = Sunday, Python's convention) is set for ``weekly_summary`` only."""

    id: str
    kind: Literal["daily_summary", "weekly_summary"]
    time: Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
    weekday: int | None = Field(default=None, ge=0, le=6)
    enabled: bool
    metrics: list[str]


class SchedulesIn(BaseModel):
    schedules: list[ScheduleOut] = Field(max_length=20)
