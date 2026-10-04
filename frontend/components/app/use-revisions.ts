"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { RevisionSummary } from "@/lib/types";

/** Revisions of a bot, newest first. `reload` refetches them (for example after a rollback or a test run). */
export function useRevisions(botId: string, activeRevisionId: string | null) {
  const [revisions, setRevisions] = useState<RevisionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  // The active revision changing (an approval in the Agent tab, a rollback) also changes the list.
  useEffect(() => {
    let cancelled = false;
    api.listRevisions(botId).then(
      (list) => {
        if (cancelled) return;
        setRevisions(list);
        setError(null);
      },
      (err) => !cancelled && setError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [botId, activeRevisionId, tick]);

  return { revisions, error, reload };
}
