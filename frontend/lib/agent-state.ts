/**
 * Pure reducer that folds the agent event stream into the view model the Agent tab renders.
 * Unknown event types are ignored; events are applied at most once, in id order.
 */
import { stripRequirementCodes } from "@/lib/format";
import {
  isKnownEvent,
  type AgentEvent,
  type ErrorCode,
  type EventPayloads,
  type Phase,
  type Question,
  type RawAgentEvent,
  type Requirements,
  type RunKind,
  type RunStatus,
  type SpecOutline,
  type Usage,
} from "@/lib/types";

export type PhaseState = "running" | "done" | "failed";

export interface ToolEntry {
  id: number;
  loop: "build" | "repair";
  name: string;
  summary: string;
  result: { ok: boolean; summary: string } | null;
}

export interface PhaseEntry {
  /** Unique within the run (phases can repeat, for example run -> repair -> run). */
  key: string;
  phase: Phase;
  /** 1 for the first occurrence of this phase, 2 for the second, ... */
  attempt: number;
  state: PhaseState;
  summary: string | null;
  tools: ToolEntry[];
}

export type TestReportPayload = EventPayloads["test_report"];

export type FeedItem =
  | { kind: "owner" | "agent"; id: number; ts: string; text: string }
  | { kind: "requirements"; id: number; requirements: Requirements }
  | { kind: "questions"; id: number; questions: Question[]; answer: string | null }
  | {
      kind: "tests";
      id: number;
      generated: EventPayloads["tests_generated"] | null;
      /** Every test_report so far, oldest first. */
      reports: TestReportPayload[];
    }
  | {
      kind: "review";
      id: number;
      diff: EventPayloads["diff"] | null;
      approval: EventPayloads["approval_requested"] | null;
    }
  | { kind: "deployed"; id: number; revisionId: string; number: number }
  | { kind: "error"; id: number; message: string };

/**
 * Where `RunView.status` came from. "inferred": guessed from events (the fallback for a backend that
 * sends no `run_status`); "server": a GET /runs/{id} answer; "event": a `run_status` event.
 * Inference never overrides an "event" status.
 */
export type StatusSource = "inferred" | "server" | "event";

/** What the assistant says it is doing right now (the latest `activity` event of the running phase). */
export interface ActivityInfo {
  phase: string;
  label: string;
}

/** An LLM call is being retried (the latest `retrying` event of the running phase). */
export interface RetryInfo {
  phase: string;
  attempt: number;
  reason: string;
}

/** Why a run ended badly. `applied` null means the server did not say. */
export interface RunFailure {
  code: ErrorCode;
  message: string;
  applied: boolean | null;
  retryable: boolean;
}

export interface RunView {
  lastEventId: number;
  status: RunStatus;
  statusSource: StatusSource;
  feed: FeedItem[];
  phases: PhaseEntry[];
  requirements: Requirements | null;
  outline: SpecOutline | null;
  usage: Usage | null;
  /** Set by `activity`, cleared when the phase ends or the run stops running. */
  activity: ActivityInfo | null;
  /** Set by `retrying`, cleared by the next `activity` or when the phase ends. */
  retry: RetryInfo | null;
  /** The last `error` event (or `run_interrupted`). Only shown while the run is failed or interrupted. */
  failure: RunFailure | null;
  /** The server restarted while the run was working. */
  interrupted: boolean;
  /** Timestamp of the first event, and the time the run spent in the `running` status (waiting for the owner excluded). */
  startedAt: string | null;
  workedMs: number;
  /** Timestamp the current running stretch began, or null when the run is not running. */
  runningSince: string | null;
}

export const emptyRunView: RunView = {
  lastEventId: 0,
  status: "running",
  statusSource: "inferred",
  feed: [],
  phases: [],
  requirements: null,
  outline: null,
  usage: null,
  activity: null,
  retry: null,
  failure: null,
  interrupted: false,
  startedAt: null,
  workedMs: 0,
  runningSince: null,
};

export const INTERRUPTED_MESSAGE = "سرور دوباره راه‌اندازی شد و کار دستیار نیمه‌کاره ماند.";
export const UNKNOWN_FAILURE_MESSAGE = "کار دستیار با خطا پایان یافت.";

function ms(ts: string): number {
  const t = Date.parse(ts);
  return Number.isNaN(t) ? 0 : t;
}

