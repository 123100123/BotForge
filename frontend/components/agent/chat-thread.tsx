"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { SendHorizontal } from "lucide-react";
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
          "max-w-[85%] rounded-lg px-4 py-2.5 text-sm leading-7 whitespace-pre-wrap",
          isOwner ? "bg-primary text-primary-foreground" : "border bg-card",
        )}
      >
        <div className={cn("mb-0.5 text-caption", isOwner ? "text-primary-foreground/70" : "text-muted-foreground")}>
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
    <div className="flex flex-col gap-3">
      <div className="flex min-h-72 flex-col gap-4">
        {items.length === 0 ? empty : items.map((item) => <div key={item.key}>{item.node}</div>)}
        <div ref={end} className="scroll-mb-40" aria-hidden />
      </div>
      {/* Below 640px the shell's bottom tab bar covers the viewport bottom: stick above it. */}
      <div className="sticky bottom-0 z-10 flex items-end gap-2 bg-background/95 pt-2 pb-3 backdrop-blur max-sm:bottom-[calc(3.625rem+env(safe-area-inset-bottom))]">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          rows={2}
          placeholder={disabledReason ?? placeholder}
          aria-label="پیام شما"
          className="max-h-40 resize-none"
        />
        <Button onClick={submit} disabled={disabled || draft.trim() === ""} size="lg">
          <SendHorizontal className="rtl:-scale-x-100" />
          ارسال
        </Button>
      </div>
    </div>
  );
}
