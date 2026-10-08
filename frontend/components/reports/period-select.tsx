"use client";

import { PERIOD_LABELS } from "@/components/reports/takeaways";
import { Select } from "@/components/ui/select";
import type { Period } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Every period the report endpoint accepts, in the order they are offered. */
export const PERIOD_ORDER: Period[] = ["today", "yesterday", "7d", "30d", "this_week", "last_week", "this_month", "all"];

export const PERIOD_OPTIONS: { value: Period; label: string }[] = PERIOD_ORDER.map((value) => ({ value, label: PERIOD_LABELS[value] }));

export function isPeriod(value: string | null): value is Period {
  return value !== null && (PERIOD_ORDER as string[]).includes(value);
}

/** The period control at the end of the Reports control row (a native select: it works everywhere, with a keyboard or a thumb). */
export function PeriodSelect({ value, onChange, className }: { value: Period; onChange: (period: Period) => void; className?: string }) {
  return (
    <Select aria-label="بازهٔ زمانی" value={value} onChange={(e) => onChange(e.target.value as Period)} className={cn("w-auto min-w-32", className)}>
      {PERIOD_OPTIONS.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </Select>
  );
}
