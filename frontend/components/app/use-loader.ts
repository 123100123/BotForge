"use client";

import { useEffect, useState } from "react";
import { errorMessage } from "@/lib/errors";

/**
 * Loads data once per `key` (the load function is called again only when `key` changes) and reports
 * `{ data, error }`; both are null while loading. Results of a previous key are never shown.
 */
export function useLoader<T>(load: () => Promise<T>, key: string): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    load().then(
      (data) => {
        if (!cancelled) setState({ key, data, error: null });
      },
      (err) => {
        if (!cancelled) setState({ key, data: null, error: errorMessage(err) });
      },
    );
    return () => {
      cancelled = true;
    };
    // `load` is a fresh closure every render; `key` identifies what it loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = state && state.key === key ? state : null;
  return { data: current?.data ?? null, error: current?.error ?? null };
}
