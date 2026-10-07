import { API_BASE_URL, IS_MOCK } from "@/lib/config";
import { authHeaders, parseErrorResponse } from "@/lib/api";
import * as engine from "@/lib/mock/engine";
import type { RawAgentEvent } from "@/lib/types";

export interface StreamOptions {
  /** Resume after this event id (sent as `Last-Event-ID`). */
  lastEventId?: number;
  signal: AbortSignal;
  onEvent: (event: RawAgentEvent) => void;
  /** Called when the connection drops and a reconnect is about to be attempted, and when it is back. */
  onConnection?: (state: "open" | "reconnecting") => void;
  /** Called with a Persian message for a failure that will not be retried (for example 401 or 404). */
  onFatal?: (message: string) => void;
  /**
   * Called when the connection ended (the server closed it, or it broke). Resolve true to reconnect
   * (the run is still running) and false to stop until the caller restarts the stream (the run is
   * finished or waiting for the owner). Default: reconnect.
   */
  onClosed?: () => Promise<boolean>;
}

/**
 * Streams the events of one agent run until `signal` is aborted. Uses fetch (not EventSource) so the
 * Authorization header can be sent, and reconnects with `Last-Event-ID` after a dropped connection.
 * Mock mode replays the fixture run with its recorded delays.
 */
export function streamRunEvents(runId: string, opts: StreamOptions): Promise<void> {
  return IS_MOCK ? streamMock(runId, opts) : streamReal(runId, opts);
}

/* ------------------------------------------------------------------ mock */

function streamMock(runId: string, opts: StreamOptions): Promise<void> {
  return new Promise<void>((resolve) => {
    let last = opts.lastEventId ?? 0;
    const deliver = (event: RawAgentEvent) => {
      if (event.id <= last) return;
      last = event.id;
      opts.onEvent(event);
      // The real server closes the stream once a run stops running (finished or waiting for the owner);
      // the caller then reads the run's status.
      if (event.type === "run_status") {
        const status = (event.payload as { status?: string }).status;
        if (status === "done" || status === "failed" || status === "rejected" || status === "interrupted") {
          void opts.onClosed?.();
        }
      }
    };
    for (const event of engine.eventsAfter(runId, last)) deliver(event);
    const unsubscribe = engine.subscribe(runId, deliver);
    opts.onConnection?.("open");
    const stop = () => {
      unsubscribe();
      resolve();
    };
    if (opts.signal.aborted) stop();
    else opts.signal.addEventListener("abort", stop, { once: true });
  });
}

/* ------------------------------------------------------------------ real SSE */

const RETRY_MIN_MS = 1000;
const RETRY_MAX_MS = 5000;

interface Frame {
  id?: string;
  event?: string;
  data: string;
}

/** Parses one SSE frame (the text between blank lines). Returns null for comment-only frames. */
export function parseFrame(text: string): Frame | null {
  const frame: Frame = { data: "" };
  const data: string[] = [];
  for (const rawLine of text.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") frame.id = value;
    else if (field === "event") frame.event = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  frame.data = data.join("\n");
  return frame;
}

/** Turns a frame into an event envelope. Accepts a full envelope in `data`, or a bare payload plus `event:`/`id:`. */
function toEvent(runId: string, frame: Frame): RawAgentEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(frame.data);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const obj = parsed as Record<string, unknown>;
  const idFromFrame = frame.id !== undefined ? Number(frame.id) : NaN;
  if (typeof obj.type === "string" && "payload" in obj) {
    const id = typeof obj.id === "number" ? obj.id : idFromFrame;
    if (Number.isNaN(id)) return null;
    return {
      id,
      run_id: typeof obj.run_id === "string" ? obj.run_id : runId,
      ts: typeof obj.ts === "string" ? obj.ts : new Date().toISOString(),
      type: obj.type,
      payload: obj.payload,
    };
  }
  if (frame.event && !Number.isNaN(idFromFrame)) {
    return { id: idFromFrame, run_id: runId, ts: new Date().toISOString(), type: frame.event, payload: obj };
  }
  return null;
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

async function streamReal(runId: string, opts: StreamOptions): Promise<void> {
  const { signal } = opts;
  let last = opts.lastEventId ?? 0;
  let delay = RETRY_MIN_MS;
  /** True when the last connection ended by an error rather than a normal close. */
  let broken = false;

  while (!signal.aborted) {
    try {
      const res = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/events`, {
        headers: {
          ...(await authHeaders()),
          Accept: "text/event-stream",
          ...(last > 0 ? { "Last-Event-ID": String(last) } : {}),
        },
        signal,
      });
      if (!res.ok) {
        const err = await parseErrorResponse(res);
        if (res.status >= 400 && res.status < 500 && res.status !== 429) {
          opts.onFatal?.(err.message);
          return;
        }
        throw err;
      }
      if (!res.body) throw new Error("no body");
      opts.onConnection?.("open");
      delay = RETRY_MIN_MS;
      broken = false;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let split: number;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = parseFrame(buffer.slice(0, split));
          buffer = buffer.slice(split + 2);
          if (!frame) continue;
          const event = toEvent(runId, frame);
          if (!event || event.id <= last) continue;
          last = event.id;
          opts.onEvent(event);
        }
      }
    } catch {
      if (signal.aborted) return;
      broken = true;
    }
    if (signal.aborted) return;
    // The stream ended: ask the caller whether the run still needs it (the server closes it once a run stops running).
    if (opts.onClosed && !(await opts.onClosed())) return;
    if (signal.aborted) return;
    if (broken) opts.onConnection?.("reconnecting"); // a normal close of a running run reconnects silently
    await wait(broken ? delay : RETRY_MIN_MS, signal);
    if (broken) delay = Math.min(delay * 2, RETRY_MAX_MS);
  }
}
