"use client";

import { Segmented } from "@/components/app/segmented";
import type { Period } from "@/lib/types";

/** The periods the owner can pick on the Overview and Reports screens. */
export const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "today", label: "امروز" },
  { value: "7d", label: "۷ روز" },
  { value: "30d", label: "۳۰ روز" },
  { value: "this_month", label: "این ماه" },
];

export function PeriodSelect({ value, onChange }: { value: Period; onChange: (period: Period) => void }) {
  return <Segmented<Period> label="بازهٔ زمانی" value={value} onChange={onChange} options={PERIOD_OPTIONS} />;
}
