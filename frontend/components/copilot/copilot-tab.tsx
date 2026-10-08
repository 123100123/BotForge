"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { AgentTab } from "@/components/agent/agent-tab";
import { Segmented } from "@/components/app/segmented";
import type { WorkspaceTab } from "@/components/app/workspace";
import { AskPanel } from "@/components/copilot/ask-panel";
import type { Bot } from "@/lib/types";

type Mode = "change" | "ask";

/**
 * Copilot section: "change the bot" (the existing agent flow) and "ask the business".
 * AgentTab stays mounted in both modes (only hidden) so its event stream and state survive.
 */
export function CopilotTab({
  bot,
  onBotChanged,
  onOpenTab,
}: {
  bot: Bot;
  onBotChanged: () => void;
  onOpenTab: (tab: WorkspaceTab) => void;
}) {
  const [mode, setMode] = useState<Mode>("change");

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="relative overflow-hidden rounded-[1.75rem] border border-primary/15 bg-gradient-to-bl from-primary/12 via-card to-accent/10 p-5 shadow-sm sm:p-7">
        <div className="pointer-events-none absolute -start-12 -top-20 size-48 rounded-full bg-primary/10 blur-3xl" aria-hidden />
        <div className="relative flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
          <div className="max-w-2xl">
            <span className="mb-3 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">
              <Sparkles className="size-3.5" /> دستیار هوشمند
            </span>
            <h2 className="text-xl font-bold tracking-tight sm:text-2xl">ایده‌تان را به ربات تبدیل کنید</h2>
            <p className="mt-2 text-sm leading-7 text-muted-foreground">ربات را با زبان خودتان بسازید و تغییر دهید، یا از داده‌های کسب‌وکارتان پاسخ بگیرید.</p>
          </div>
          <div className="rounded-2xl border border-border/70 bg-card/80 p-1.5 shadow-sm">
            <Segmented<Mode>
              label="حالت دستیار"
              value={mode}
              onChange={setMode}
              options={[
                { value: "change", label: "ساخت و تغییر" },
                { value: "ask", label: "پرسش از داده‌ها" },
              ]}
            />
          </div>
        </div>
      </header>
      <div className="min-w-0" hidden={mode !== "change"}>
        <AgentTab bot={bot} onBotChanged={onBotChanged} onOpenTab={onOpenTab} />
      </div>
      {/* Mounted only in ask mode, but remounted per bot; the thread resets when leaving the mode. */}
      {mode === "ask" && <AskPanel key={bot.id} bot={bot} onOpenTab={onOpenTab} />}
    </div>
  );
}
