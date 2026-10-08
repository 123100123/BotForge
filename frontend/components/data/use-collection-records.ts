"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { DataRecord } from "@/lib/types";

/** Records are fetched this many at a time (the backend allows up to 200). */
export const PAGE_SIZE = 100;
/** `loadAll` stops here so that a huge collection cannot freeze a page. */
const MAX_AUTO_ROWS = 1000;

export interface CollectionRecords {
  /** null until the first page arrives (or fails). */
  items: DataRecord[] | null;
  total: number;
  error: string | null;
  loadingMore: boolean;
  hasMore: boolean;
  loadMore: () => void;
  /** Re-reads everything loaded so far (after a change). Keeps the old rows on screen meanwhile. */
  reload: () => void;
  /** Applies a changed record to the loaded rows at once (the server copy replaces it on reload). */
  patch: (id: number, change: Partial<DataRecord>) => void;
}

/**
 * The records of one collection, newest first, loaded in pages of 100. `loadAll` keeps loading the next pages
 * (up to 1000 rows) for views that need every row, such as an event's registrations.
 */
export function useCollectionRecords(botId: string, collection: string | null, opts: { loadAll?: boolean } = {}): CollectionRecords {
  const loadAll = opts.loadAll === true;
  const [state, setState] = useState<{ key: string; items: DataRecord[]; total: number } | null>(null);
  const [errorState, setErrorState] = useState<{ key: string; message: string } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [tick, setTick] = useState(0);
  const key = `${botId}:${collection ?? ""}`;
  const latest = useRef<{ key: string; count: number }>({ key, count: 0 });

  useEffect(() => {
    if (!collection) return;
    let cancelled = false;
    (async () => {
      try {
        // A reload covers every row loaded before it, so a person who loaded 300 rows keeps them.
        const want = latest.current.key === key ? Math.max(latest.current.count, PAGE_SIZE) : PAGE_SIZE;
        let items: DataRecord[] = [];
        let total = 0;
        while (true) {
          const page = await api.listRecords(botId, collection, { limit: PAGE_SIZE, offset: items.length });
          if (cancelled) return;
          total = page.total;
          items = [...items, ...page.items];
          const target = loadAll ? Math.min(total, MAX_AUTO_ROWS) : Math.min(total, want);
          if (page.items.length === 0 || items.length >= target) break;
        }
        latest.current = { key, count: items.length };
        setState({ key, items, total });
        setErrorState(null);
      } catch (err) {
        if (!cancelled) setErrorState({ key, message: errorMessage(err) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [botId, collection, key, loadAll, tick]);

  const current = state && state.key === key ? state : null;
  const error = errorState && errorState.key === key ? errorState.message : null;

  const loadMore = useCallback(() => {
    if (!collection || !current || loadingMore) return;
    setLoadingMore(true);
    api
      .listRecords(botId, collection, { limit: PAGE_SIZE, offset: current.items.length })
      .then((page) => {
        setState((s) => {
          if (!s || s.key !== key) return s;
          const seen = new Set(s.items.map((r) => r.id));
          const items = [...s.items, ...page.items.filter((r) => !seen.has(r.id))];
          latest.current = { key, count: items.length };
          return { key, items, total: page.total };
        });
        setErrorState(null);
      })
      .catch((err) => setErrorState({ key, message: errorMessage(err) }))
      .finally(() => setLoadingMore(false));
  }, [botId, collection, current, key, loadingMore]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  const patch = useCallback(
    (id: number, change: Partial<DataRecord>) =>
      setState((s) => (s ? { ...s, items: s.items.map((r) => (r.id === id ? { ...r, ...change } : r)) } : s)),
    [],
  );

  return {
    items: current?.items ?? null,
    total: current?.total ?? 0,
    error,
    loadingMore,
    hasMore: current ? current.items.length < current.total : false,
    loadMore,
    reload,
    patch,
  };
}
