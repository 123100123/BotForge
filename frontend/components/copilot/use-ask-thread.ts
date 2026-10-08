"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/errors";
import type { ChatTurn, CopilotMessageOut, ToolCallOut } from "@/lib/types";

/** Only the most recent turns are sent, so a long conversation does not grow every request. */
export const HISTORY_LIMIT = 12;

export interface AskTurn extends ChatTurn {
  toolCalls?: ToolCallOut[];
  usage?: Record<string, unknown>;
}

export type AskFailure = { kind: "disabled" | "limit" | "unavailable" | "other"; message: string };

function classify(err: unknown): AskFailure {
  if (err instanceof ApiError) {
    if (err.status === 409 && err.code === "capability_disabled") {
      return { kind: "disabled", message: "برای پاسخ به این پرسش، قابلیت مربوط به آن در ربات فعال نیست." };
    }
    if (err.status === 429) {
      return { kind: "limit", message: "سقف پرسش‌های دستیار برای الان پر شده است؛ کمی بعد دوباره امتحان کنید." };
    }
    if (err.status === 503) return { kind: "unavailable", message: "دستیار در دسترس نیست" };
  }
  return { kind: "other", message: errorMessage(err) };
}

export interface AskThread {
  turns: AskTurn[];
  draft: string;
  setDraft: (text: string) => void;
  busy: boolean;
  failure: AskFailure | null;
  /** Sends a question (ignored while a previous one is in flight). */
  ask: (text: string) => void;
  /** Sends the conversation again after a failure. */
  retry: () => void;
}

/**
 * The assistant's question thread for one business (POST /bots/{id}/copilot/messages; read-only). Held by
 * AssistantProvider in the bot layout, so the conversation survives closing the panel and navigating.
 */
export function useAskThread(botId: string): AskThread {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<AskFailure | null>(null);

  const send = useCallback(
    async (thread: AskTurn[]) => {
      setBusy(true);
      setFailure(null);
      try {
        const messages: ChatTurn[] = thread.slice(-HISTORY_LIMIT).map(({ role, content }) => ({ role, content }));
        const out: CopilotMessageOut = await api.copilotMessage(botId, { messages });
        setTurns([...thread, { role: "assistant", content: out.reply, toolCalls: out.tool_calls, usage: out.usage }]);
      } catch (err) {
        setFailure(classify(err));
      } finally {
        setBusy(false);
      }
    },
    [botId],
  );

  const ask = useCallback(
    (text: string) => {
      const content = text.trim();
      if (!content || busy) return;
      const next: AskTurn[] = [...turns, { role: "user", content }];
      setTurns(next);
      setDraft("");
      void send(next);
    },
    [busy, turns, send],
  );

  const retry = useCallback(() => void send(turns), [send, turns]);

  return { turns, draft, setDraft, busy, failure, ask, retry };
}
