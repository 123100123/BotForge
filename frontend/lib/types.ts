/**
 * Types hand-mirrored from the backend contracts. Keep in sync with:
 *   backend/app/botspec/models.py, outline.py, diff.py
 *   backend/app/agent/requirements.py
 *   backend/app/testing/scenario.py
 *   backend/app/runtime/contracts.py
 *   IMPLEMENTATION_ROADMAP.md ("Agent Architecture" events, "Backend API")
 *
 * REST shapes follow the roadmap's "Response shapes" table and the backend code that exists
 * (backend/app/api/bots.py, data.py). Where the code exists it is authoritative.
 */

/* ------------------------------------------------------------------ BotSpec */

export type FieldType =
  | "text"
  | "long_text"
  | "integer"
  | "decimal"
  | "datetime"
  | "boolean"
  | "choice"
  | "phone";

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required: boolean;
  choices: string[] | null;
  default: string | null;
}

export interface Resource {
  key: string;
  label: string;
  label_plural: string;
  fields: FieldDef[];
  title_field: string;
}

export interface BotMeta {
  name: string;
  welcome_text: string;
  timezone: string;
  language: "fa";
}

export interface TextOverride {
  key: string;
  value: string;
}

export interface InfoPage {
  key: string;
  title: string;
  body: string;
}

/** Who may use a capability in the Telegram bot (spec-level gate). */
export type CapabilityAudience = "everyone" | "staff" | "managers";

export interface InfoCapability {
  type: "info";
  enabled: boolean;
  audience: CapabilityAudience;
  key: string;
  title: string;
  pages: InfoPage[];
}

export interface CatalogCapability {
  type: "catalog";
  enabled: boolean;
  audience: CapabilityAudience;
  key: string;
  title: string;
  resource: string;
  detail_fields: string[];
  upcoming_only_field: string | null;
  sort_field: string | null;
  sort_desc: boolean;
  texts: TextOverride[];
}

export interface Capacity {
  mode: "fixed" | "per_item";
  value: number | null;
  field: string | null;
}

export interface Waitlist {
  enabled: boolean;
  auto_promote: boolean;
}

export interface Cancellation {
  enabled: boolean;
  deadline_hours: number | null;
}

export interface BookingCapability {
  type: "booking";
  enabled: boolean;
  audience: CapabilityAudience;
  key: string;
  title: string;
  resource: string;
  capacity: Capacity;
  start_field: string | null;
  detail_fields: string[];
  form_fields: FieldDef[];
  one_active_per_user_per_item: boolean;
  max_active_per_user: number | null;
  closes_hours_before_start: number | null;
  waitlist: Waitlist;
  cancellation: Cancellation;
  notify_owner_on: ("booked" | "waitlisted" | "cancelled")[];
  notify_user_on: "promoted"[];
  texts: TextOverride[];
  /** "events" is the booking engine with event wording (RSVP, categories, reminders). */
  preset: "booking" | "events";
  reminder_hours_before: number | null;
  category_field: string | null;
}

export interface StatusDef {
  key: string;
  label: string;
}

export interface OwnerAction {
  key: string;
  label: string;
  from_statuses: string[];
  to_status: string;
}

export interface RequestCapability {
  type: "request";
  enabled: boolean;
  audience: CapabilityAudience;
  key: string;
  title: string;
  form_fields: FieldDef[];
  item_resource: string | null;
  statuses: StatusDef[];
  initial_status: string;
  owner_actions: OwnerAction[];
  notify_owner_on: "submitted"[];
  notify_user_on: "status_changed"[];
  texts: TextOverride[];
}

export interface OrdersCapability {
  type: "orders";
  enabled: boolean;
  audience: CapabilityAudience;
  key: string;
  label: string;
  resource: string;
  price_field: string;
  stock_field: string | null;
  checkout_fields: FieldDef[];
  statuses: StatusDef[];
  initial_status: string;
  owner_actions: OwnerAction[];
  cancellable_statuses: string[];
  notify_owner_on: string[];
  notify_user_on: string[];
  texts: TextOverride[];
}

