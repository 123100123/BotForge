"use client";

import { useState, type FormEvent } from "react";
import { SendHorizontal } from "lucide-react";
import { AgentTab } from "@/components/agent/agent-tab";
import { Segmented } from "@/components/app/segmented";
import { ErrorNote } from "@/components/app/state-blocks";
import type { WorkspaceTab } from "@/components/app/workspace";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Bot, ChatTurn, ToolCallOut } from "@/lib/types";

type Mode = "change" | "ask";

interface AskTurn extends ChatTurn {
  toolCalls?: ToolCallOut[];
}

/** Ask mode (stub): a plain question and answer thread against api.copilotMessage. W2-FE-COP polishes it. */
function AskPanel({ bot }: { bot: Bot }) {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    const next: AskTurn[] = [...turns, { role: "user", content: text }];
    setTurns(next);
    setDraft("");
    setBusy(true);
    setError(null);
    try {
      const out = await api.copilotMessage(bot.id, {
        messages: next.map(({ role, content }) => ({ role, content })),
      });
      setTurns([...next, { role: "assistant", content: out.reply, toolCalls: out.tool_calls }]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        {turns.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <h3 className="text-base font-semibold">از کسب‌وکارتان بپرسید</h3>
            <p className="max-w-md text-sm leading-7 text-muted-foreground">
              مثلاً «هفتهٔ گذشته چند رزرو داشتیم؟». دستیار از داده‌های ربات پاسخ می‌دهد و چیزی را تغییر نمی‌دهد.
            </p>
          </div>
        )}
        {turns.length > 0 && (
          <ul className="flex flex-col gap-3" aria-live="polite">
            {turns.map((t, i) => (
              <li
                key={i}
                className={
                  t.role === "user"
                    ? "max-w-[85%] self-start rounded-lg bg-primary/10 p-3 text-sm leading-7"
                    : "max-w-[85%] self-end rounded-lg bg-muted p-3 text-sm leading-7"
                }
              >
                <p className="whitespace-pre-wrap">{t.content}</p>
                {t.toolCalls && t.toolCalls.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-0.5 border-t pt-2 text-xs text-muted-foreground">
                    {t.toolCalls.map((c, j) => (
                      <li key={j}>{c.summary}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
        {error && <ErrorNote>{error}</ErrorNote>}
        <form onSubmit={submit} className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={2}
            placeholder="سؤال خود را بنویسید…"
            aria-label="پرسش از کسب‌وکار"
            disabled={busy}
            className="min-h-0 flex-1"
          />
          <Button type="submit" disabled={busy || draft.trim() === ""}>
            <SendHorizontal className="rtl:-scale-x-100" />
            {busy ? "در حال پاسخ…" : "ارسال"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

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
      {mode === "ask" && <AskPanel bot={bot} />}
    </div>
  );
}
