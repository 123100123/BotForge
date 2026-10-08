import { fa, formatNumber } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";

/** Horizontal bar list: one row per group with its value and share of the total. Plain HTML so labels wrap and stay readable. */
export function BreakdownList({ points, unit }: { points: SeriesPoint[]; unit?: string | null }) {
  const total = points.reduce((sum, p) => sum + p.value, 0);
  const max = Math.max(1, ...points.map((p) => p.value));
  if (points.length === 0) return <p className="text-small text-fg-muted">داده‌ای برای نمایش نیست.</p>;
  return (
    <ul className="flex flex-col gap-3">
      {points.map((p, i) => {
        const share = total > 0 ? Math.round((p.value / total) * 100) : 0;
        const text = `${p.label}: ${formatNumber(p.value)}${unit ? ` ${unit}` : ""} (${fa(share)}٪)`;
        return (
          <li key={`${p.label}-${i}`} title={text} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span>{p.label}</span>
              {/* Flex items, so the Persian digits of the value and the share are never merged into one number by the bidi algorithm. */}
              <span className="flex shrink-0 items-baseline gap-2">
                <span>
                  {formatNumber(p.value)}
                  {unit && <span className="ms-1 text-caption text-muted-foreground">{unit}</span>}
                </span>
                <span className="text-caption text-muted-foreground">{fa(share)}٪</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-xs bg-border" aria-hidden>
              <div className="h-full rounded-xs bg-chart-1" style={{ width: `${(p.value / max) * 100}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