export type Capability =
  | InfoCapability
  | CatalogCapability
  | BookingCapability
  | RequestCapability
  | OrdersCapability;

export type CapabilityType = Capability["type"];

export interface MenuItem {
  key: string;
  label: string;
  capability: string;
  view: "main" | "mine";
}

export interface BotSpec {
  spec_version: 1;
  bot: BotMeta;
  resources: Resource[];
  capabilities: Capability[];
  menu: MenuItem[];
}

/* ------------------------------------------------------------------ SpecOutline */

export interface OutlineField {
  key: string;
  label: string;
  type: FieldType;
  required: boolean;
  choices: string[] | null;
}

export interface OutlineResource {
  key: string;
  label: string;
  label_plural: string;
  title_field: string;
  fields: OutlineField[];
}

export interface OutlineItem {
  key: string;
  label: string;
}

export interface OutlineCapability {
  key: string;
  type: CapabilityType;
  title: string;
  resource: string | null;
  form_fields: OutlineField[];
  pages: OutlineItem[];
  statuses: OutlineItem[];
  owner_actions: OutlineItem[];
}

export interface OutlineMenuItem {
  key: string;
  label: string;
  capability: string;
  view: "main" | "mine";
}

export interface SpecOutline {
  bot_name: string;
  resources: OutlineResource[];
  capabilities: OutlineCapability[];
  menu: OutlineMenuItem[];
}

/** botspec/diff.py SpecChange */
export interface SpecChange {
  path: string[];
  kind: "added" | "removed" | "changed";
  old: unknown;
  new: unknown;
  label_fa: string;
}

/* ------------------------------------------------------------------ Requirements */

export type RequirementKind = "capability" | "rule" | "data" | "text" | "notification";

export interface Requirement {
  id: string;
  kind: RequirementKind;
  statement: string;
  status: "confirmed" | "assumed";
}

export interface Unsupported {
  statement: string;
  reason: string;
  alternative: string | null;
}

export interface Question {
  id: string;
  text: string;
  why: string;
  severity: "blocking" | "important";
  options?: string[] | null;
}

export interface Requirements {
  business_summary: string;
  items: Requirement[];
  unsupported: Unsupported[];
  open_questions: Question[];
}

/* ------------------------------------------------------------------ Scenarios / tests */

export interface KV {
  key: string;
  value: string;
}

export interface SeedRecord {
  ref: string;
  collection: string;
  values: KV[];
}

export type NoticeKind =
  | "booked"
  | "waitlisted"
  | "cancelled"
  | "promoted"
  | "submitted"
  | "status_changed";

export type ReasonCode =
  | "capacity_full"
  | "duplicate"
  | "user_limit"
  | "booking_closed"
  | "cancel_deadline_passed"
  | "cancellation_disabled"
  | "not_found"
  | "invalid_input"
  | "not_allowed";

export type StepDo =
  | "book"
  | "cancel"
  | "expect_booking"
  | "expect_counts"
  | "submit_request"
  | "owner_action"
  | "expect_request"
  | "expect_notified"
  | "open"
  | "advance_time";

export interface Step {
  do: StepDo;
  actor?: string | null;
  capability?: string | null;
  item?: string | null;
  form?: KV[];
  action?: string | null;
  target_actor?: string | null;
  expect?: string | null;
  reason?: ReasonCode | null;
  confirmed?: number | null;
  waitlisted?: number | null;
  contains?: string | null;
  hours?: number | null;
  view?: "main" | "mine" | null;
  event?: NoticeKind | null;
}

export interface Scenario {
  id: string;
  title: string;
  source: "derived" | "acceptance";
  requirement_ids: string[];
  capability_keys: string[];
  capacity_override: number | null;
  seed: SeedRecord[];
  steps: Step[];
}

export interface StepResult {
  index: number;
  passed: boolean;
  message: string | null;
  narrative: string;
}

export interface TranscriptEntry {
  actor: string;
  direction: "in" | "out";
  text: string;
  buttons: string[];
}

export interface ScenarioResult {
  scenario_id: string;
  passed: boolean;
  failed_step: number | null;
  steps: StepResult[];
  transcript: TranscriptEntry[];
}

