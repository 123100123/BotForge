"use client";

import { useState } from "react";
import { CircleHelp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fa } from "@/lib/format";
import type { Question } from "@/lib/types";
import { cn } from "@/lib/utils";

interface QuestionsCardProps {
  questions: Question[];
  /** The owner's reply once the questions were answered; null while they are open. */
  answer: string | null;
  /** The run is no longer waiting for an answer through this card. */
  disabled: boolean;
  onAnswer: (text: string) => void;
}

/** Blocking questions with optional choice buttons. Answering sends a chat message. */
export function QuestionsCard({ questions, answer, disabled, onAnswer }: QuestionsCardProps) {
  const [picked, setPicked] = useState<Record<string, string>>({});
  const answered = answer !== null;
  const locked = answered || disabled;
  const single = questions.length === 1;

  function choose(q: Question, value: string) {
    if (locked) return;
    if (single) {
      onAnswer(value);
      return;
    }
    setPicked((prev) => ({ ...prev, [q.id]: value }));
  }

  const allAnswered = questions.every((q) => (picked[q.id] ?? "").trim() !== "");

  function submitAll() {
    const text = questions.map((q, i) => `${fa(i + 1)}) ${picked[q.id].trim()}`).join("\n");
    onAnswer(text);
  }

  return (
    <Card className="border-warning/40">
      <CardHeader className="flex-row items-center gap-2">
        <CircleHelp className="size-5 text-warning-text" />
        <CardTitle>{single ? "یک پرسش" : "چند پرسش"}</CardTitle>
        {answered && <Badge variant="success">پاسخ داده شد</Badge>}
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {questions.map((q) => (
          <div key={q.id} className="flex flex-col gap-2">
            <div className="text-sm leading-7 font-medium">{q.text}</div>
            <p className="text-caption leading-6 text-muted-foreground">{q.why}</p>
            {q.options && q.options.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {q.options.map((option) => (
                  <Button
                    key={option}
                    type="button"
                    size="sm"
                    variant={picked[q.id] === option ? "default" : "outline"}
                    disabled={locked}
                    onClick={() => choose(q, option)}
                    className={cn("h-auto min-h-8 whitespace-normal py-1.5 text-start")}
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
          <div className="rounded-md bg-muted p-3 text-sm whitespace-pre-wrap">
            <span className="text-muted-foreground">پاسخ شما: </span>
            {answer}
          </div>
        ) : (
          <>
            {!single && (
              <Button type="button" onClick={submitAll} disabled={locked || !allAnswered} className="self-start">
                ارسال پاسخ‌ها
              </Button>
            )}
            <p className="text-caption text-muted-foreground">
              {disabled ? "این پرسش دیگر فعال نیست." : "می‌توانید پاسخ خود را با کلمات خودتان هم در کادر پیام بنویسید."}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
