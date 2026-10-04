/**
 * Pure reducer that folds the agent event stream into the view model the Agent tab renders.
 * Unknown event types are ignored; events are applied at most once, in id order.
 */
import {
  isKnownEvent,
  type AgentEvent,
  type EventPayloads,
  type Phase,
  type Question,
  type RawAgentEvent,
  type Requirements,
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

export interface RunView {
  lastEventId: number;
  status: RunStatus;
  feed: FeedItem[];
  phases: PhaseEntry[];
  requirements: Requirements | null;
  outline: SpecOutline | null;
  usage: Usage | null;
}

export const emptyRunView: RunView = {
  lastEventId: 0,
  status: "running",
  feed: [],
  phases: [],
  requirements: null,
  outline: null,
  usage: null,
};

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

function applyKnown(state: RunView, event: AgentEvent): RunView {
  const base: RunView = { ...state, lastEventId: event.id };
  switch (event.type) {
    case "owner_message": {
      // An owner message answers any open question card.
      const answered = state.feed.map((item) =>
        item.kind === "questions" && item.answer === null ? { ...item, answer: event.payload.text } : item,
      );
      return {
        ...base,
        status: state.status === "waiting_user" ? "running" : state.status,
        feed: [...answered, { kind: "owner", id: event.id, ts: event.ts, text: event.payload.text }],
      };
    }
    case "agent_message":
      return { ...base, feed: [...state.feed, { kind: "agent", id: event.id, ts: event.ts, text: event.payload.text }] };

    case "phase_started": {
      const { phase } = event.payload;
      const attempt = state.phases.filter((p) => p.phase === phase).length + 1;
      return {
        ...base,
        status: "running",
        phases: [
          ...state.phases,
          { key: `${phase}-${attempt}`, phase, attempt, state: "running", summary: null, tools: [] },
        ],
      };
    }
    case "phase_finished": {
      const { phase, ok, summary } = event.payload;
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
      return { ...base, phases };
    }

    case "tool_call": {
      const { loop, name, summary } = event.payload;
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
      const { name, ok, summary } = event.payload;
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
        status: "waiting_user",
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
        status: "waiting_approval",
        feed: updated ?? [...state.feed, { kind: "review", id: event.id, diff: null, approval: event.payload }],
      };
    }
    case "deployed":
      return {
        ...base,
        status: "done",
        feed: [...state.feed, { kind: "deployed", id: event.id, revisionId: event.payload.revision_id, number: event.payload.number }],
      };

    case "usage":
      return { ...base, usage: event.payload };
    case "error":
      return {
        ...base,
        status: "failed",
        feed: [...state.feed, { kind: "error", id: event.id, message: event.payload.message }],
      };
  }
}

/** Applies one wire event. Returns the same state object when the event is a duplicate. */
export function reduceEvent(state: RunView, raw: RawAgentEvent): RunView {
  if (raw.id <= state.lastEventId) return state;
  if (!isKnownEvent(raw)) return { ...state, lastEventId: raw.id };
  return applyKnown(state, raw);
}

/** The most recent report across the feed, or null. */
export function latestReport(view: RunView): TestReportPayload | null {
  for (let i = view.feed.length - 1; i >= 0; i--) {
    const item = view.feed[i];
    if (item.kind === "tests" && item.reports.length > 0) return item.reports[item.reports.length - 1];
  }
  return null;
}