export interface TestReport {
  total: number;
  passed: number;
  failed: number;
  results: ScenarioResult[];
  duration_ms: number;
}

/* ------------------------------------------------------------------ Runtime (simulator) */

export interface RuntimeButton {
  label: string;
  data: string;
}

export interface OutMessage {
  to_actor_id: string;
  text: string;
  buttons: RuntimeButton[][];
  edit: boolean;
  notice: NoticeKind | null;
}

export interface Outcome {
  capability: string;
  action: "book" | "cancel" | "submit" | "owner_action";
  result: "confirmed" | "waitlisted" | "cancelled" | "submitted" | "ok" | "rejected";
  reason: ReasonCode | null;
  record_id: number | null;
}

export interface RuntimeEffect {
  kind: "record_created" | "record_updated" | "record_deleted" | "notification";
  collection: string | null;
  record_id: number | null;
  status: string | null;
  to_actor_id: string | null;
}

export interface RuntimeResponse {
  messages: OutMessage[];
  outcomes: Outcome[];
  effects: RuntimeEffect[];
}

export type Persona = "ali" | "sara" | "reza" | "owner";

/** POST /bots/{bot_id}/simulator/events. `revision_id: null` means the active revision. */
export interface SimulatorEventBody {
  revision_id: string | null;
  persona: Persona;
  kind: "start" | "text" | "callback";
  text?: string;
  data?: string;
}

/** POST /bots/{bot_id}/simulator/reset response; `loaded` = sample records loaded. */
export interface SimulatorResetResult {
  ok: boolean;
  loaded: number;
}

/* ------------------------------------------------------------------ Bots, runs, revisions (REST shapes) */

export type BotStatus = "draft" | "live" | "paused";

/** backend/app/api/bots.py BotOut */
export interface Bot {
  id: string;
  name: string;
  status: BotStatus;
  tg_username: string | null;
  active_revision_id: string | null;
  active_revision_number: number | null;
  owner_link_code: string | null;
  owner_linked: boolean;
  created_at: string;
}

/** backend/app/api/bots.py MeOut */
export interface Me {
  id: string;
  email: string | null;
}

export type RunKind = "create" | "modify";

export type RunStatus =
  | "running"
  | "waiting_user"
  | "waiting_approval"
  | "done"
  | "failed"
  | "rejected"
  | "interrupted";

export type Phase =
  | "triage"
  | "understand"
  | "clarify"
  | "build"
  | "testgen"
  | "run"
  | "repair"
  | "review"
  | "await_approval"
  | "deploy"
  | "failed";

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  tool_calls: number;
}

export interface AgentRun {
  id: string;
  bot_id: string;
  kind: RunKind;
  phase: Phase;
  status: RunStatus;
  base_revision_id: string | null;
  result_revision_id: string | null;
  /** Not part of the roadmap's run object; usage arrives as a `usage` event. */
  usage?: Usage | null;
  created_at: string;
  updated_at: string;
}

export type RevisionStatus = "draft" | "active" | "superseded" | "rejected";

export interface TestCounts {
  total: number;
  passed: number;
  failed: number;
}

/** GET /bots/{bot_id}/revisions row (newest first) and the response of POST /revisions/{id}/activate. */
export interface RevisionSummary {
  id: string;
  number: number;
  status: RevisionStatus;
  change_request: string | null;
  created_at: string;
  activated_at: string | null;
  tests: TestCounts | null;
}

/** GET /revisions/{revision_id}. `diff` is diff_specs(parent, this); empty for a first revision. */
export interface RevisionDetail {
  id: string;
  bot_id: string;
  number: number;
  status: RevisionStatus;
  parent_id: string | null;
  change_request: string | null;
  created_at: string;
  activated_at: string | null;
  spec: BotSpec;
  requirements: Requirements | null;
  /** null (or empty) when no scenarios are stored for this revision. */
  scenarios: Scenario[] | null;
  /** Scenarios superseded while building this revision; shape not specified, unused. */
  superseded: unknown[] | null;
  test_report: TestReport | null;
  diff: SpecChange[];
}

/* ------------------------------------------------------------------ Data admin / Telegram */

