"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api } from "@/lib/api";
import { applyServerStatus, emptyRunView, reduceEvent, viewFromEvents, type RunView } from "@/lib/agent-state";
import { errorMessage } from "@/lib/errors";
import { loadRunEvents, streamRunEvents } from "@/lib/sse";
import type { AgentRun, RawAgentEvent, RunKind, RunStatus } from "@/lib/types";

/** An earlier run of the bot's conversation. Loaded once (its events are replayed), never streamed. */
export interface PastRun {
  run: AgentRun;
  /** null while the run's events are loading (or after a failed load, see `failed`). */
  view: RunView | null;
  failed: boolean;
}

interface State {
  /** The latest run: the one that is streamed live and that the owner acts on. */
  run: AgentRun | null;
  view: RunView;
  /** Every earlier run of the bot, oldest first. */
  past: PastRun[];
}

type Action =
  | { type: "init"; runs: AgentRun[] }
  | { type: "start"; run: AgentRun }
  | { type: "event"; runId: string; event: RawAgentEvent }
  | { type: "server_run"; run: AgentRun; atEventId: number }
  | { type: "past_loaded"; runId: string; events: RawAgentEvent[] }
  | { type: "past_failed"; runId: string }
  | { type: "past_retry"; runId: string };

const initialState: State = { run: null, view: emptyRunView, past: [] };

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
        run: latest,
        view: seededView(latest),
        past: older.reverse().map((run) => ({ run, view: null, failed: false })),
      };
    }
    case "start": {
      // The run that was shown so far moves into the history with the view it already has; a view that
      // never received an event is loaded from the server like any other earlier run.
      const past = state.run
        ? [
            ...state.past,
            { run: state.run, view: state.view.lastEventId > 0 ? state.view : null, failed: false },
          ]
        : state.past;
      return { run: action.run, view: seededView(action.run), past };
    }
    case "event":
      if (action.runId !== state.run?.id) return state;
      return { ...state, view: reduceEvent(state.view, action.event) };
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
  /** Earlier runs of the bot, oldest first: the rest of the conversation history. */
  past: PastRun[];
  /** Loads an earlier run again after a failed load. */
  retryPast: (runId: string) => void;
  /** The owner's own approve/reject for this run, known before the server confirms it. */
  decided: "approved" | "rejected" | null;
  connection: "open" | "reconnecting";
  /** A request (send, approve, reject) is in flight. */
  busy: boolean;
  error: string | null;
  clearError: () => void;
  send: (text: string) => Promise<void>;
  approve: () => Promise<void>;
  reject: () => Promise<void>;
}

/**
 * Owns the Agent tab's data: the bot's whole conversation. The latest run is streamed into a RunView
 * and is the one the owner acts on; earlier runs are loaded once each (their events are replayed and
 * the stream closes, since they are not running) and kept as history. The server decides the latest
 * run's status: it is re-read after every action and whenever the event stream ends. Sending after a
 * finished run starts a new one; the finished run moves into the history.
 */
export function useAgentRun(botId: string): AgentRunController {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<"open" | "reconnecting">("open");
  const [decision, setDecision] = useState<{ runId: string; value: "approved" | "rejected" } | null>(null);
  /** Bumped to (re)start the event stream: after the owner acts on a run whose stream had stopped. */
  const [streamTick, setStreamTick] = useState(0);

  const { run, view, past } = state;
  const runId = run?.id ?? null;
  const lastEventRef = useRef(0);
  useEffect(() => {
    lastEventRef.current = view.lastEventId;
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

  // Load each earlier run once (a few at a time). Loads outlive re-renders and stop when the tab unmounts.
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
    if (!signal || signal.aborted) return;
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
  }, [past]);

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
      onEvent: (event) => dispatch({ type: "event", runId, event }),
      onConnection: setConnection,
      onFatal: setError,
      onClosed: async () => {
        const status = await syncRun(runId);
        // Reconnect only while the run is running (or when its status could not be read).
        return status === null || status === "running";
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

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message) return;
      await act(async () => {
        if (runId && (status === "waiting_user" || status === "waiting_approval")) {
          try {
            await api.postRunMessage(runId, message);
          } finally {
            await syncRun(runId);
            setStreamTick((t) => t + 1); // the stream may have stopped while the run waited
          }
          return;
        }
        const created = await api.createRun(botId, message);
        dispatch({ type: "start", run: created });
      });
    },
    [act, botId, runId, status, syncRun],
  );

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
          setStreamTick((t) => t + 1);
        }
      });
    },
    [act, runId, syncRun],
  );

  const approve = useCallback(() => decide("approved"), [decide]);
  const reject = useCallback(() => decide("rejected"), [decide]);

  return {
    loading,
    runId,
    run,
    kind: run?.kind ?? null,
    status,
    view,
    past,
    retryPast,
    decided,
    connection,
    busy,
    error,
    clearError: () => setError(null),
    send,
    approve,
    reject,
  };
}
