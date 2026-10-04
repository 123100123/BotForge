"use client";

import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { api } from "@/lib/api";
import { emptyRunView, reduceEvent, type RunView } from "@/lib/agent-state";
import { errorMessage } from "@/lib/errors";
import { streamRunEvents } from "@/lib/sse";
import { isTerminal, type AgentRun, type RawAgentEvent, type RunKind, type RunStatus } from "@/lib/types";

interface State {
  runId: string | null;
  view: RunView;
}

type Action =
  | { type: "attach"; runId: string | null }
  | { type: "event"; runId: string; event: RawAgentEvent };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "attach":
      return { runId: action.runId, view: emptyRunView };
    case "event":
      if (action.runId !== state.runId) return state;
      return { ...state, view: reduceEvent(state.view, action.event) };
  }
}

export interface AgentRunController {
  /** True until the bot's latest run (if any) has been looked up. */
  loading: boolean;
  runId: string | null;
  kind: RunKind | null;
  status: RunStatus | null;
  view: RunView;
  /** The owner's own approve/reject for this run, known before the stream reports it. */
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
 * Owns the Agent tab's data: finds the bot's latest run, streams its events into a RunView, and
 * exposes the owner's actions. Only the latest run is shown; sending after a finished run starts a new one.
 */
export function useAgentRun(botId: string): AgentRunController {
  const [state, dispatch] = useReducer(reducer, { runId: null, view: emptyRunView });
  const [serverRun, setServerRun] = useState<AgentRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<"open" | "reconnecting">("open");
  const [decision, setDecision] = useState<{ runId: string; value: "approved" | "rejected" } | null>(null);

  const { runId, view } = state;

  // Find the latest run once per bot.
  useEffect(() => {
    let cancelled = false;
    api.listRuns(botId).then(
      (runs) => {
        if (cancelled) return;
        const latest = [...runs].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
        setServerRun(latest);
        dispatch({ type: "attach", runId: latest?.id ?? null });
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

  // Stream the attached run. The server replays from the first event (or from Last-Event-ID on reconnect).
  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    void streamRunEvents(runId, {
      signal: controller.signal,
      onEvent: (event) => dispatch({ type: "event", runId, event }),
      onConnection: setConnection,
      onFatal: setError,
    });
    return () => controller.abort();
  }, [runId]);

  // Re-read the run's server-side status whenever the stream-derived status changes (and on demand).
  const [refreshTick, setRefreshTick] = useState(0);
  const refreshRun = useCallback(() => setRefreshTick((t) => t + 1), []);
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    api.getRun(runId).then(
      (fresh) => {
        if (!cancelled) setServerRun(fresh);
      },
      () => {
        /* the event stream still drives the view */
      },
    );
    return () => {
      cancelled = true;
    };
  }, [runId, view.status, refreshTick]);

  const current = serverRun && serverRun.id === runId ? serverRun : null;
  const decided = decision && decision.runId === runId ? decision.value : null;
  const status: RunStatus | null = useMemo(() => {
    if (!runId) return null;
    if (current && isTerminal(current.status)) return current.status;
    // Between the owner's click and the stream's next event the run is no longer waiting for approval.
    if (decided && view.status === "waiting_approval") return decided === "approved" ? "running" : "rejected";
    return view.status;
  }, [runId, current, view.status, decided]);

  const act = useCallback(async (fn: () => Promise<AgentRun | null>) => {
    setBusy(true);
    setError(null);
    try {
      const run = await fn();
      if (run) {
        setServerRun(run);
        dispatch({ type: "attach", runId: run.id });
      }
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
          await api.postRunMessage(runId, message);
          return null;
        }
        return api.createRun(botId, message);
      });
    },
    [act, botId, runId, status],
  );

  const approve = useCallback(async () => {
    if (!runId) return;
    await act(async () => {
      await api.approveRun(runId);
      setDecision({ runId, value: "approved" });
      refreshRun();
      return null;
    });
  }, [act, runId, refreshRun]);

  const reject = useCallback(async () => {
    if (!runId) return;
    await act(async () => {
      await api.rejectRun(runId);
      setDecision({ runId, value: "rejected" });
      refreshRun();
      return null;
    });
  }, [act, runId, refreshRun]);

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
  };
}
