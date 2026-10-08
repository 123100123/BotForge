"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api } from "@/lib/api";
import { applyServerStatus, emptyRunView, reduceEvent, type RunView } from "@/lib/agent-state";
import { errorMessage } from "@/lib/errors";
import { streamRunEvents } from "@/lib/sse";
import type { AgentRun, RawAgentEvent, RunKind, RunStatus } from "@/lib/types";

interface State {
  runId: string | null;
  view: RunView;
}

type Action =
  | { type: "attach"; runId: string | null; status?: RunStatus }
  | { type: "event"; runId: string; event: RawAgentEvent }
  | { type: "server_status"; runId: string; status: RunStatus; atEventId: number };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "attach":
      return {
        runId: action.runId,
        view: action.status ? { ...emptyRunView, status: action.status, statusSource: "server" } : emptyRunView,
      };
    case "event":
      if (action.runId !== state.runId) return state;
      return { ...state, view: reduceEvent(state.view, action.event) };
    case "server_status":
      if (action.runId !== state.runId) return state;
      return { ...state, view: applyServerStatus(state.view, action.status, action.atEventId) };
  }
}

export interface AgentRunController {
  /** True until the bot's latest run (if any) has been looked up. */
  loading: boolean;
  runId: string | null;
  kind: RunKind | null;
  /** The run's status: a `run_status` event or the server's answer to GET /runs/{id}; inferred from events only as a fallback. */
  status: RunStatus | null;
  view: RunView;
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
  /** Shows a run created elsewhere (for example a capability handoff) and streams its events. */
  attach: (run: AgentRun) => void;
}

/**
 * Owns the Agent tab's data: finds the bot's latest run, streams its events into a RunView, and
 * exposes the owner's actions. The server decides the run's status: it is re-read after every
 * action and whenever the event stream ends. Only the latest run is shown; sending after a finished
 * run starts a new one.
 */
export function useAgentRun(botId: string): AgentRunController {
  const [state, dispatch] = useReducer(reducer, { runId: null, view: emptyRunView });
  const [serverRun, setServerRun] = useState<AgentRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<"open" | "reconnecting">("open");
  const [decision, setDecision] = useState<{ runId: string; value: "approved" | "rejected" } | null>(null);
  /** Bumped to (re)start the event stream: after the owner acts on a run whose stream had stopped. */
  const [streamTick, setStreamTick] = useState(0);

  const { runId, view } = state;
  const lastEventRef = useRef(0);
  useEffect(() => {
    lastEventRef.current = view.lastEventId;
  });

  /** Reads the run from the server and takes its status as the truth. Returns that status. */
  const syncRun = useCallback(async (id: string): Promise<RunStatus | null> => {
    const atEventId = lastEventRef.current;
    try {
      const fresh = await api.getRun(id);
      setServerRun(fresh);
      dispatch({ type: "server_status", runId: id, status: fresh.status, atEventId });
      return fresh.status;
    } catch {
      return null;
    }
  }, []);

  // Find the latest run once per bot.
  useEffect(() => {
    let cancelled = false;
    api.listRuns(botId).then(
      (runs) => {
        if (cancelled) return;
        const latest = [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
        setServerRun(latest);
        dispatch({ type: "attach", runId: latest?.id ?? null, status: latest?.status });
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

  // Stream the attached run. When the stream ends, the server's status says whether to reconnect.
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
        if (cancelled) return;
        setServerRun(fresh);
        dispatch({ type: "server_status", runId, status: fresh.status, atEventId });
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

  const current = serverRun && serverRun.id === runId ? serverRun : null;
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
        const run = await api.createRun(botId, message);
        setServerRun(run);
        dispatch({ type: "attach", runId: run.id, status: run.status });
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

  const attach = useCallback((run: AgentRun) => {
    setServerRun(run);
    setError(null);
    dispatch({ type: "attach", runId: run.id, status: run.status });
  }, []);

  const approve = useCallback(() => decide("approved"), [decide]);
  const reject = useCallback(() => decide("rejected"), [decide]);

  return {
    loading,
    runId,
    kind: current?.kind ?? null,
    status,
    view,
    decided,
    connection,
    busy,
    error,
    clearError: () => setError(null),
    send,
    approve,
    reject,
    attach,
  };
}