export interface SystemColumn {
  key: string;
  label: string;
}

export interface StatusOption {
  key: string;
  label: string;
}

/** A row action of a booking (`cancel`) or request (an owner action) collection. */
export interface CollectionAction {
  key: string;
  label: string;
  /** The action is offered only for records whose status is in this list. */
  from_statuses: string[];
}

/** backend/app/api/data.py CollectionOut */
export interface DataCollection {
  key: string;
  kind: "resource" | "booking" | "request" | "orders";
  label: string;
  label_plural: string;
  writable: boolean;
  /** resource: its fields; booking/request: the form fields */
  fields: FieldDef[];
  system_columns: SystemColumn[];
  /** resource only */
  title_field?: string | null;
  /** booking: the bookable resource; request: item_resource */
  resource?: string | null;
  /** IANA zone of the bot (date-time fields are entered in it). */
  timezone?: string;
  /** booking/request collections: the status vocabulary */
  statuses?: StatusOption[];
  /** booking/request collections: the row actions */
  actions?: CollectionAction[];
}

export interface DataOverview {
  collections: DataCollection[];
}

/** backend/app/api/data.py RecordOut */
export interface DataRecord {
  id: number;
  collection: string;
  data: Record<string, unknown>;
  status: string | null;
  actor_id: string | null;
  item_id: number | null;
  /** booking/request records: the customer's display name and the item's title (null when unknown) */
  actor_name?: string | null;
  item_title?: string | null;
  created_at: string;
  updated_at: string;
}

/** backend/app/api/data.py RecordsPage (newest first) */
export interface RecordsPage {
  collection: string;
  total: number;
  limit: number;
  offset: number;
  items: DataRecord[];
}

/** POST /bots/{bot_id}/data/{collection}/{record_id}/actions/{action} */
export interface DataActionResult {
  ok: boolean;
  outcome: Outcome | null;
  message: string;
}

/** GET/POST connect on /bots/{bot_id}/telegram; DELETE returns the same shape. */
export interface TelegramStatus {
  connected: boolean;
  username: string | null;
  bot_link: string | null;
  owner_linked: boolean;
  owner_link: string | null;
  last_error: string | null;
}

/* ------------------------------------------------------------------ Agent events */

export interface TestFailure {
  id: string;
  title: string;
  message: string;
}

/** A test named in the review card; `reason` explains why it was superseded (or carried/new). */
export interface TestRef {
  title: string;
  reason?: string | null;
}

/** The backend may send counts or lists; both are accepted. */
export type TestGroup = number | TestRef[];

export interface DiffChange {
  label_fa: string;
  kind: "added" | "removed" | "changed";
}

export type RiskLevel = "low" | "medium" | "high";

/** Requirement delta of a modify run (backend `diff` event; optional). */
export interface RequirementsDeltaView {
  added: { id: string; statement: string }[];
  changed: { id: string; before: string; after: string }[];
  removed: { id: string; statement: string }[];
}

export interface EventPayloads {
  owner_message: { text: string };
  agent_message: { text: string };
  phase_started: { phase: Phase };
  phase_finished: { phase: Phase; ok: boolean; summary?: string | null };
  requirements: { requirements: Requirements };
  questions: { questions: Question[] };
  tool_call: { loop: "build" | "repair"; name: string; summary: string };
  tool_result: { name: string; ok: boolean; summary: string };
  spec_updated: { outline: SpecOutline };
  tests_generated: { derived: number | Scenario[]; acceptance: number | Scenario[]; notes?: string[] };
  test_report: {
    total: number;
    passed: number;
    failed: number;
    failures: TestFailure[];
  };
  diff: {
    changes: DiffChange[];
    affected_capabilities: string[];
    tests: { carried: TestGroup; new: TestGroup; superseded: TestGroup };
    risk: RiskLevel;
    warnings: string[];
    requirements?: RequirementsDeltaView;
  };
  /** Authoritative run status on every transition. */
  run_status: { status: RunStatus; phase: string };
  approval_requested: {
    revision_id: string | null;
    can_approve: boolean;
    blocked_reason?: string | null;
  };
  deployed: { revision_id: string; number: number };
  usage: Usage;
  error: { message: string };
}

