"use client";

import { useState, type KeyboardEvent } from "react";
import { SendHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export interface ChatLine {
  key: string;
  from: "owner" | "agent";
  text: string;
  /** Delivery state of an owner message that is not in the conversation yet. */
  note?: string;
}

export function ChatMessage({ from, text, note }: { from: "owner" | "agent"; text: string; note?: string }) {
  const isOwner = from === "owner";
  return (
    <div className={cn("flex", isOwner ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-md px-4 py-2.5 text-body whitespace-pre-wrap",
          isOwner ? "bg-brand-soft text-fg" : "border border-border bg-surface-sunken text-fg",
        )}
      >
        <div className="mb-0.5 text-caption text-fg-muted">{isOwner ? "شما" : "دستیار"}</div>
        {text}
        {note && <div className="mt-1 text-caption text-fg-muted">{note}</div>}
      </div>
    </div>
  );
}

/** The conversation between the owner and the assistant (messages only; the cards live in the proposal). */
export function ChatLog({ lines }: { lines: ChatLine[] }) {
  if (lines.length === 0) return <p className="text-small text-fg-muted">هنوز پیامی رد و بدل نشده است.</p>;
  return (
    <ul className="flex flex-col gap-3" aria-label="گفتگو با دستیار">
      {lines.map((line) => (
        <li key={line.key}>
          <ChatMessage from={line.from} text={line.text} note={line.note} />
        </li>
      ))}
    </ul>
  );
}

interface ChatInputProps {
  onSend: (text: string) => void;
  /** When set the input is disabled and this text replaces the placeholder. */
  disabledReason?: string | null;
  placeholder: string;
  label?: string;
}

/** A message box: Enter sends, Shift+Enter adds a line. */
export function ChatInput({ onSend, disabledReason, placeholder, label = "پیام شما" }: ChatInputProps) {
  const [draft, setDraft] = useState("");
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
    <div className="flex items-end gap-2">
      <Textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
        rows={2}
        placeholder={disabledReason ?? placeholder}
        aria-label={label}
        className="max-h-40 resize-none"
      />
      <Button onClick={submit} disabled={disabled || draft.trim() === ""}>
        <SendHorizontal strokeWidth={1.75} className="rtl:-scale-x-100" />
        ارسال
      </Button>
    </div>
  );
}
