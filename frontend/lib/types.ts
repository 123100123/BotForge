/**
 * Types hand-mirrored from the backend contracts. Keep in sync with:
 *   backend/app/botspec/models.py, outline.py, diff.py
 *   backend/app/agent/requirements.py
 *   backend/app/testing/scenario.py
 *   backend/app/runtime/contracts.py
 *   IMPLEMENTATION_ROADMAP.md ("Agent Architecture" events, "Backend API")
 *
 * Shapes marked "provisional" are not frozen by the roadmap (REST response models are owned by
 * the backend packages); they follow the roadmap's wording and should be re-checked against the
 * Pydantic response models when those land.
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

export interface InfoCapability {
  type: "info";
  key: string;
  title: string;
  pages: InfoPage[];
}

export interface CatalogCapability {
  type: "catalog";
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

export type Capability =
  | InfoCapability
  | CatalogCapability
  | BookingCapability
  | RequestCapability;

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

/* ------------------------------------------------------------------ Bots, runs, revisions (provisional REST shapes) */

export type BotStatus = "draft" | "live" | "paused";

export interface Bot {
  id: string;
  name: string;
  status: BotStatus;
  active_revision_id: string | null;
  /** Convenience for the workspace header; the backend is expected to include it. */
  active_revision_number: number | null;
  tg_username: string | null;
  created_at: string;
}

export interface Me {
  id: string;
  email: string;
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
  | "understand"
  | "clarify"
  | "build"
  | "testgen"
  | "run"
  | "repair"
  | "review"
  | "await_approval"
  | "deploy";

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
  usage: Usage | null;
  created_at: string;
  updated_at: string;
}

export type RevisionStatus = "draft" | "active" | "superseded" | "rejected";

export interface RevisionSummary {
  id: string;
  bot_id: string;
  number: number;
  parent_id: string | null;
  status: RevisionStatus;
  change_request: string | null;
  created_at: string;
  activated_at: string | null;
  tests_total: number | null;
  tests_passed: number | null;
}

export interface RevisionDetail extends RevisionSummary {
  spec: BotSpec;
  requirements: Requirements | null;
  diff: SpecChange[];
  scenarios: Scenario[];
  test_report: TestReport | null;
}

/* ------------------------------------------------------------------ Data admin / Telegram (provisional) */

export interface DataCollection {
  key: string;
  kind: "resource" | "booking" | "request";
  label: string;
  fields: FieldDef[];
}

export interface DataOverview {
  collections: DataCollection[];
}

export interface DataRecord {
  id: number;
  collection: string;
  data: Record<string, unknown>;
  status: string | null;
  actor_id: string | null;
  item_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface TelegramStatus {
  connected: boolean;
  username: string | null;
  bot_link: string | null;
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
  tests_generated: { derived: number | Scenario[]; acceptance: number | Scenario[] };
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
  };
  approval_requested: {
    revision_id: string;
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
