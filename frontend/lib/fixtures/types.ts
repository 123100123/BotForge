import type { AgentEventType, EventPayloads } from "@/lib/types";

/** One event of a recorded run, without the envelope fields the mock server assigns (id, run_id, ts). */
export type ScriptEvent = {
  [T in AgentEventType]: { type: T; payload: EventPayloads[T] };
}[AgentEventType];

/**
 * A recorded run is a list of script items. An `event` item is emitted after `delay` ms. A `wait`
 * item pauses the run until the owner acts: "message" (answers a clarification) or "approve"
 * (approves or rejects the draft).
 */
export type ScriptItem =
  | { event: ScriptEvent; delay: number }
  | { wait: "message" | "approve" };

/** Values only known when a run starts. */
export interface ScriptContext {
  /** Revision created by this run. */
  revisionId: string;
  /** Its number (previous active number + 1). */
  revisionNumber: number;
}

export function ev<T extends AgentEventType>(
  type: T,
  payload: EventPayloads[T],
  delay = 600,
): ScriptItem {
  return { event: { type, payload } as ScriptEvent, delay };
}

export const waitFor = (wait: "message" | "approve"): ScriptItem => ({ wait });
