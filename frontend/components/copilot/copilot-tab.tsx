"use client";

import { useState } from "react";
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
    <div className="flex flex-col gap-4">
      <Segmented<Mode>
        label="حالت دستیار"
        value={mode}
        onChange={setMode}
        options={[
          { value: "change", label: "تغییر ربات" },
          { value: "ask", label: "پرسش از کسب‌وکار" },
        ]}
      />
      <div hidden={mode !== "change"}>
        <AgentTab bot={bot} onBotChanged={onBotChanged} onOpenTab={onOpenTab} />
      </div>
      {/* Mounted only in ask mode, but remounted per bot; the thread resets when leaving the mode. */}
      {mode === "ask" && <AskPanel key={bot.id} bot={bot} onOpenTab={onOpenTab} />}
    </div>
  );
}
