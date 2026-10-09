"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { SendHorizontal, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export interface ChatItem {
  key: string;
  node: ReactNode;
}

export function ChatMessage({ from, text }: { from: "owner" | "agent"; text: string }) {
  const isOwner = from === "owner";
  return (
    <div className={cn("flex", isOwner ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-7 whitespace-pre-wrap shadow-sm sm:max-w-[82%]",
          isOwner ? "rounded-ss-md bg-primary text-primary-foreground" : "rounded-se-md border border-border/70 bg-background",
        )}
      >
        <div className={cn("mb-0.5 text-xs", isOwner ? "text-primary-foreground/70" : "text-muted-foreground")}>
          {isOwner ? "شما" : "ایجنت"}
        </div>
        {text}
      </div>
    </div>
  );
}

interface ChatThreadProps {
  items: ChatItem[];
  /** Shown when there are no items. */
  empty?: ReactNode;
  onSend: (text: string) => void;
  /** When set the input is disabled and this text replaces the placeholder. */
  disabledReason?: string | null;
  placeholder: string;
  /** Text to put in the input box (for example an example prompt); change `seedKey` to apply it again. */
  seed?: { key: number; text: string } | null;
}

/** Owner and agent messages (and inline cards) with the input box. */
export function ChatThread({ items, empty, onSend, disabledReason, placeholder, seed }: ChatThreadProps) {
  const [draft, setDraft] = useState("");
  const [appliedSeed, setAppliedSeed] = useState<number | null>(null);
  const end = useRef<HTMLDivElement>(null);

  // Apply a new seed during render (not in an effect) so it never flashes the old draft.
  if (seed && seed.key !== appliedSeed) {
    setAppliedSeed(seed.key);
    setDraft(seed.text);
  }

  // Keep the newest item in view as the run progresses.
  useEffect(() => {
    if (items.length > 0) end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [items.length]);

  const disabled = Boolean(disabledReason);

  function submit() {
    const text = draft.trim();
    if (!text || disabled) return;
    onSend(text);
    setDraft("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex min-h-80 flex-col gap-5 py-3">
        {items.length === 0 ? empty : items.map((item) => <div key={item.key}>{item.node}</div>)}
        <div ref={end} className="scroll-mb-40" aria-hidden />
      </div>
      <div className="sticky bottom-0 z-10 rounded-2xl border border-border/70 bg-background/95 p-2 shadow-lg shadow-primary/5 backdrop-blur sm:p-3">
        <div className="flex items-end gap-2">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          rows={2}
          placeholder={disabledReason ?? placeholder}
          aria-label="پیام شما"
          className="max-h-40 min-w-0 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        />
        <Button onPress={submit} isDisabled={disabled || draft.trim() === ""} size="lg" className="shrink-0">
          <SendHorizontal className="rtl:-scale-x-100" />
          <span className="hidden sm:inline">ارسال</span>
        </Button>
        </div>
        <p className="mt-1 flex items-center gap-1.5 px-1 text-[11px] text-muted-foreground"><ShieldCheck className="size-3.5" /> تغییرها پیش از فعال‌سازی به تأیید شما می‌رسند.</p>
      </div>
    </div>
  );
}
