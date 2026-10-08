"use client";

import { useState } from "react";
import { CircleHelp, SendHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/status-badge";
import { fa } from "@/lib/format";
import type { Question } from "@/lib/types";
import { cn } from "@/lib/utils";

interface QuestionCardProps {
  questions: Question[];
  /** The owner's reply once the questions were answered; null while they are open. */
  answer: string | null;
  /** The run is not waiting for an answer through this card (or a request is in flight). */
  disabled?: boolean;
  /** Message under the buttons when `disabled` and not answered. */
  disabledHint?: string;
  onAnswer?: (text: string) => void;
}

/**
 * Blocking questions: one-tap answers where the assistant offered options, plus a free-text answer.
 * One question answers on a tap; several are collected and sent together. Props only (a static variant:
 * pass `answer` and no `onAnswer`).
 */
export function QuestionCard({ questions, answer, disabled = false, disabledHint, onAnswer }: QuestionCardProps) {
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [free, setFree] = useState("");
  const answered = answer !== null;
  const locked = answered || disabled || !onAnswer;
  const single = questions.length === 1;

  function choose(q: Question, value: string) {
    if (locked) return;
    if (single) {
      onAnswer?.(value);
      return;
    }
    setPicked((prev) => ({ ...prev, [q.id]: value }));
  }

  const allAnswered = questions.every((q) => (picked[q.id] ?? "").trim() !== "");

  function submitAll() {
    onAnswer?.(questions.map((q, i) => `${fa(i + 1)}) ${picked[q.id].trim()}`).join("\n"));
  }

  function submitFree() {
    const text = free.trim();
    if (!text || locked) return;
    onAnswer?.(text);
    setFree("");
  }

  return (
    <div className={cn("flex flex-col gap-4 rounded-md border p-4", answered ? "border-border bg-surface" : "border-warning/50 bg-surface-raised")}>
      <div className="flex items-center gap-2">
        <CircleHelp strokeWidth={1.75} aria-hidden className="size-5 shrink-0 text-warning-text" />
        <h4 className="text-h3 text-fg">{single ? "یک پرسش از شما" : `${fa(questions.length)} پرسش از شما`}</h4>
        {answered && (
          <StatusBadge tone="success" marker className="ms-auto">
            پاسخ داده شد
          </StatusBadge>
        )}
      </div>

      {questions.map((q) => (
        <div key={q.id} className="flex flex-col gap-2">
          <p className="text-body font-medium">{q.text}</p>
          {q.why && <p className="text-small text-fg-muted">{q.why}</p>}
          {q.options && q.options.length > 0 ? (
            <div className="flex flex-wrap gap-2" role="group" aria-label="پاسخ‌های پیشنهادی">
              {q.options.map((option) => (
                <Button
                  key={option}
                  type="button"
                  variant={picked[q.id] === option ? "primary" : "secondary"}
                  disabled={locked}
                  onClick={() => choose(q, option)}
                  className="h-auto min-h-10 max-w-full py-2 text-start whitespace-normal"
                >
                  {option}
                </Button>
              ))}
            </div>
          ) : (
            !single && (
              <Input
                value={picked[q.id] ?? ""}
                disabled={locked}
                onChange={(e) => setPicked((prev) => ({ ...prev, [q.id]: e.target.value }))}
                aria-label={q.text}
                placeholder="پاسخ شما"
              />
            )
          )}
        </div>
      ))}

      {answered ? (
        <div className="rounded-sm bg-surface-sunken p-3 text-small whitespace-pre-wrap">
          <span className="text-fg-muted">پاسخ شما: </span>
          {answer}
        </div>
      ) : (
        <>
          {!single && (
            <Button type="button" onClick={submitAll} disabled={locked || !allAnswered} className="self-start">
              ارسال پاسخ‌ها
            </Button>
          )}
          {single && (
            <form
              className="flex flex-col gap-2 sm:flex-row sm:items-center"
              onSubmit={(e) => {
                e.preventDefault();
                submitFree();
              }}
            >
              <Input
                value={free}
                disabled={locked}
                onChange={(e) => setFree(e.target.value)}
                aria-label="پاسخ با کلمات خودتان"
                placeholder="یا با کلمات خودتان پاسخ بدهید…"
              />
              <Button type="submit" variant="secondary" disabled={locked || free.trim() === ""}>
                <SendHorizontal strokeWidth={1.75} className="rtl:-scale-x-100" />
                ارسال
              </Button>
            </form>
          )}
          {disabled && disabledHint && <p className="text-caption text-fg-muted">{disabledHint}</p>}
        </>
      )}
    </div>
  );
}
