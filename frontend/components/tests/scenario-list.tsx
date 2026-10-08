"use client";

import { CircleCheck, CircleDashed, CircleX } from "lucide-react";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Scenario, ScenarioResult } from "@/lib/types";

const GROUPS: { source: Scenario["source"]; title: string; hint: string }[] = [
  { source: "derived", title: "آزمون‌های عمومی ربات", hint: "از روی پیکربندی ربات ساخته شده‌اند" },
  { source: "acceptance", title: "آزمون‌های خواستهٔ شما", hint: "از روی چیزهایی که شما گفتید" },
];

interface ScenarioListProps {
  scenarios: Scenario[];
  results: Record<string, ScenarioResult>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** Scenarios grouped by source, each with its pass/fail state (icon and word, never color alone). */
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
              <h5 className="flex items-center justify-between gap-2 text-small font-semibold text-fg">
                {g.title}
                <span className="text-caption font-normal text-fg-muted">
                  {fa(passed)} از {fa(items.length)}
                </span>
              </h5>
              <p className="text-caption text-fg-muted">{g.hint}</p>
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
                        "flex w-full items-start gap-2 rounded-sm px-2 py-2 text-start text-small transition-colors duration-fast",
                        active ? "bg-brand-soft text-fg" : "hover:bg-surface-sunken",
                      )}
                    >
                      {!r ? (
                        <CircleDashed strokeWidth={1.75} aria-label="اجرا نشده" className="mt-1 size-4 shrink-0 text-fg-muted" />
                      ) : r.passed ? (
                        <CircleCheck strokeWidth={1.75} aria-label="موفق" className="mt-1 size-4 shrink-0 text-success-text" />
                      ) : (
                        <CircleX strokeWidth={1.75} aria-label="ناموفق" className="mt-1 size-4 shrink-0 text-danger-text" />
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
