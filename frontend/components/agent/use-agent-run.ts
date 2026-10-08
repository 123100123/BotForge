"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "@/lib/api";
import {
  applyServerStatus,
  deriveSteps,
  emptyRunView,
  reconcilePending,
  reduceEvent,
  startPending,
  viewFromEvents,
  type PendingOwnerMessage,
  type RunStep,
  type RunView,
} from "@/lib/agent-state";
import { errorMessage } from "@/lib/errors";
import { loadRunEvents, streamRunEvents } from "@/lib/sse";
import type { AgentRun, RawAgentEvent, RunKind, RunStatus } from "@/lib/types";

/** An earlier run of the bot's conversation. Loaded once (its events are replayed), never streamed. */
export interface PastRun {
  run: AgentRun;
  /** null while the run's events are loading (or before they are asked for, or after a failed load, see `failed`). */
  view: RunView | null;
  failed: boolean;
}

interface State {
  /** The latest run: the one that is streamed live and that the owner acts on. */
  run: AgentRun | null;
  view: RunView;
  /** Every earlier run of the bot, oldest first. */
  past: PastRun[];
  /** The owner's message that is not in the feed yet. */
  pending: PendingOwnerMessage | null;
}

type Action =
  | { type: "init"; runs: AgentRun[] }
  | { type: "attach"; run: AgentRun; keepPending?: boolean }
  | { type: "event"; runId: string; event: RawAgentEvent }
  | { type: "server_run"; run: AgentRun; atEventId: number }
  | { type: "past_loaded"; runId: string; events: RawAgentEvent[] }
  | { type: "past_failed"; runId: string }
  | { type: "past_retry"; runId: string }
  | { type: "send_started"; pending: PendingOwnerMessage }
  | { type: "send_accepted" }
  | { type: "send_failed"; error: string }
  | { type: "pending_cleared" };

const initialState: State = { run: null, view: emptyRunView, past: [], pending: null };

function seededView(run: AgentRun | null): RunView {
  return run ? { ...emptyRunView, status: run.status, statusSource: "server" } : emptyRunView;
}

function updatePast(state: State, runId: string, update: (entry: PastRun) => PastRun): State {
  return { ...state, past: state.past.map((entry) => (entry.run.id === runId ? update(entry) : entry)) };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "init": {
      const [latest = null, ...older] = action.runs;
      return {
        ...state,
        run: latest,
        view: seededView(latest),
        past: older.reverse().map((run) => ({ run, view: null, failed: false })),
      };
    }
    case "attach": {
      if (state.run?.id === action.run.id) return { ...state, run: action.run };
      // The run shown so far moves into the history with the view it already has; a view that never
      // received an event is loaded from the server like any other earlier run.
      const past = state.run
        ? [...state.past, { run: state.run, view: state.view.lastEventId > 0 ? state.view : null, failed: false }]
        : state.past;
      // A new run starts with an empty feed: the pending message (sent to create it) waits for its event there.
      const pending = action.keepPending && state.pending ? { ...state.pending, ownerCount: 0 } : null;
      return { run: action.run, view: seededView(action.run), past, pending };
    }
    case "event": {
      if (action.runId !== state.run?.id) return state;
      const view = reduceEvent(state.view, action.event);
      return { ...state, view, pending: reconcilePending(state.pending, view) };
    }
    case "server_run":
      if (action.run.id !== state.run?.id) return state;
      return { ...state, run: action.run, view: applyServerStatus(state.view, action.run.status, action.atEventId) };
    case "past_loaded":
      return updatePast(state, action.runId, (entry) => ({
        ...entry,
        view: viewFromEvents(action.events, entry.run.status),
        failed: false,
      }));
    case "past_failed":
      return updatePast(state, action.runId, (entry) => ({ ...entry, failed: true }));
    case "past_retry":
      return updatePast(state, action.runId, (entry) => ({ ...entry, view: null, failed: false }));
    case "send_started":
      return { ...state, pending: action.pending };
    case "send_accepted":
      return state.pending ? { ...state, pending: { ...state.pending, state: "received" } } : state;
    case "send_failed":
      return state.pending ? { ...state, pending: { ...state.pending, state: "failed", error: action.error } } : state;
    case "pending_cleared":
      return { ...state, pending: null };
  }
}

