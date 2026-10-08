"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/errors";
import { buildNav, firstOperationsHref, type NavGroup } from "@/lib/nav";
import type { Bot, CapabilityOut, DataCollection } from "@/lib/types";

/**
 * The business (= the bot) every page under /bots/[id] works on, loaded once by the bot layout:
 * the bot itself, its data collections (from the active revision) and its capabilities. The navigation
 * is derived from them (lib/nav.ts), so enabling a capability or activating a version updates the sidebar.
 */
export interface BusinessContextValue {
  bot: Bot;
  /** Collections of the active revision; empty while loading and for a business with no active version. */
  collections: DataCollection[];
  /** Every capability (enabled or not), flattened from the categories. */
  capabilities: CapabilityOut[];
  /** "loading" until collections and capabilities have been read once for the current active revision. */
  dataStatus: "loading" | "ready";
  /** The grouped navigation (lib/nav.ts buildNav). */
  nav: NavGroup[];
  /** The first Operations route, or null. */
  operationsHref: string | null;
  /** Re-reads the bot, its collections and its capabilities (after a version or capability changed). */
  reload: () => void;
  /** Re-reads only the bot (name, status, Telegram handle, active version). */
  reloadBot: () => void;
}

const EMPTY_COLLECTIONS: DataCollection[] = [];
const EMPTY_CAPABILITIES: CapabilityOut[] = [];

const BusinessContext = createContext<BusinessContextValue | null>(null);

export function useBusiness(): BusinessContextValue {
  const ctx = useContext(BusinessContext);
  if (!ctx) throw new Error("useBusiness must be used inside the bot layout (BusinessProvider)");
  return ctx;
}

/** The business context when rendered under /bots/[id], otherwise null (shared components). */
export function useOptionalBusiness(): BusinessContextValue | null {
  return useContext(BusinessContext);
}

export type BusinessLoad =
  | { state: "loading" }
  | { state: "not_found" }
  | { state: "error"; message: string }
  | { state: "ready"; value: BusinessContextValue };

interface DataState {
  /** bot id + active revision + reload tick the data was read for. */
  key: string;
  collections: DataCollection[];
  capabilities: CapabilityOut[];
}

/**
 * Loads the business for `botId`. The bot is required (its failure is the page's failure); collections and
 * capabilities are best-effort (a business without an active version has no collections).
 */
export function useBusinessLoader(botId: string): { load: BusinessLoad; retry: () => void } {
  const [bot, setBot] = useState<{ botId: string; bot: Bot } | null>(null);
  const [botError, setBotError] = useState<{ botId: string; notFound: boolean; message: string } | null>(null);
  const [botTick, setBotTick] = useState(0);
  const [data, setData] = useState<DataState | null>(null);
  const [dataTick, setDataTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.getBot(botId).then(
      (loaded) => {
        if (cancelled) return;
        setBot({ botId, bot: loaded });
        setBotError(null);
      },
      (err) => {
        if (cancelled) return;
        const notFound = err instanceof ApiError && (err.status === 404 || err.status === 403);
        setBotError({ botId, notFound, message: errorMessage(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [botId, botTick]);

  const current = bot && bot.botId === botId ? bot.bot : null;
  const revision = current?.active_revision_id ?? null;
  const hasBot = current !== null;
  const dataKey = `${botId}:${revision ?? ""}:${dataTick}`;

  useEffect(() => {
    if (!hasBot) return;
    let cancelled = false;
    const collections = revision
      ? api.getDataOverview(botId).then(
          (o) => o.collections,
          () => [] as DataCollection[],
        )
      : Promise.resolve([] as DataCollection[]);
    const capabilities = api.listCapabilities(botId).then(
      (list) => list.categories.flatMap((c) => c.capabilities),
      () => [] as CapabilityOut[],
    );
    void Promise.all([collections, capabilities]).then(([cols, caps]) => {
      if (!cancelled) setData({ key: dataKey, collections: cols, capabilities: caps });
    });
    return () => {
      cancelled = true;
    };
  }, [botId, revision, hasBot, dataKey]);

  const reloadBot = useCallback(() => setBotTick((t) => t + 1), []);
  const reload = useCallback(() => {
    setBotTick((t) => t + 1);
    setDataTick((t) => t + 1);
  }, []);

  // A reload keeps the previous result until the new one arrives, so the sidebar does not flicker.
  const collections = data?.collections ?? EMPTY_COLLECTIONS;
  const capabilities = data?.capabilities ?? EMPTY_CAPABILITIES;
  const dataStatus = data ? "ready" : "loading";

  const nav = useMemo(() => buildNav(collections, capabilities, botId), [collections, capabilities, botId]);

  const value = useMemo<BusinessContextValue | null>(
    () =>
      current
        ? {
            bot: current,
            collections,
            capabilities,
            dataStatus,
            nav,
            operationsHref: firstOperationsHref(nav),
            reload,
            reloadBot,
          }
        : null,
    [current, collections, capabilities, dataStatus, nav, reload, reloadBot],
  );

  let load: BusinessLoad;
  if (value) load = { state: "ready", value };
  else if (botError && botError.botId === botId) {
    load = botError.notFound ? { state: "not_found" } : { state: "error", message: botError.message };
  } else load = { state: "loading" };

  const retry = useCallback(() => {
    setBotError(null);
    setBotTick((t) => t + 1);
  }, []);

  return { load, retry };
}

export function BusinessProvider({ value, children }: { value: BusinessContextValue; children: ReactNode }) {
  return <BusinessContext.Provider value={value}>{children}</BusinessContext.Provider>;
}
