import { API_BASE_URL, IS_MOCK } from "@/lib/config";
import { parseErrorResponse } from "@/lib/api";
import * as engine from "@/lib/mock/engine";
import type { RawAgentEvent } from "@/lib/types";
import { createWatchdog, STALL_MS } from "@/lib/watchdog";

/** The server writes a `: heartbeat` comment this often while a run is quiet. */
export const HEARTBEAT_MS = 15_000;

export interface StreamOptions {
  /** Resume after this event id (sent as `Last-Event-ID`). */
  lastEventId?: number;
  signal: AbortSignal;
  onEvent: (event: RawAgentEvent) => void;
  /** Called when the connection drops (or goes silent) and a reconnect is about to be attempted, and when it is back. */
  onConnection?: (state: "open" | "reconnecting") => void;
  /**
   * Called with `Date.now()` whenever ANY bytes arrive, including `: heartbeat` comments (and when the
   * response headers arrive). Silence on this signal means the connection is dead; heartbeats without
   * events mean the server is alive and the model is still working.
   */
  onBytes?: (at: number) => void;
  /** Called with a Persian message for a failure that will not be retried (for example 401 or 404). */
  onFatal?: (message: string) => void;
  /**
   * Called when the connection ended (the server closed it, or it broke). Resolve true to reconnect
   * (the run is still running) and false to stop until the caller restarts the stream (the run is
   * finished or waiting for the owner). Default: reconnect.
   */
  onClosed?: (info: { broken: boolean }) => Promise<boolean>;
}

/**
 * Streams the events of one agent run until `signal` is aborted. Uses fetch (not EventSource) so the
 * request can be aborted and `Last-Event-ID` sent; it authenticates by the session cookie. Reconnects with
 * `Last-Event-ID` after a dropped connection, and after `STALL_MS` without any bytes (a dead connection
 * looks open; heartbeats prove it is not). Mock mode replays the fixture run with its recorded delays,
 * sends mock heartbeats, and can simulate a stall.
 */
export function streamRunEvents(runId: string, opts: StreamOptions): Promise<void> {
  return IS_MOCK ? streamMock(runId, opts) : streamReal(runId, opts);
}

/* ------------------------------------------------------------------ mock */

function streamMock(runId: string, opts: StreamOptions): Promise<void> {
  return new Promise<void>((resolve) => {
    let last = opts.lastEventId ?? 0;
    let unsubscribe: (() => void) | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    let watchdog: ReturnType<typeof createWatchdog> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    /** While in the future the mock "network" delivers nothing (the mock flag "stall"). */
    let stalledUntil = 0;
    let finished = false;

    const bytes = () => {
      opts.onBytes?.(Date.now());
      watchdog?.poke();
    };
    const closeConnection = () => {
      unsubscribe?.();
      unsubscribe = null;
      if (heartbeat) clearInterval(heartbeat);
      heartbeat = null;
      watchdog?.stop();
      watchdog = null;
    };
    const deliver = (event: RawAgentEvent) => {
      if (finished || Date.now() < stalledUntil || event.id <= last) return;
      last = event.id;
      bytes();
      opts.onEvent(event);
      if (
        event.type === "phase_started" &&
        (event.payload as { phase?: string }).phase === "testgen" &&
        engine.consumeMockFlag("stall")
      ) {
        stalledUntil = Date.now() + engine.MOCK_STALL_MS;
      }
      // The real server closes the stream once a run is terminal; the caller then reads the run's status.
      if (event.type === "run_status") {
        const status = (event.payload as { status?: string }).status;
        if (status === "done" || status === "failed" || status === "rejected" || status === "interrupted") {
          closeConnection();
          void opts.onClosed?.({ broken: false });
        }
      }
    };
    function onStall() {
      closeConnection();
      opts.onConnection?.("reconnecting");
      retryTimer = setTimeout(connect, 1000);
    }
    function connect() {
      retryTimer = null;
      if (finished) return;
      if (Date.now() < stalledUntil) {
        retryTimer = setTimeout(connect, 1000); // the network is still down: this reconnect attempt fails
        return;
      }
      watchdog = createWatchdog(onStall);
      for (const event of engine.eventsAfter(runId, last)) deliver(event);
      if (finished || watchdog === null) return;
      unsubscribe = engine.subscribe(runId, deliver);
      heartbeat = setInterval(() => {
        if (Date.now() >= stalledUntil) bytes();
      }, HEARTBEAT_MS);
      opts.onConnection?.("open");
      bytes();
    }
    const stop = () => {
      finished = true;
      closeConnection();
      if (retryTimer) clearTimeout(retryTimer);
      resolve();
    };
    if (opts.signal.aborted) stop();
    else {
      opts.signal.addEventListener("abort", stop, { once: true });
      connect();
    }
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
    // One abortable request per connection: the watchdog aborts it when no bytes arrive for STALL_MS.
    const conn = new AbortController();
    const onAbort = () => conn.abort();
    signal.addEventListener("abort", onAbort, { once: true });
    const watchdog = createWatchdog(() => conn.abort(), STALL_MS);
    try {
      const res = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}/events`, {
        credentials: "same-origin",
        headers: {
          Accept: "text/event-stream",
          ...(last > 0 ? { "Last-Event-ID": String(last) } : {}),
        },
        signal: conn.signal,
      });
      watchdog.poke();
      opts.onBytes?.(Date.now());
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
        // Any bytes (an event or a `: heartbeat` comment) prove the connection is alive.
        watchdog.poke();
        opts.onBytes?.(Date.now());
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
      broken = true; // includes the watchdog's abort
    } finally {
      watchdog.stop();
      signal.removeEventListener("abort", onAbort);
    }
    if (signal.aborted) return;
    // The stream ended: ask the caller whether the run still needs it (the server closes it for finished runs).
    if (opts.onClosed && !(await opts.onClosed({ broken }))) return;
    if (signal.aborted) return;
    if (broken) opts.onConnection?.("reconnecting"); // a normal close of a running run reconnects silently
    await wait(broken ? delay : RETRY_MIN_MS, signal);
    if (broken) delay = Math.min(delay * 2, RETRY_MAX_MS);
  }
}
