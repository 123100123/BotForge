"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bot as BotIcon, SendHorizontal } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { RuntimeButton } from "@/lib/types";
import type { ChatItem } from "./chat";

interface PhoneFrameProps {
  botName: string;
  personaLabel: string;
  items: ChatItem[];
  busy: boolean;
  onPress: (item: ChatItem, button: RuntimeButton) => void;
  onSendText: (text: string) => void;
}

/** A Telegram-like conversation: bot messages with inline keyboards, the user's texts and taps, an input bar. */
export function PhoneFrame({ botName, personaLabel, items, busy, onPress, onSendText }: PhoneFrameProps) {
  const [text, setText] = useState("");
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setText("");
    onSendText(value);
  }

  return (
    <div className="mx-auto flex h-[min(41rem,75vh)] min-h-[31rem] w-full max-w-[26rem] flex-col overflow-hidden rounded-[2rem] border-[6px] border-slate-950 bg-card shadow-[0_24px_70px_-30px_rgba(10,39,81,.48)] dark:border-slate-700">
      <div className="mx-auto mt-1 h-1.5 w-20 rounded-full bg-slate-400/40" aria-hidden />
      <div className="flex items-center gap-3 border-b border-border/60 bg-card px-4 py-3">
        <span className="grid size-9 place-items-center rounded-full bg-primary text-primary-foreground">
          <BotIcon className="size-5" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{botName}</div>
          <div className="text-xs text-muted-foreground">در نقش {personaLabel}</div>
        </div>
      </div>

      <div ref={scroller} className="flex flex-1 flex-col gap-3 overflow-y-auto bg-[radial-gradient(circle_at_12%_18%,color-mix(in_srgb,var(--primary)_8%,transparent),transparent_45%),linear-gradient(135deg,color-mix(in_srgb,var(--muted)_76%,transparent),color-mix(in_srgb,var(--card)_82%,transparent))] p-3 sm:p-4" aria-live="polite">
        {items.length === 0 && (
          <p className="m-auto max-w-56 text-center text-sm leading-7 text-muted-foreground">
            گفتگو خالی است. برای شروع، دکمهٔ «شروع» را بزنید.
          </p>
        )}
        {items.map((item) => (
          <div key={item.id} className={cn("flex flex-col gap-1.5", item.from === "me" ? "items-end" : "items-start")}>
            <div
              dir="auto"
              className={cn(
                "max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-7 whitespace-pre-wrap",
                item.from === "me"
                  ? "rounded-ee-sm bg-primary text-primary-foreground"
                  : "rounded-es-sm border border-border/60 bg-card shadow-sm",
              )}
            >
              {item.text}
            </div>
            {item.from === "bot" && item.buttons.length > 0 && (
              <div className="flex w-full max-w-[85%] flex-col gap-1">
                {item.buttons.map((row, r) => (
                  <div key={r} className="flex gap-1">
                    {row.map((b, i) => (
                      <button
                        key={`${b.data}-${i}`}
                        type="button"
                        disabled={busy}
                        onClick={() => onPress(item, b)}
                        className="min-w-0 flex-1 rounded-xl border border-primary/20 bg-primary/10 px-2 py-2 text-sm font-medium text-primary transition-colors outline-none hover:bg-primary/20 focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:opacity-60"
                      >
                        {b.label}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={submit} className="flex items-center gap-2 border-t bg-card p-2">
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="پیام…" aria-label="پیام" disabled={busy} />
        <button
          type="submit"
          disabled={busy || text.trim() === ""}
          aria-label="ارسال"
          className="grid size-9 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:opacity-50"
        >
          <SendHorizontal className="size-4 rtl:-scale-x-100" />
        </button>
      </form>
    </div>
  );
}