/** Closes the running stretch at `ts` and adds it to `workedMs`. */
function stopClock(state: RunView, ts: string): Pick<RunView, "workedMs" | "runningSince"> {
  if (state.runningSince === null) return { workedMs: state.workedMs, runningSince: null };
  return { workedMs: state.workedMs + Math.max(0, ms(ts) - ms(state.runningSince)), runningSince: null };
}

function withLastOf<T extends FeedItem["kind"]>(
  feed: FeedItem[],
  kind: T,
  update: (item: Extract<FeedItem, { kind: T }>) => FeedItem,
): FeedItem[] | null {
  for (let i = feed.length - 1; i >= 0; i--) {
    const item = feed[i];
    if (item.kind === kind) {
      const next = feed.slice();
      next[i] = update(item as Extract<FeedItem, { kind: T }>);
      return next;
    }
  }
  return null;
}

/** Status change by inference; ignored once a `run_status` event has set the status. */
function infer(state: RunView, status: RunStatus): Pick<RunView, "status" | "statusSource"> {
  return state.statusSource === "event"
    ? { status: state.status, statusSource: "event" }
    : { status, statusSource: "inferred" };
}

function applyKnown(state: RunView, event: AgentEvent): RunView {
  const first = state.startedAt === null ? { startedAt: event.ts, runningSince: event.ts } : {};
  const base: RunView = { ...state, ...first, lastEventId: event.id };
  switch (event.type) {
    case "owner_message": {
      // An owner message answers any open question card.
      const answered = state.feed.map((item) =>
        item.kind === "questions" && item.answer === null ? { ...item, answer: event.payload.text } : item,
      );
      return {
        ...base,
        ...infer(state, state.status === "waiting_user" ? "running" : state.status),
        feed: [...answered, { kind: "owner", id: event.id, ts: event.ts, text: event.payload.text }],
      };
    }
    case "agent_message":
      return { ...base, feed: [...state.feed, { kind: "agent", id: event.id, ts: event.ts, text: stripRequirementCodes(event.payload.text) }] };

    case "phase_started": {
      const { phase } = event.payload;
      const attempt = state.phases.filter((p) => p.phase === phase).length + 1;
      return {
        ...base,
        ...infer(state, "running"),
        activity: null,
        retry: null,
        phases: [
          ...state.phases,
          { key: `${phase}-${attempt}`, phase, attempt, state: "running", summary: null, tools: [] },
        ],
      };
    }
    case "phase_finished": {
      const { phase, ok } = event.payload;
      const summary = event.payload.summary ? stripRequirementCodes(event.payload.summary) : event.payload.summary;
      const phases = state.phases.slice();
      let idx = -1;
      for (let i = phases.length - 1; i >= 0; i--) {
        if (phases[i].phase === phase && phases[i].state === "running") {
          idx = i;
          break;
        }
      }
      if (idx === -1) {
        const attempt = phases.filter((p) => p.phase === phase).length + 1;
        phases.push({ key: `${phase}-${attempt}`, phase, attempt, state: ok ? "done" : "failed", summary: summary ?? null, tools: [] });
      } else {
        phases[idx] = { ...phases[idx], state: ok ? "done" : "failed", summary: summary ?? null };
      }
      return { ...base, phases, activity: null, retry: null };
    }

    case "tool_call": {
      const { loop, name } = event.payload;
      const summary = stripRequirementCodes(event.payload.summary);
      const phases = state.phases.slice();
      if (phases.length === 0) {
        phases.push({ key: `${loop}-1`, phase: loop, attempt: 1, state: "running", summary: null, tools: [] });
      }
      const last = phases.length - 1;
      phases[last] = {
        ...phases[last],
        tools: [...phases[last].tools, { id: event.id, loop, name, summary, result: null }],
      };
      return { ...base, phases };
    }
    case "tool_result": {
      const { name, ok } = event.payload;
      const summary = stripRequirementCodes(event.payload.summary);
      const phases = state.phases.slice();
      for (let p = phases.length - 1; p >= 0; p--) {
        const tools = phases[p].tools;
        for (let t = tools.length - 1; t >= 0; t--) {
          if (tools[t].name === name && tools[t].result === null) {
            const nextTools = tools.slice();
            nextTools[t] = { ...tools[t], result: { ok, summary } };
            phases[p] = { ...phases[p], tools: nextTools };
            return { ...base, phases };
          }
        }
      }
      return base;
    }

    case "requirements": {
      const rest = state.feed.filter((item) => item.kind !== "requirements");
      return {
        ...base,
        requirements: event.payload.requirements,
        feed: [...rest, { kind: "requirements", id: event.id, requirements: event.payload.requirements }],
      };
    }
    case "questions":
      return {
        ...base,
        ...infer(state, "waiting_user"),
        feed: [...state.feed, { kind: "questions", id: event.id, questions: event.payload.questions, answer: null }],
      };
    case "spec_updated":
      return { ...base, outline: event.payload.outline };

    case "tests_generated": {
      const rest = state.feed.filter((item) => item.kind !== "tests");
      return { ...base, feed: [...rest, { kind: "tests", id: event.id, generated: event.payload, reports: [] }] };
    }
    case "test_report": {
      const updated = withLastOf(state.feed, "tests", (item) => ({ ...item, reports: [...item.reports, event.payload] }));
      return {
        ...base,
        feed: updated ?? [...state.feed, { kind: "tests", id: event.id, generated: null, reports: [event.payload] }],
      };
    }

    case "diff": {
      const updated = withLastOf(state.feed, "review", (item) => ({ ...item, diff: event.payload }));
      return {
        ...base,
        feed: updated ?? [...state.feed, { kind: "review", id: event.id, diff: event.payload, approval: null }],
      };
    }
    case "approval_requested": {
      const updated = withLastOf(state.feed, "review", (item) => ({ ...item, approval: event.payload }));
      return {
        ...base,
        ...infer(state, "waiting_approval"),
        feed: updated ?? [...state.feed, { kind: "review", id: event.id, diff: null, approval: event.payload }],
      };
    }
    case "deployed":
      return {
        ...base,
        ...infer(state, "done"),
        feed: [...state.feed, { kind: "deployed", id: event.id, revisionId: event.payload.revision_id, number: event.payload.number }],
      };

    case "usage":
      return { ...base, usage: event.payload };
    case "run_status": {
      const { status } = event.payload;
      if (status === "running") {
        return { ...base, status, statusSource: "event", runningSince: base.runningSince ?? event.ts };
      }
      return { ...base, ...stopClock(base, event.ts), status, statusSource: "event", activity: null, retry: null };
    }
    case "error": {
      // An error event does not by itself end the run; the server status decides.
      const { message, code, applied, retryable } = event.payload;
      return {
        ...base,
        failure: {
          code: code ?? "UNEXPECTED_ERROR",
          message,
          applied: typeof applied === "boolean" ? applied : null,
          retryable: retryable ?? true,
        },
        feed: [...state.feed, { kind: "error", id: event.id, message }],
      };
    }
    case "activity":
      return { ...base, activity: { phase: event.payload.phase, label: event.payload.label }, retry: null };
    case "retrying":
      return { ...base, retry: { phase: event.payload.phase, attempt: event.payload.attempt, reason: event.payload.reason } };
    case "run_interrupted":
      return {
        ...base,
        interrupted: true,
        activity: null,
        retry: null,
        failure: { code: "INTERRUPTED", message: INTERRUPTED_MESSAGE, applied: false, retryable: true },
      };
  }
}

