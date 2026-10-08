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
  type PendingOwnerMessage,
  type RunStep,
  type RunView,
} from "@/lib/agent-state";
import { errorMessage } from "@/lib/errors";
import { streamRunEvents } from "@/lib/sse";
import type { AgentRun, RawAgentEvent, RunKind, RunStatus } from "@/lib/types";

interface State {
  runId: string | null;
  view: RunView;
  /** The owner's message that is not in the feed yet. */
  pending: PendingOwnerMessage | null;
}

type Action =
  | { type: "attach"; runId: string | null; status?: RunStatus; keepPending?: boolean }
  | { type: "event"; runId: string; event: RawAgentEvent }
  | { type: "server_status"; runId: string; status: RunStatus; atEventId: number }
  | { type: "send_started"; pending: PendingOwnerMessage }
  | { type: "send_accepted" }
  | { type: "send_failed"; error: string }
  | { type: "pending_cleared" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "attach": {
      const view = action.status ? { ...emptyRunView, status: action.status, statusSource: "server" as const } : emptyRunView;
      // A new run starts with an empty feed: the pending message (sent to create it) waits for its event there.
      const pending = action.keepPending && state.pending ? { ...state.pending, ownerCount: 0 } : null;
      return { runId: action.runId, view, pending };
    }
    case "event": {
      if (action.runId !== state.runId) return state;
      const view = reduceEvent(state.view, action.event);
      return { ...state, view, pending: reconcilePending(state.pending, view) };
    }
    case "server_status":
      if (action.runId !== state.runId) return state;
      return { ...state, view: applyServerStatus(state.view, action.status, action.atEventId) };
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

export interface AgentRunController {
  /** True until the bot's latest run (if any) has been looked up. */
  loading: boolean;
  runId: string | null;
  kind: RunKind | null;
  /** The run's status: a `run_status` event or the server's answer to GET /runs/{id}; inferred from events only as a fallback. */
  status: RunStatus | null;
  view: RunView;
  /** The ordered steps of the run (pending ones included), derived from the flow's phase sequence. */
  steps: RunStep[];
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
 * Owns the Agent tab's data: finds the bot's latest run, streams its events into a RunView, and
 * exposes the owner's actions. The server decides the run's status: it is re-read after every
 * action and whenever the event stream ends. Only the latest run is shown; sending after a finished
 * run starts a new one.
 */
export function useAgentRun(botId: string): AgentRunController {
  const [state, dispatch] = useReducer(reducer, { runId: null, view: emptyRunView, pending: null });
  const [serverRun, setServerRun] = useState<AgentRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<"open" | "reconnecting">("open");
  /** Stream liveness of one run; ignored once another run is attached. */
  const [live, setLive] = useState<{ runId: string; bytesAt: number | null; eventAt: number | null } | null>(null);
  const [decision, setDecision] = useState<{ runId: string; value: "approved" | "rejected" } | null>(null);
  /** Bumped to (re)start the event stream: after the owner acts on a run whose stream had stopped. */
  const [streamTick, setStreamTick] = useState(0);

  const { runId, view, pending } = state;
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
      onEvent: (event) => {
        setLive((l) => ({ runId, bytesAt: l?.runId === runId ? l.bytesAt : null, eventAt: Date.now() }));
        dispatch({ type: "event", runId, event });
      },
      onBytes: (at) => setLive((l) => ({ runId, bytesAt: at, eventAt: l?.runId === runId ? l.eventAt : at })),
      onConnection: setConnection,
      onFatal: setError,
      onClosed: async ({ broken }) => {
        const status = await syncRun(runId);
        // Reconnect while the run is running (or its status could not be read), and after a broken connection
        // while it waits for the owner (the server keeps a waiting run's stream open).
        return status === null || status === "running" || (broken && (status === "waiting_user" || status === "waiting_approval"));
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
  const kind = current?.kind ?? null;
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
            setStreamTick((t) => t + 1); // the stream may have stopped while the run waited
          }
        } else {
          const run = await api.createRun(botId, message);
          setServerRun(run);
          dispatch({ type: "attach", runId: run.id, status: run.status, keepPending: true });
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
          setStreamTick((t) => t + 1);
        }
      });
    },
    [act, runId, syncRun],
  );

  const retry = useCallback(async () => {
    if (!runId) return;
    await act(async () => {
      const run = await api.retryRun(runId);
      setServerRun(run);
      dispatch({ type: "attach", runId: run.id, status: run.status });
    });
  }, [act, runId]);

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
    kind,
    status,
    view,
    steps,
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