/** How many earlier runs are loaded at the same time. */
const PAST_LOAD_CONCURRENCY = 2;

export interface AgentRunController {
  /** True until the bot's runs have been looked up. */
  loading: boolean;
  runId: string | null;
  /** The latest run as the server last reported it. */
  run: AgentRun | null;
  kind: RunKind | null;
  /** The run's status: a `run_status` event or the server's answer to GET /runs/{id}; inferred from events only as a fallback. */
  status: RunStatus | null;
  view: RunView;
  /** The ordered steps of the run (pending ones included), derived from the flow's phase sequence. */
  steps: RunStep[];
  /** Earlier runs of the bot, oldest first: the rest of the conversation history. Their events load on `loadHistory`. */
  past: PastRun[];
  /** Loads the events of the earlier runs (once each; a few at a time). Called when the conversation is opened. */
  loadHistory: () => void;
  /** Loads an earlier run again after a failed load. */
  retryPast: (runId: string) => void;
  /** The owner's own approve/reject for this run, known before the server confirms it. */
  decided: "approved" | "rejected" | null;
  /** The owner's message that was just sent and is not in the feed yet (or whose send failed). */
  pending: PendingOwnerMessage | null;
  connection: "open" | "reconnecting";
  /** `Date.now()` of the last bytes on the event stream (heartbeats included); null before the first. */
  lastBytesAt: number | null;
  /** `Date.now()` of the last event received; null before the first. */
  lastEventAt: number | null;
  /** A request (send, approve, reject, retry) is in flight. */
  busy: boolean;
  error: string | null;
  clearError: () => void;
  /** Sends the owner's message. Resolves true when the server accepted it; false when it did not (see `pending`). */
  send: (text: string) => Promise<boolean>;
  /** Sends the failed pending message again. */
  resend: () => Promise<boolean>;
  /** Drops a failed pending message. */
  dismissPending: () => void;
  approve: () => Promise<void>;
  reject: () => Promise<void>;
  /** Starts a new run from the original request of the failed or interrupted run and shows it. */
  retry: () => Promise<void>;
  /** Shows a run created elsewhere (for example a capability handoff) and streams its events. */
  attach: (run: AgentRun) => void;
}

/**
 * Owns the agent run data of one bot: the whole conversation. The latest run is streamed into a RunView
 * and is the one the owner acts on; earlier runs are kept as history, each loaded once on demand (its
 * events are replayed and the stream closes, since it is not running). The server decides the latest
 * run's status: it is re-read after every action and whenever the event stream ends.
 *
 * Stream contract (backend app/api/runs.py stream_events): the server closes a run's stream once the run
 * is not running, both when it finished and when it pauses for the owner (waiting_user, waiting_approval),
 * after the `run_status` event of that status. Such a close is normal: no reconnect and no "connection
 * lost". The stream is reopened (streamTick) after the owner answers, approves or rejects, when the run
 * runs again. Only a running run reconnects, and the liveness watchdog (lib/sse.ts) only runs while a
 * connection is open. Sending after a finished run starts a new one; the finished run moves into the history.
 */
