"use client";

import { MessageCircleQuestion, Search } from "lucide-react";
import { AccountMenu } from "@/components/app/account-menu";
import { useBusiness } from "@/components/app/business-context";
import { ThemeMenu } from "@/components/app/theme-menu";
import { useAssistant } from "@/components/copilot/assistant-provider";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { useIsApplePlatform } from "@/lib/use-media-query";

/** The search-shaped entry to the assistant, with its shortcut. */
function AssistantSearchButton() {
  const assistant = useAssistant();
  const apple = useIsApplePlatform();
  return (
    <button
      type="button"
      onClick={() => assistant.open()}
      aria-haspopup="dialog"
      aria-expanded={assistant.isOpen}
      aria-keyshortcuts={apple ? "Meta+K" : "Control+K"}
      className="hidden h-9 min-w-0 flex-1 items-center gap-2 rounded-sm border border-border-strong bg-surface-raised px-3 text-start text-small text-fg-muted transition-colors duration-fast hover:border-brand hover:text-fg sm:flex sm:max-w-md"
    >
      <Search className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
      <span className="min-w-0 flex-1 truncate">از کسب‌وکارتان بپرسید…</span>
      <span className="flex shrink-0 items-center gap-1" dir="ltr" aria-hidden>
        <Kbd>{apple ? "⌘" : "Ctrl"}</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  );
}

/**
 * 56px sticky bar above the content. ≥640px: the assistant entry, then theme and account at the end edge
 * (the business name too below 1024px, where the sidebar is a rail). <640px: business name and assistant.
 */
export function TopBar() {
  const { bot } = useBusiness();
  const assistant = useAssistant();
  return (
    <header className="sticky top-0 z-sticky flex h-14 shrink-0 items-center gap-3 border-b bg-page px-4 sm:px-6">
      <p className="min-w-0 max-w-[40%] truncate text-body font-semibold text-fg max-sm:max-w-none max-sm:flex-1 lg:hidden">{bot.name}</p>
      <AssistantSearchButton />
      <div className="ms-auto flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="icon" className="size-11 sm:hidden" aria-label="دستیار" onClick={() => assistant.open()}>
          <MessageCircleQuestion className="size-5" strokeWidth={1.75} />
        </Button>
        <div className="hidden items-center gap-1 sm:flex">
          <ThemeMenu />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