/** Applies one wire event. Returns the same state object when the event is a duplicate. */
export function reduceEvent(state: RunView, raw: RawAgentEvent): RunView {
  if (raw.id <= state.lastEventId) return state;
  if (!isKnownEvent(raw)) return { ...state, lastEventId: raw.id };
  return applyKnown(state, raw);
}

/**
 * Applies the server's answer to GET /runs/{id}. `atEventId` is the last event id the view had when the
 * request started: a `run_status` event newer than that wins over this (older) answer.
 */
export function applyServerStatus(state: RunView, status: RunStatus, atEventId: number): RunView {
  if (state.statusSource === "event" && state.lastEventId > atEventId) return state;
  if (state.status === status && state.statusSource !== "inferred") return state;
  return { ...state, status, statusSource: "server" };
}

/**
 * The view of a run loaded in one go (an earlier run of the conversation history). The server's status
 * (from the run list or GET /runs/{id}) is the truth, as for the live run.
 */
export function viewFromEvents(events: RawAgentEvent[], serverStatus: RunStatus): RunView {
  const view = events.reduce(reduceEvent, emptyRunView);
  return applyServerStatus(view, serverStatus, view.lastEventId);
}

/** The most recent report across the feed, or null. */
export function latestReport(view: RunView): TestReportPayload | null {
  for (let i = view.feed.length - 1; i >= 0; i--) {
    const item = view.feed[i];
    if (item.kind === "tests" && item.reports.length > 0) return item.reports[item.reports.length - 1];
  }
  return null;
}