export function useAgentRun(botId: string): AgentRunController {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<"open" | "reconnecting">("open");
  /** Stream liveness of one run; ignored once another run is attached. */
  const [live, setLive] = useState<{ runId: string; bytesAt: number | null; eventAt: number | null } | null>(null);
  const [decision, setDecision] = useState<{ runId: string; value: "approved" | "rejected" } | null>(null);
  /** Bumped to (re)start the event stream: after the owner acts on a run whose stream had stopped. */
  const [streamTick, setStreamTick] = useState(0);
  /** The conversation history was asked for (the owner opened it): earlier runs are loaded from then on. */
  const [historyWanted, setHistoryWanted] = useState(false);

  const { run, view, past, pending } = state;
  const runId = run?.id ?? null;
  const lastEventRef = useRef(0);
  const statusRef = useRef<RunStatus | null>(null);
  useEffect(() => {
    lastEventRef.current = view.lastEventId;
    statusRef.current = runId ? view.status : null;
  });

  /** Reads the run from the server and takes its status as the truth. Returns that status. */
  const syncRun = useCallback(async (id: string): Promise<RunStatus | null> => {
    const atEventId = lastEventRef.current;
    try {
      const fresh = await api.getRun(id);
      dispatch({ type: "server_run", run: fresh, atEventId });
      return fresh.status;
    } catch {
      return null;
    }
  }, []);

  // List the bot's runs once per bot: the newest is the live run, the rest are history.
  useEffect(() => {
    let cancelled = false;
    api.listRuns(botId).then(
      (runs) => {
        if (cancelled) return;
        dispatch({ type: "init", runs: [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at)) });
        setLoading(false);
      },
      (err) => {
        if (cancelled) return;
        setError(errorMessage(err));
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);

  // Load each earlier run once (a few at a time), after the history was asked for. Loads outlive
  // re-renders and stop when the bot changes or the provider unmounts.
  const pastAbort = useRef<AbortController | null>(null);
  const requested = useRef(new Set<string>());
  useEffect(() => {
    const controller = new AbortController();
    pastAbort.current = controller;
    const requestedIds = requested.current;
    return () => {
      controller.abort();
      requestedIds.clear();
    };
  }, [botId]);
  useEffect(() => {
    const signal = pastAbort.current?.signal;
    if (!historyWanted || !signal || signal.aborted) return;
    // Newest first, so the history next to the live run fills in first.
    const queue = past
      .filter((entry) => entry.view === null && !entry.failed && !requested.current.has(entry.run.id))
      .map((entry) => entry.run.id)
      .reverse();
    if (queue.length === 0) return;
    for (const id of queue) requested.current.add(id);
    const worker = async () => {
      for (let id = queue.shift(); id !== undefined && !signal.aborted; id = queue.shift()) {
        try {
          const events = await loadRunEvents(id, signal);
          if (!signal.aborted) dispatch({ type: "past_loaded", runId: id, events });
        } catch {
          if (!signal.aborted) dispatch({ type: "past_failed", runId: id });
        }
      }
    };
    for (let i = 0; i < Math.min(PAST_LOAD_CONCURRENCY, queue.length); i++) void worker();
  }, [past, historyWanted]);

  const loadHistory = useCallback(() => setHistoryWanted(true), []);
  const retryPast = useCallback((id: string) => {
    requested.current.delete(id);
    dispatch({ type: "past_retry", runId: id });
  }, []);

  // Stream the latest run. When the stream ends, the server's status says whether to reconnect.
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    void streamRunEvents(runId, {
      signal: controller.signal,
      lastEventId: lastEventRef.current,
      onEvent: (event) => {
        setLive((l) => ({ runId, bytesAt: l?.runId === runId ? l.bytesAt : null, eventAt: Date.now() }));
        dispatch({ type: "event", runId, event });
      },
      onBytes: (at) => setLive((l) => ({ runId, bytesAt: at, eventAt: l?.runId === runId ? l.eventAt : at })),
      onConnection: setConnection,
      onFatal: setError,
      onClosed: async ({ broken }) => {
        const status = await syncRun(runId);
        // Reconnect while the run is running (or its status could not be read). A run that waits for the
        // owner gets one reconnect after a broken connection, to replay what was missed (the server then
        // closes it again); a normal close of a waiting or finished run is the end of this stream.
        const again =
          status === null || status === "running" || (broken && (status === "waiting_user" || status === "waiting_approval"));
        if (!again) setConnection("open"); // a deliberate stop is not a lost connection
        return again;
      },
    });
    return () => controller.abort();
  }, [runId, streamTick, syncRun]);

  // Read the run once when it is attached (the server status is the truth, not the events).
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const atEventId = lastEventRef.current;
    api.getRun(runId).then(
      (fresh) => {
        if (!cancelled) dispatch({ type: "server_run", run: fresh, atEventId });
      },
      () => {
        /* the event stream still drives the view */
      },
    );
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // Fallback for a backend that sends no `run_status`: while the view only *infers* "running", ask the server.
  const inferredRunning = runId !== null && view.status === "running" && view.statusSource !== "event";
  useEffect(() => {
    if (!runId || !inferredRunning) return;
    const timer = setInterval(() => void syncRun(runId), 4000);
    return () => clearInterval(timer);
  }, [runId, inferredRunning, syncRun]);

  const decided = decision && decision.runId === runId ? decision.value : null;
  const status: RunStatus | null = runId ? view.status : null;
  const kind = run?.kind ?? null;
  const steps = useMemo(() => deriveSteps(view, kind, { decided }), [view, kind, decided]);

  const act = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, []);

  /** Delivers an owner message: answers the waiting run, or starts a new one. The text shows at once as `pending`. */
  const deliver = useCallback(
    async (message: string, target: "new" | "existing"): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        if (target === "existing" && runId) {
          try {
            await api.postRunMessage(runId, message);
          } finally {
            await syncRun(runId);
            setStreamTick((t) => t + 1); // the server closed the stream while the run waited: open it again
          }
        } else {
          const created = await api.createRun(botId, message);
          dispatch({ type: "attach", run: created, keepPending: true });
        }
        dispatch({ type: "send_accepted" });
        return true;
      } catch (err) {
        dispatch({ type: "send_failed", error: errorMessage(err) });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [botId, runId, syncRun],
  );

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message) return false;
      const target = runId && (statusRef.current === "waiting_user" || statusRef.current === "waiting_approval") ? "existing" : "new";
      dispatch({ type: "send_started", pending: startPending(message, target, view) });
      return deliver(message, target);
    },
    [deliver, runId, view],
  );

  const resend = useCallback(async () => {
    if (!pending) return false;
    const target =
      pending.target === "existing" && runId && (statusRef.current === "waiting_user" || statusRef.current === "waiting_approval")
        ? "existing"
        : "new";
    dispatch({ type: "send_started", pending: { ...startPending(pending.text, target, view), ts: pending.ts } });
    return deliver(pending.text, target);
  }, [deliver, pending, runId, view]);

  const dismissPending = useCallback(() => dispatch({ type: "pending_cleared" }), []);

  const decide = useCallback(
    async (value: "approved" | "rejected") => {
      if (!runId) return;
      await act(async () => {
        try {
          await (value === "approved" ? api.approveRun(runId) : api.rejectRun(runId));
          setDecision({ runId, value });
        } finally {
          const next = await syncRun(runId);
          // A refusal can return the run to waiting_approval: the decision did not take effect.
          if (next === "waiting_approval") setDecision(null);
          setStreamTick((t) => t + 1); // read the events of the decision (the paused run's stream had closed)
        }
      });
    },
    [act, runId, syncRun],
  );

  const retry = useCallback(async () => {
    if (!runId) return;
    await act(async () => {
      const created = await api.retryRun(runId);
      dispatch({ type: "attach", run: created });
    });
  }, [act, runId]);

  const attach = useCallback((created: AgentRun) => {
    setError(null);
    dispatch({ type: "attach", run: created });
  }, []);

  const approve = useCallback(() => decide("approved"), [decide]);
  const reject = useCallback(() => decide("rejected"), [decide]);

  return {
    loading,
    runId,
    run,
    kind,
    status,
    view,
    steps,
    past,
    loadHistory,
    retryPast,
    decided,
    pending,
    connection,
    lastBytesAt: live && live.runId === runId ? live.bytesAt : null,
    lastEventAt: live && live.runId === runId ? live.eventAt : null,
    busy,
    error,
    clearError: () => setError(null),
    send,
    resend,
    dismissPending,
    approve,
    reject,
    retry,
    attach,
  };
}
