"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useBusiness } from "@/components/app/business-context";
import { ConsequenceSheet, type ToggleDone } from "@/components/capabilities/consequence-sheet";
import { dismissToast, toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { CapabilityCategoryOut, CapabilityOut } from "@/lib/types";

/** What the last toggle did; shown as a persistent note with a link to Changes (toasts cannot carry a link). */
export interface ToggleNotice {
  text: string;
  revisionNumber: number | null;
}

interface CapabilitiesContextValue {
  /** Null until the first read; check `error` first. */
  categories: CapabilityCategoryOut[] | null;
  error: string | null;
  all: CapabilityOut[];
  byId: Map<string, CapabilityOut>;
  /** Re-reads the list (also after a failed first read). */
  refresh: () => Promise<void>;
  /** Replaces one capability with its server copy (after a config save). */
  patch: (updated: CapabilityOut) => void;
  /** Opens the consequence sheet: dry-run first, nothing changes until the owner confirms. */
  requestToggle: (cap: CapabilityOut) => void;
  notice: ToggleNotice | null;
  dismissNotice: () => void;
}

const CapabilitiesContext = createContext<CapabilitiesContextValue | null>(null);

export function useCapabilities(): CapabilitiesContextValue {
  const ctx = useContext(CapabilitiesContext);
  if (!ctx) throw new Error("useCapabilities must be used inside CapabilitiesProvider");
  return ctx;
}

const NO_CAPS: CapabilityOut[] = [];

/**
 * Loads the capability list for the Capability Center routes (list and detail share it through the
 * route layout) and owns the consequence sheet, so a switch or a button anywhere opens the same flow.
 */
export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const { bot, reload } = useBusiness();
  const botId = bot.id;
  const [state, setState] = useState<{ botId: string; categories: CapabilityCategoryOut[] | null; error: string | null } | null>(null);
  const [notice, setNotice] = useState<ToggleNotice | null>(null);
  /** The control that opened the sheet; focus goes back to it when the sheet closes. */
  const opener = useRef<HTMLElement | null>(null);
  /** The result toast of the last toggle; it would sit on top of the next sheet's buttons, so opening a sheet dismisses it. */
  const lastToast = useRef<string | null>(null);
  const [sheet, setSheet] = useState<{ cap: CapabilityOut; nonce: number; open: boolean } | null>(null);

  const fetchList = useCallback(async () => {
    try {
      const list = await api.listCapabilities(botId);
      setState({ botId, categories: list.categories.filter((c) => c.capabilities.length > 0), error: null });
    } catch (err) {
      // A failed re-read keeps the list that is already shown.
      setState((prev) => (prev && prev.botId === botId && prev.categories ? prev : { botId, categories: null, error: errorMessage(err) }));
    }
  }, [botId]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  const current = state && state.botId === botId ? state : null;
  const categories = current?.categories ?? null;
  const all = useMemo(() => (categories ? categories.flatMap((c) => c.capabilities) : NO_CAPS), [categories]);
  const byId = useMemo(() => new Map(all.map((c) => [c.id, c])), [all]);

  const refresh = useCallback(async () => {
    setState(null);
    await fetchList();
  }, [fetchList]);

  const patch = useCallback(
    (updated: CapabilityOut) => {
      setState((prev) =>
        prev && prev.categories
          ? {
              ...prev,
              categories: prev.categories.map((c) => ({
                ...c,
                capabilities: c.capabilities.map((x) => (x.id === updated.id ? updated : x)),
              })),
            }
          : prev,
      );
      // The navigation follows configuration too (for example reminders change what Events shows).
      reload();
    },
    [reload],
  );

  const requestToggle = useCallback((cap: CapabilityOut) => {
    if (lastToast.current) dismissToast(lastToast.current);
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSheet((prev) => ({ cap, nonce: (prev?.nonce ?? 0) + 1, open: true }));
  }, []);

  const closeSheet = useCallback(() => setSheet((prev) => (prev ? { ...prev, open: false } : prev)), []);

  const handleDone = useCallback(
    (done: ToggleDone) => {
      closeSheet();
      const verb = done.action === "enable" ? "روشن" : "خاموش";
      const text =
        done.revisionNumber !== null
          ? `«${done.capabilityName}» ${verb} شد. نسخهٔ ${fa(done.revisionNumber)} ساخته و فعال شد.`
          : `«${done.capabilityName}» ${verb} شد.`;
      setNotice({ text, revisionNumber: done.revisionNumber });
      lastToast.current = toast({ title: done.message || text, description: done.revisionNumber !== null ? text : undefined, tone: "success" });
      // Re-read quietly (no flash of the loading state), then let the navigation catch up.
      void fetchList();
      reload();
    },
    [closeSheet, fetchList, reload],
  );

  const value = useMemo<CapabilitiesContextValue>(
    () => ({
      categories,
      error: current?.error ?? null,
      all,
      byId,
      refresh,
      patch,
      requestToggle,
      notice,
      dismissNotice: () => setNotice(null),
    }),
    [categories, current?.error, all, byId, refresh, patch, requestToggle, notice],
  );

  return (
    <CapabilitiesContext.Provider value={value}>
      {children}
      {sheet && (
        <ConsequenceSheet
          key={sheet.nonce}
          botId={botId}
          cap={sheet.cap}
          byId={byId}
          open={sheet.open}
          onClose={closeSheet}
          returnFocusTo={opener}
          onDone={handleDone}
        />
      )}
    </CapabilitiesContext.Provider>
  );
}