/* ------------------------------------------------------------------ derived: honest status */

/** The assistant's own sentence about what it is doing, only while the run is running. */
export function activeLabel(view: RunView): string | null {
  return view.status === "running" ? (view.activity?.label ?? null) : null;
}

/** The retry in progress, only while the run is running. */
export function retryInfo(view: RunView): RetryInfo | null {
  return view.status === "running" ? view.retry : null;
}

/**
 * How the run failed, or null while it did not fail. A failed run without an `error` event (an older
 * backend) still gets a failure: generic message, `applied` unknown, retry offered (the endpoint accepts
 * every failed or interrupted run).
 */
export function runFailure(view: RunView): RunFailure | null {
  if (view.status === "interrupted") {
    return view.failure ?? { code: "INTERRUPTED", message: INTERRUPTED_MESSAGE, applied: false, retryable: true };
  }
  if (view.status === "failed") {
    return view.failure ?? { code: "UNEXPECTED_ERROR", message: UNKNOWN_FAILURE_MESSAGE, applied: null, retryable: true };
  }
  return null;
}

export type StepKey =
  | "triage"
  | "understand"
  | "clarify"
  | "build"
  | "testgen"
  | "run"
  | "repair"
  | "review"
  | "await_approval"
  | "deploy";

export type StepState = "pending" | "running" | "done" | "failed" | "waiting_user" | "waiting_approval" | "skipped";

export interface RunStep {
  key: StepKey;
  label: string;
  state: StepState;
  /** The phase's own one-line summary once it finished, or a short note («بعد از رفع مشکل دوباره اجرا می‌شود»). */
  detail: string | null;
}

export const STEP_LABELS: Record<StepKey, string> = {
  triage: "تشخیص نوع درخواست",
  understand: "فهمیدن درخواست",
  clarify: "پرسش از شما",
  build: "ساخت پیکربندی",
  testgen: "نوشتن آزمون‌ها",
  run: "اجرای آزمون‌ها",
  repair: "رفع مشکل",
  review: "آماده‌سازی خلاصه",
  await_approval: "تأیید شما",
  deploy: "فعال‌سازی",
};

export interface StepOptions {
  /** The owner's own approve/reject, known before the server confirms it. */
  decided?: "approved" | "rejected" | null;
}

/**
 * The ordered step list of a run, pending steps included, from the flow's real phase sequence.
 * create: understand, [clarify], build, testgen, run, [repair], review, await_approval, deploy.
 * modify: the same behind a triage step. `clarify` shows only when the assistant asked something,
 * `repair` only when a repair happened. `kind` null (not yet known) is guessed from the phases.
 * Once the run can no longer continue (done, failed, rejected, interrupted) steps that never ran are
 * "skipped", and a failed or interrupted run marks the step it died in as "failed".
 */
