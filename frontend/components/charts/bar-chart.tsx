import { CHART_H, CHART_W, PLOT, labelEvery, niceMax, xFor, yFor } from "@/components/charts/chart-axis";
import { formatNumber } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";

/** Vertical bar chart as inline SVG (right-to-left: the oldest point is at the right). Hover a bar for its exact value. */
export function BarChart({ points, label, unit }: { points: SeriesPoint[]; label: string; unit?: string | null }) {
  const n = points.length;
  if (n === 0) return <p className="text-sm text-muted-foreground">داده‌ای برای نمایش نیست.</p>;
  const top = niceMax(Math.max(...points.map((p) => p.value)));
  const ticks = [0, top / 2, top];
  const step = (PLOT.right - PLOT.left) / n;
  const barW = Math.min(step * 0.62, 28);
  const every = labelEvery(n);
  const unitText = unit ? ` ${unit}` : "";

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      role="img"
      aria-label={`${label}: ${points.map((p) => `${p.label} ${formatNumber(p.value)}`).join("، ")}`}
      className="h-auto w-full max-w-lg"
    >
      <title>{label}</title>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PLOT.left} x2={PLOT.right} y1={yFor(t, top)} y2={yFor(t, top)} className="stroke-border" strokeWidth={1} />
          <text x={PLOT.right + 6} y={yFor(t, top) + 4} className="fill-muted-foreground" fontSize={11}>
            {formatNumber(t)}
          </text>
        </g>
      ))}
      {points.map((p, i) => {
        const h = Math.max(p.value > 0 ? 2 : 0, PLOT.bottom - yFor(p.value, top));
        const cx = xFor(i, n);
        return (
          <g key={`${p.label}-${i}`} className="group">
            <title>{`${p.label}: ${formatNumber(p.value)}${unitText}`}</title>
            {/* A full-height transparent hit area keeps tiny bars hoverable. */}
            <rect x={cx - step / 2} y={PLOT.top} width={step} height={PLOT.bottom - PLOT.top} fill="transparent" />
            <rect
              x={cx - barW / 2}
              y={PLOT.bottom - h}
              width={barW}
              height={h}
              rx={3}
              className="fill-primary transition-opacity group-hover:opacity-75"
            />
            {i % every === 0 && (
              <text x={cx} y={CHART_H - 10} textAnchor="middle" className="fill-muted-foreground" fontSize={11}>
                {p.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
