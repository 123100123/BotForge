import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/format";
import { comparePeriods, type ChangeTone, type Polarity } from "@/lib/polarity";
import { cn } from "@/lib/utils";

export interface MetricStripItem {
  id: string;
  label: string;
  value: number | null;
  unit?: string | null;
  /** Value of the previous period; omit or null for no comparison line. */
  previous?: number | null;
  /** Which direction is good (lib/polarity.ts metricPolarity); default up_good. */
  polarity?: Polarity;
}

const TONE_CLASS: Record<ChangeTone, string> = {
  success: "text-success-text",
  danger: "text-danger-text",
  neutral: "text-fg-secondary",
};

// Literal class names so Tailwind sees them. Leftover cells of the last row stay empty (surface).
const COLUMNS: Record<number, string> = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-2 sm:grid-cols-3",
  4: "grid-cols-2 lg:grid-cols-4",
  5: "grid-cols-2 sm:grid-cols-3 xl:grid-cols-5",
};

function columnsFor(count: number): string {
  return COLUMNS[Math.min(Math.max(count, 1), 5)];
}

// Cells draw an end and a bottom hairline; the grid is pulled 1px past the frame so the outer ones are clipped.
const CELL = "flex min-w-0 flex-col gap-1 border-e border-b border-border p-4";

function Comparison({ item }: { item: MetricStripItem }) {
  const cmp = comparePeriods(item.value, item.previous ?? null, item.polarity ?? "up_good");
  if (!cmp) return <span className="text-caption text-fg-muted">&nbsp;</span>;
  const Arrow = cmp.arrow === "up" ? ArrowUpIcon : ArrowDownIcon;
  const text =
    cmp.direction === "same"
      ? "بدون تغییر نسبت به دورهٔ قبل"
      : `${cmp.percent === null ? "" : `${cmp.percentText} `}${cmp.word} از دورهٔ قبل`;
  return (
    <span className={cn("inline-flex items-start gap-1 text-caption", TONE_CLASS[cmp.tone])}>
      {cmp.arrow !== "none" && <Arrow className="mt-[0.3em] size-3.5 shrink-0" strokeWidth={1.75} aria-hidden />}
      <span>{text}</span>
    </span>
  );
}

/**
 * One bordered row of 3 to 5 headline numbers with hairline dividers (not separate cards). Each cell: label,
 * value with unit, and a comparison line (arrow, word, percent) colored by polarity. Pure: props only, so
 * Reports and the landing page can reuse it. With `loading` it draws a skeleton of `count` cells.
 */
export function MetricStrip({
  items,
  loading = false,
  count = 4,
  label = "شاخص‌های کلیدی",
  className,
}: {
  items?: MetricStripItem[];
  loading?: boolean;
  /** Number of skeleton cells while loading. */
  count?: number;
  /** Accessible name of the group. */
  label?: string;
  className?: string;
}) {
  const shown = (items ?? []).slice(0, 5);
  const cells = loading ? count : shown.length;
  if (cells === 0) return null;
  return (
    <div role="group" aria-label={label} aria-busy={loading || undefined} className={cn("overflow-hidden rounded-md border border-border bg-surface", className)}>
      <div className={cn("-me-px -mb-px grid", columnsFor(cells))}>
        {loading
          ? Array.from({ length: cells }, (_, i) => (
              <div key={i} className={CELL}>
                <Skeleton className="h-4 w-20" />
                <Skeleton className="my-1 h-7 w-28" />
                <Skeleton className="h-4 w-32" />
              </div>
            ))
          : shown.map((item) => (
              <div key={item.id} className={CELL}>
                <span className="text-caption text-fg-muted">{item.label}</span>
                <span className="flex flex-wrap items-baseline gap-x-1.5">
                  <span className="text-metric text-fg">{item.value === null ? "—" : formatNumber(item.value)}</span>
                  {item.unit && <span className="text-caption text-fg-muted">{item.unit}</span>}
                </span>
                <Comparison item={item} />
              </div>
            ))}
      </div>
    </div>
  );
}
