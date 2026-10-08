"use client";

import { CircleCheck, CircleDashed, CircleX } from "lucide-react";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Scenario, ScenarioResult } from "@/lib/types";

const GROUPS: { source: Scenario["source"]; title: string; hint: string }[] = [
  { source: "derived", title: "آزمون‌های مشتق‌شده", hint: "از روی تنظیمات ربات ساخته شده‌اند" },
  { source: "acceptance", title: "آزمون‌های پذیرش", hint: "از روی نیازمندی‌هایی که شما گفتید" },
];

interface ScenarioListProps {
  scenarios: Scenario[];
  results: Record<string, ScenarioResult>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** Scenarios grouped by source, each with its pass/fail state. */
export function ScenarioList({ scenarios, results, selectedId, onSelect }: ScenarioListProps) {
  return (
    <div className="flex flex-col gap-5">
      {GROUPS.map((g) => {
        const items = scenarios.filter((s) => s.source === g.source);
        if (items.length === 0) return null;
        const passed = items.filter((s) => results[s.id]?.passed).length;
        return (
          <section key={g.source} aria-label={g.title} className="flex flex-col gap-1">
            <div className="px-2">
              <h3 className="flex items-center justify-between gap-2 text-sm font-semibold">
                {g.title}
                <span className="text-caption font-normal text-muted-foreground">
                  {fa(passed)} از {fa(items.length)}
                </span>
              </h3>
              <p className="text-caption text-muted-foreground">{g.hint}</p>
            </div>
            <ul className="flex flex-col gap-0.5">
              {items.map((s) => {
                const r = results[s.id];
                const active = s.id === selectedId;
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(s.id)}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-sm px-2 py-2 text-start text-sm leading-6 transition-colors",
                        active ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                      )}
                    >
                      {!r ? (
                        <CircleDashed aria-label="اجرا نشده" className="mt-1 size-4 shrink-0 text-muted-foreground" />
                      ) : r.passed ? (
                        <CircleCheck aria-label="موفق" className="mt-1 size-4 shrink-0 text-success-text" />
                      ) : (
                        <CircleX aria-label="ناموفق" className="mt-1 size-4 shrink-0 text-danger-text" />
                      )}
                      <span>{s.title}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
