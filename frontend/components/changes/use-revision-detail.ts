"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { RevisionDetail } from "@/lib/types";

/**
 * One version's detail (spec diff, scenarios, test report). `refreshKey` re-reads it when something that
 * changes the version happens (a run reaching approval, a rollback). `reload` re-reads it on demand.
 * A failed read leaves `detail` null and sets `error`.
 */
export function useRevisionDetail(revisionId: string | null, refreshKey: string | number = 0) {
  const [state, setState] = useState<{ id: string; detail: RevisionDetail | null; error: string | null } | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!revisionId) return;
    let cancelled = false;
    api.getRevision(revisionId).then(
      (detail) => !cancelled && setState({ id: revisionId, detail, error: null }),
      (err) => !cancelled && setState({ id: revisionId, detail: null, error: errorMessage(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [revisionId, refreshKey, tick]);

  const current = state && state.id === revisionId ? state : null;
  return {
    detail: current?.detail ?? null,
    error: current?.error ?? null,
    /** No answer yet for this version. */
    loading: revisionId !== null && current === null,
    reload,
    /** Replace the cached detail (after running tests). */
    set: (detail: RevisionDetail) => setState({ id: detail.id, detail, error: null }),
  };
}
