"use client";

import { CircleCheck, CircleX } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Requirement, Scenario, ScenarioResult, TranscriptEntry } from "@/lib/types";

const ACTOR_NAMES: Record<string, string> = { ali: "علی", sara: "سارا", reza: "رضا", owner: "مدیر" };

function actorName(id: string) {
  return ACTOR_NAMES[id] ?? id;
}

interface ScenarioDetailProps {
  scenario: Scenario;
  result: ScenarioResult | undefined;
  requirements: Requirement[];
}

export function ScenarioDetail({ scenario, result, requirements }: ScenarioDetailProps) {
  const linked = scenario.requirement_ids
    .map((id) => requirements.find((r) => r.id === id) ?? null)
    .filter((r): r is Requirement => r !== null);

  return (
    <Card>
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{scenario.source === "derived" ? "مشتق‌شده" : "پذیرش"}</Badge>
          {result && <Badge variant={result.passed ? "success" : "destructive"}>{result.passed ? "موفق" : "ناموفق"}</Badge>}
          {!result && <Badge variant="secondary">اجرا نشده</Badge>}
        </div>
        <CardTitle className="text-base leading-7">{scenario.title}</CardTitle>
        {scenario.capacity_override !== null && (
          <p className="text-caption text-muted-foreground">این سناریو با ظرفیت آزمایشی {fa(scenario.capacity_override)} نفر اجرا می‌شود تا کوتاه بماند.</p>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {linked.length > 0 && (
          <section aria-label="نیازمندی‌های مرتبط" className="flex flex-col gap-2">
            <h4 className="text-sm font-semibold">نیازمندی‌های مرتبط</h4>
            <ul className="flex flex-col gap-1.5">
              {linked.map((r) => (
                <li key={r.id} className="flex gap-2 text-sm leading-7">
                  <Badge variant="secondary" className="mt-1 h-fit">
                    {r.id.replace(/\d+/, (d) => fa(d))}
                  </Badge>
                  <span>{r.statement}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section aria-label="مرحله‌ها" className="flex flex-col gap-2">
          <h4 className="text-sm font-semibold">مرحله‌ها</h4>
          {result ? (
            <ol className="flex flex-col gap-1.5">
              {result.steps.map((s) => (
                <li
                  key={s.index}
                  aria-current={!s.passed ? "step" : undefined}
                  className={cn(
                    "flex items-start gap-2 rounded-sm border px-3 py-2 text-sm leading-7",
                    s.passed ? "border-transparent" : "border-destructive/40 bg-danger-soft",
                  )}
                >
                  {s.passed ? (
                    <CircleCheck className="mt-1.5 size-4 shrink-0 text-success-text" />
                  ) : (
                    <CircleX className="mt-1.5 size-4 shrink-0 text-danger-text" />
                  )}
                  <div className="min-w-0">
                    <div>
                      {s.index >= 0 && <span className="text-muted-foreground">{fa(s.index + 1)}. </span>}
                      {s.narrative}
                    </div>
                    {s.message && <div className="font-medium text-danger-text">{s.message}</div>}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted-foreground">این سناریو هنوز اجرا نشده است.</p>
          )}
          {result && result.steps.length < scenario.steps.length && !result.passed && (
            <p className="text-caption text-muted-foreground">
              بعد از مرحلهٔ ناموفق، {fa(scenario.steps.length - result.steps.length)} مرحلهٔ دیگر اجرا نشد.
            </p>
          )}
        </section>

        {result && result.transcript.length > 0 && <Transcript entries={result.transcript} />}
      </CardContent>
    </Card>
  );
}

function Transcript({ entries }: { entries: TranscriptEntry[] }) {
  return (
    <section aria-label="گفتگوها" className="flex flex-col gap-2">
      <h4 className="text-sm font-semibold">گفتگوی کاربران با ربات</h4>
      <ul className="flex flex-col gap-2 rounded-md bg-muted/60 p-3">
        {entries.map((e, i) => (
          <li key={i} className={cn("flex flex-col gap-1", e.direction === "in" ? "items-end" : "items-start")}>
            <span className="text-caption text-muted-foreground">
              {e.direction === "in" ? `${actorName(e.actor)} می‌گوید` : `ربات به ${actorName(e.actor)}`}
            </span>
            <div
              dir="auto"
              className={cn(
                "max-w-[90%] rounded-lg px-3 py-1.5 text-sm leading-7 whitespace-pre-wrap",
                e.direction === "in" ? "bg-primary text-primary-foreground" : "border bg-card",
              )}
            >
              {e.text}
            </div>
            {e.buttons.length > 0 && (
              <div className="flex max-w-[90%] flex-wrap gap-1">
                {e.buttons.map((b, j) => (
                  <span key={j} className="rounded-sm bg-accent px-2 py-0.5 text-caption text-accent-foreground">
                    {b}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
