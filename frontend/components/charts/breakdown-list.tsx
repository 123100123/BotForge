import { fa, formatNumber } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";

/**
 * Horizontal bars, one row per group, labelled directly: the name, then the value and its share of the total
 * at the end of the same line, and a bar under it scaled to the largest value. No background track. Plain
 * HTML, so long names wrap and stay at full size on narrow screens.
 */
export function BreakdownList({ points, unit }: { points: SeriesPoint[]; unit?: string | null }) {
  const total = points.reduce((sum, p) => sum + p.value, 0);
  const max = Math.max(1, ...points.map((p) => p.value));
  if (points.length === 0) return <p className="text-small text-fg-muted">داده‌ای برای نمایش نیست.</p>;
  return (
    <ul className="flex flex-col gap-3.5">
      {points.map((p, i) => {
        const share = total > 0 ? Math.round((p.value / total) * 100) : 0;
        const text = `${p.label}: ${formatNumber(p.value)}${unit ? ` ${unit}` : ""} (${fa(share)}٪)`;
        return (
          <li key={`${p.label}-${i}`} aria-label={text} className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3 text-small">
              <span className="min-w-0 text-fg">{p.label}</span>
              {/* Flex items, so the Persian digits of the value and the share are never merged into one number by the bidi algorithm. */}
              <span className="flex shrink-0 items-baseline gap-2 tabular-nums">
                <span className="font-medium text-fg">
                  {formatNumber(p.value)}
                  {unit && <span className="ms-1 text-caption font-normal text-fg-muted">{unit}</span>}
                </span>
                <span className="text-caption text-fg-secondary">{fa(share)}٪</span>
              </span>
            </div>
            <div aria-hidden className="h-2 rounded-xs bg-chart-1" style={{ width: `${Math.max(1.5, (p.value / max) * 100)}%` }} />
          </li>
        );
      })}
    </ul>
  );
}