export type AgentEventType = keyof EventPayloads;

export type AgentEvent = {
  [T in AgentEventType]: {
    id: number;
    run_id: string;
    ts: string;
    type: T;
    payload: EventPayloads[T];
  };
}[AgentEventType];

/** Envelope as it arrives on the wire: the type may be one this client does not know. */
export interface RawAgentEvent {
  id: number;
  run_id: string;
  ts: string;
  type: string;
  payload: unknown;
}

export const KNOWN_EVENT_TYPES: readonly AgentEventType[] = [
  "owner_message",
  "agent_message",
  "phase_started",
  "phase_finished",
  "requirements",
  "questions",
  "tool_call",
  "tool_result",
  "spec_updated",
  "tests_generated",
  "test_report",
  "diff",
  "approval_requested",
  "deployed",
  "usage",
  "error",
  "run_status",
];

export function isKnownEvent(e: RawAgentEvent): e is AgentEvent {
  return (
    typeof e.payload === "object" &&
    e.payload !== null &&
    (KNOWN_EVENT_TYPES as readonly string[]).includes(e.type)
  );
}

export const TERMINAL_STATUSES: readonly RunStatus[] = ["done", "failed", "rejected", "interrupted"];

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/* ------------------------------------------------------------------ Business OS (backend/app/schemas/business.py) */

/* Capability Center */

export type CapabilityCategory = "commerce" | "operations" | "team" | "intelligence" | "customer";

export interface CapabilityOut {
  id: string;
  name: string;
  description: string;
  category: CapabilityCategory;
  kind: "spec" | "module";
  enabled: boolean;
  configurable: boolean;
  requires: string[];
  requires_any: string[];
  conflicts: string[];
  features: string[];
  metrics: string[];
  audience: string | null;
  spec_keys: string[];
  config: Record<string, unknown>;
  needs_agent: boolean;
  handoff_prompt: string | null;
}

export interface CapabilityCategoryOut {
  id: string;
  name: string;
  capabilities: CapabilityOut[];
}

export interface CapabilityListOut {
  categories: CapabilityCategoryOut[];
}

export interface CapabilityToggleIn {
  dry_run?: boolean;
}

export interface CapabilityTogglePlan {
  capability: string;
  action: "enable" | "disable";
  will_enable: string[];
  will_disable: string[];
  blocked_by: string[];
  needs_agent: boolean;
  handoff_prompt: string | null;
  compat_warnings: string[];
}

export interface CapabilityToggleOut {
  plan: CapabilityTogglePlan;
  applied: boolean;
  revision_id: string | null;
  revision_number: number | null;
  message: string;
}

export interface CapabilityConfigIn {
  config: Record<string, unknown>;
}

/* Reports */

export type Period = "today" | "yesterday" | "7d" | "30d" | "this_week" | "last_week" | "this_month" | "all";

export interface SeriesPoint {
  label: string;
  value: number;
}

export interface MetricValue {
  id: string;
  label: string;
  kind: "scalar" | "series" | "breakdown" | "table";
  value: number | null;
  unit: string | null;
  series: SeriesPoint[] | null;
  rows: Record<string, unknown>[] | null;
  previous: number | null;
}

export interface CapabilityReportOut {
  capability_key: string;
  capability_id: string;
  label: string;
  period: Period;
  since: string;
  until: string;
  metrics: MetricValue[];
}

export interface ActivityItem {
  at: string;
  text: string;
  kind: string;
}

export interface OverviewOut {
  period: Period;
  kpis: MetricValue[];
  activity: ActivityItem[];
  enabled_capabilities: string[];
}

/* Spreadsheet intelligence (Data Analyst) */

export type InferredColumnType = "text" | "integer" | "decimal" | "datetime" | "boolean" | "empty";

export interface ColumnProfile {
  name: string;
  inferred_type: InferredColumnType;
  non_null: number;
  distinct: number;
  sample: string[];
  min: string | null;
  max: string | null;
  mean: number | null;
}