export function deriveSteps(view: RunView, kind: RunKind | null, opts: StepOptions = {}): RunStep[] {
  const { status } = view;
  const flow: RunKind = kind ?? (view.phases.some((p) => p.phase === "triage") ? "modify" : "create");
  const entriesOf = (key: StepKey) => view.phases.filter((p) => p.phase === key);
  const hasDeployed = view.feed.some((i) => i.kind === "deployed");
  const approvalAsked = view.feed.some((i) => i.kind === "review" && i.approval !== null) || entriesOf("await_approval").length > 0;
  const asked = view.feed.some((i) => i.kind === "questions") || entriesOf("clarify").length > 0 || status === "waiting_user";
  const repaired = entriesOf("repair").length > 0;
  const terminalBad = status === "failed" || status === "interrupted";
  const open = status === "running" || status === "waiting_user" || status === "waiting_approval";
  const approved = opts.decided === "approved" || hasDeployed;
  const rejected = status === "rejected" || opts.decided === "rejected";

  const order: StepKey[] = [
    ...(flow === "modify" ? (["triage"] as StepKey[]) : []),
    "understand",
    ...(asked ? (["clarify"] as StepKey[]) : []),
    "build",
    "testgen",
    "run",
    ...(repaired ? (["repair"] as StepKey[]) : []),
    "review",
    "await_approval",
    "deploy",
  ];

  const steps: RunStep[] = order.map((key) => {
    const last = entriesOf(key).at(-1) ?? null;
    // A phase entry still "running" while the run is not running was cut short by the run's status.
    const fromEntry = (): StepState => {
      if (!last) return "pending";
      if (last.state === "running") return status === "running" ? "running" : terminalBad ? "failed" : "done";
      return last.state;
    };
    let state: StepState;
    let detail: string | null = null;
    switch (key) {
      case "clarify":
        state = status === "waiting_user" ? "waiting_user" : "done";
        break;
      case "await_approval":
        if (approved || (rejected && approvalAsked)) state = "done";
        else if (status === "waiting_approval") state = "waiting_approval";
        else state = fromEntry();
        break;
      case "deploy":
        if (hasDeployed) state = "done";
        else if (rejected) state = "pending";
        else if (last) state = fromEntry();
        else if (opts.decided === "approved") state = terminalBad ? "failed" : "running";
        else state = "pending";
        break;
      case "run":
        state = fromEntry();
        // Tests failed and the assistant repairs: this step runs again after the repair.
        if (last?.state === "failed" && open) {
          state = "pending";
          detail = "بعد از رفع مشکل دوباره اجرا می‌شود";
        }
        break;
      default:
        state = fromEntry();
    }
    if (detail === null && (state === "done" || state === "failed")) detail = last?.summary ?? null;
    return { key, label: STEP_LABELS[key], state, detail };
  });

  // A failed or interrupted run: the step it died in is failed; if no step was running, the next one is.
  if (terminalBad && !steps.some((s) => s.state === "failed")) {
    const next = steps.find((s) => s.state === "pending");
    if (next) next.state = "failed";
  }
  // Steps that will never run now.
  if (!open) {
    for (const step of steps) {
      if (step.state === "pending") {
        step.state = "skipped";
        step.detail = null;
      }
    }
  }
  return steps;
}

/** The step the run is on: running, or waiting for the owner. */
export function currentStep(steps: RunStep[]): RunStep | null {
  return steps.find((s) => s.state === "running" || s.state === "waiting_user" || s.state === "waiting_approval") ?? null;
}

/** Time spent working (waiting for the owner excluded) and the latest test result, for the one-line summary. */
export function runSummary(view: RunView): { workedMs: number | null; tests: { passed: number; total: number } | null } {
  const report = latestReport(view);
  return {
    workedMs: view.workedMs > 0 ? view.workedMs : null,
    tests: report ? { passed: report.passed, total: report.total } : null,
  };
}

/* ------------------------------------------------------------------ optimistic owner message */

/**
 * The message the owner just sent, shown at once. "sending": the request is in flight; "received": the
 * server accepted it but its `owner_message` event has not arrived yet; "failed": the request itself failed
 * (the text is kept for a resend). It is replaced by the real feed item when the matching event arrives.
 */
export interface PendingOwnerMessage {
  text: string;
  ts: string;
  state: "sending" | "received" | "failed";
  error: string | null;
  /** `new`: starts a run (create or modify); `existing`: answers the run that is waiting. */
  target: "new" | "existing";
  /** Owner messages the attached run's feed already held when this was sent. */
  ownerCount: number;
}

export function startPending(text: string, target: "new" | "existing", view: RunView, now: Date = new Date()): PendingOwnerMessage {
  const ownerCount = target === "new" ? 0 : view.feed.filter((i) => i.kind === "owner").length;
  return { text, ts: now.toISOString(), state: "sending", error: null, target, ownerCount };
}

/** True once the feed holds an owner message newer than the ones present at send time, with the same text. */
export function isPendingConfirmed(pending: PendingOwnerMessage, view: RunView): boolean {
  const owners = view.feed.flatMap((i) => (i.kind === "owner" ? [i.text] : []));
  return owners.slice(pending.ownerCount).some((text) => text.trim() === pending.text.trim());
}

/** The pending message to keep showing after `view` changed, or null once its real event arrived. */
export function reconcilePending(pending: PendingOwnerMessage | null, view: RunView): PendingOwnerMessage | null {
  if (!pending) return null;
  return isPendingConfirmed(pending, view) ? null : pending;
}
