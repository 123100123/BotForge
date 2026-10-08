import { CHART_H, CHART_W, PLOT, labelEvery, niceMax, xFor, yFor } from "@/components/charts/chart-axis";
import { formatNumber } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";

/** Line chart as inline SVG (right-to-left: the oldest point is at the right). Hover a point for its exact value. */
export function LineChart({ points, label, unit }: { points: SeriesPoint[]; label: string; unit?: string | null }) {
  const n = points.length;
  if (n === 0) return <p className="text-small text-fg-muted">داده‌ای برای نمایش نیست.</p>;
  const top = niceMax(Math.max(...points.map((p) => p.value)));
  const ticks = [0, top / 2, top];
  const every = labelEvery(n);
  const unitText = unit ? ` ${unit}` : "";
  const coords = points.map((p, i) => ({ x: xFor(i, n), y: yFor(p.value, top), p }));
  const line = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const first = coords[0];
  const last = coords[n - 1];
  const area = `M${first.x.toFixed(1)},${PLOT.bottom} L${line.replaceAll(" ", " L")} L${last.x.toFixed(1)},${PLOT.bottom} Z`;

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
          <line x1={PLOT.left} x2={PLOT.right} y1={yFor(t, top)} y2={yFor(t, top)} className="stroke-chart-grid" strokeWidth={1} />
          <text x={PLOT.right + 6} y={yFor(t, top) + 4} className="fill-chart-label" fontSize={12.5}>
            {formatNumber(t)}
          </text>
        </g>
      ))}
      {n > 1 && <path d={area} className="fill-chart-1" fillOpacity={0.12} />}
      {n > 1 && <polyline points={line} fill="none" className="stroke-chart-1" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
      {coords.map(({ x, y, p }, i) => (
        <g key={`${p.label}-${i}`} className="group">
          <title>{`${p.label}: ${formatNumber(p.value)}${unitText}`}</title>
          <circle cx={x} cy={y} r={10} fill="transparent" />
          <circle cx={x} cy={y} r={n > 15 ? 2.5 : 3.5} className="fill-surface stroke-chart-1 group-hover:fill-chart-1" strokeWidth={2} />
          {i % every === 0 && (
            <text x={x} y={CHART_H - 10} textAnchor="middle" className="fill-chart-label" fontSize={12.5}>
              {p.label}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