export interface SheetProfile {
  name: string;
  rows: number;
  columns: ColumnProfile[];
  sample_rows: string[][];
}

export interface WorkbookInspection {
  sheets: SheetProfile[];
  signature: string;
  row_limit_hit: boolean;
}

export interface UploadOut {
  id: string;
  filename: string;
  size: number;
  content_type: string;
  sha256: string;
  created_at: string;
  inspection: WorkbookInspection;
}

export interface AnalysisMetricSpec {
  id: string;
  label: string;
  measure: "count" | "sum" | "avg" | "min" | "max";
  field: string | null;
  group_by: string | null;
  group_kind: "field" | "day" | "week" | null;
  top_n: number | null;
}

export interface AnalysisCheckSpec {
  id: string;
  label: string;
  kind: "outlier_high" | "outlier_low" | "threshold_above" | "threshold_below" | "missing_values";
  field: string;
  group_by: string | null;
  threshold: number | null;
}

export interface AnalysisProfileOut {
  id: string;
  name: string;
  signature: string;
  sheet: string;
  expected_columns: string[];
  metrics: AnalysisMetricSpec[];
  checks: AnalysisCheckSpec[];
  daily_report: boolean;
  created_at: string;
  runs_count: number;
}

export interface AnalysisProfileCreateIn {
  upload_id: string;
  name?: string;
  daily_report?: boolean;
}

export interface AnalysisProfileUpdateIn {
  name?: string;
  daily_report?: boolean;
  metrics?: AnalysisMetricSpec[];
  checks?: AnalysisCheckSpec[];
}

export interface AnalysisRunIn {
  upload_id: string;
  narrative?: boolean;
}

export interface SchemaDiff {
  missing: string[];
  new: string[];
}

export interface AnalysisAnomaly {
  check_id: string;
  label: string;
  field: string;
  group: string | null;
  value: number | null;
  expected: number | null;
  severity: "info" | "warning" | "critical";
}

export interface AnalysisRunOut {
  id: string;
  profile_id: string;
  upload_id: string | null;
  filename: string | null;
  status: "ok" | "schema_changed" | "failed";
  submitted_by: string | null;
  created_at: string;
  metrics: MetricValue[];
  anomalies: AnalysisAnomaly[];
  narrative: string | null;
  schema_diff: SchemaDiff | null;
  error: string | null;
}

/* Copilot */

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface CopilotMessageIn {
  messages: ChatTurn[];
}

export interface ToolCallOut {
  name: string;
  arguments: Record<string, unknown>;
  summary: string;
}

export interface CopilotMessageOut {
  reply: string;
  tool_calls: ToolCallOut[];
  usage: Record<string, unknown>;
}

/* Team, groups, announcements, schedules */

export type TeamRole = "customer" | "staff" | "manager";

export interface TeamMemberOut {
  actor_id: string;
  display_name: string | null;
  role: TeamRole;
  first_seen: string;
}

export interface TeamOut {
  staff_link: string | null;
  staff_link_code: string | null;
  members: TeamMemberOut[];
  counts: Record<string, number>;
}

export interface StaffLinkOut {
  staff_link: string | null;
  staff_link_code: string | null;
}

export interface MemberRoleIn {
  role: TeamRole;
}

export interface GroupOut {
  chat_id: number;
  title: string;
  kind: "group" | "supergroup" | "channel";
  added_at: string;
  active: boolean;
}

export interface PublishIn {
  collection: string;
  record_id: number;
}

export interface PublishOut {
  queued: boolean;
  message: string;
}

export type Audience = "everyone" | "customers" | "staff" | "managers" | "subscribers";

export interface AnnouncementIn {
  text: string;
  audience: Audience;
  category?: string | null;
  group_chat_ids?: number[];
}

export interface AnnouncementOut {
  id: string;
  text: string;
  audience: Audience;
  recipients: number;
  created_at: string;
  status: string;
}

export interface ScheduleOut {
  id: string;
  kind: "daily_summary" | "weekly_summary";
  time: string;
  weekday: number | null;
  enabled: boolean;
  metrics: string[];
}

export interface SchedulesIn {
  schedules: ScheduleOut[];
}
