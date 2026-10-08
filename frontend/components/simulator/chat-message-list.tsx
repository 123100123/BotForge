"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export interface ChatMessage {
  /** Stable key; the index is used when omitted. */
  id?: string | number;
  from: "user" | "bot";
  text: string;
  /** Inline keyboard under a bot message: rows of button labels. */
  buttons?: string[][];
}

export interface ChatMessageListProps {
  messages: ChatMessage[];
  /** Makes the keyboard buttons clickable. Without it they are drawn as static buttons. */
  onButtonPress?: (messageIndex: number, row: number, col: number) => void;
  /** Disables keyboard buttons (a request is in flight). */
  disabled?: boolean;
  /** Shown centered when there are no messages. */
  emptyText?: string;
  /** Keep the newest message in view (the live simulator). Off for static displays. */
  autoScroll?: boolean;
  className?: string;
}

const BUTTON_CLASS =
  "min-h-9 min-w-0 flex-1 rounded-sm border border-border bg-surface px-2 py-1.5 text-small text-brand-text transition-colors duration-fast";

/**
 * Chat bubbles with Telegram-style inline keyboards. User bubbles use the brand tint, bot bubbles the
 * raised surface with a border. Pure: props only (the state of a conversation lives with the caller).
 */
export function ChatMessageList({ messages, onButtonPress, disabled, emptyText, autoScroll, className }: ChatMessageListProps) {
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scroller.current;
    if (autoScroll && el) el.scrollTop = el.scrollHeight;
  }, [messages, autoScroll]);

  return (
    <div
      ref={scroller}
      role="log"
      aria-live="polite"
      aria-label="گفتگو"
      className={cn("flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3", className)}
    >
      {messages.length === 0 && emptyText && <p className="m-auto max-w-56 text-center text-small text-fg-muted">{emptyText}</p>}
      {messages.map((m, i) => (
        <div key={m.id ?? i} className={cn("flex flex-col gap-1.5", m.from === "user" ? "items-end" : "items-start")}>
          <div
            dir="auto"
            className={cn(
              "max-w-[85%] rounded-md px-3 py-2 text-body whitespace-pre-wrap text-fg",
              m.from === "user" ? "rounded-ee-xs bg-brand-soft" : "rounded-es-xs border border-border bg-surface-raised",
            )}
          >
            {m.text}
          </div>
          {m.from === "bot" && m.buttons && m.buttons.length > 0 && (
            <div className="flex w-full max-w-[85%] flex-col gap-1">
              {m.buttons.map((row, r) => (
                <div key={r} className="flex gap-1">
                  {row.map((label, c) =>
                    onButtonPress ? (
                      <button
                        key={c}
                        type="button"
                        disabled={disabled}
                        onClick={() => onButtonPress(i, r, c)}
                        className={cn(BUTTON_CLASS, "hover:bg-surface-sunken disabled:opacity-60")}
                      >
                        {label}
                      </button>
                    ) : (
                      <span key={c} className={cn(BUTTON_CLASS, "text-center")}>
                        {label}
                      </span>
                    ),
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
