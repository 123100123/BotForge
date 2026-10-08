"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useOpenSection } from "@/components/app/shell/use-open-section";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/lib/use-media-query";
import { AskPanel } from "./ask-panel";
import { useAskThread } from "./use-ask-thread";

/**
 * The global assistant (D06): a panel from the end edge (left in RTL) on every page of a business, opened
 * from the top bar, the mobile tab bar or Ctrl/⌘+K. The conversation lives here, in the bot layout, so it
 * survives closing the panel and navigating. Other pages open it pre-filled with `useAssistant().open(text)`.
 */
export interface AssistantApi {
  isOpen: boolean;
  /** Opens the panel; `prefill` replaces the question box text (not sent). */
  open: (prefill?: string) => void;
  close: () => void;
  toggle: () => void;
}

const AssistantContext = createContext<AssistantApi | null>(null);

export function useAssistant(): AssistantApi {
  const ctx = useContext(AssistantContext);
  if (!ctx) throw new Error("useAssistant must be used inside AssistantProvider (the bot layout)");
  return ctx;
}

/** Width of the panel on wide screens; the shell reserves it at ≥1280px so the panel sits beside content. */
export const ASSISTANT_WIDTH_CLASS = "sm:w-[420px]";
const INPUT_ID = "assistant-question";

export function AssistantProvider({ botId, children }: { botId: string; children: ReactNode }) {
  const thread = useAskThread(botId);
  const { setDraft } = thread;
  const [isOpen, setOpen] = useState(false);
  const fullScreen = useMediaQuery("(max-width: 639.98px)");
  const openSection = useOpenSection();

  const open = useCallback(
    (prefill?: string) => {
      if (prefill !== undefined) setDraft(prefill);
      setOpen(true);
      // Already open: move focus to the question box anyway.
      requestAnimationFrame(() => document.getElementById(INPUT_ID)?.focus());
    },
    [setDraft],
  );
  const close = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => setOpen((o) => !o), []);

  // Ctrl+K / ⌘+K anywhere. `code` keeps it working with a Persian keyboard layout (where K types «ن»).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.code === "KeyK" || e.key.toLowerCase() === "k")) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const api = useMemo<AssistantApi>(() => ({ isOpen, open, close, toggle }), [isOpen, open, close, toggle]);

  return (
    <AssistantContext.Provider value={api}>
      {children}
      {/* Non-modal on tablet and desktop: the page stays usable (and navigable) while the panel is open. */}
      <Sheet open={isOpen} onOpenChange={setOpen} modal={fullScreen}>
        <SheetContent
          side="end"
          className={`w-full max-w-full gap-0 overflow-hidden p-0 max-sm:rounded-none max-sm:border-0 ${ASSISTANT_WIDTH_CLASS} sm:max-w-[calc(100%-2rem)]`}
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            document.getElementById(INPUT_ID)?.focus();
          }}
          // Clicking the page keeps the panel open; Esc or the close button closes it.
          onInteractOutside={(e) => {
            if (!fullScreen) e.preventDefault();
          }}
        >
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle>دستیار</SheetTitle>
            <SheetDescription>
              از کسب‌وکارتان بپرسید یا تغییری را درخواست کنید؛ تا تأیید شما چیزی عوض نمی‌شود.
            </SheetDescription>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
            <AskPanel
              thread={thread}
              inputId={INPUT_ID}
              onOpenCapabilities={() => {
                if (fullScreen) setOpen(false);
                openSection("capabilities");
              }}
            />
          </div>
        </SheetContent>
      </Sheet>
    </AssistantContext.Provider>
  );
}
