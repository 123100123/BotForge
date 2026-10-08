"use client";

import { useRef, useState } from "react";
import {
  LABEL_PX,
  compactNumber,
  geometry,
  gx,
  gy,
  labelEvery,
  labelWidth,
  niceMax,
  showsLabel,
  yTicks,
} from "@/components/charts/chart-axis";
import { ChartFrame, pointKeyHandler } from "@/components/charts/chart-frame";
import { formatNumber } from "@/lib/format";
import type { SeriesPoint } from "@/lib/types";

/**
 * Line chart as inline SVG (right-to-left: the oldest point is at the right). It measures its width and draws
 * in CSS pixels, so labels stay 12.5px on any screen. Hover or focus a point (arrow keys move between them)
 * for its exact value; the newest point is emphasized and labelled. `compare` is the previous period, drawn
 * as a dashed line and matched to `points` by position.
 */
export function LineChart({
  points,
  label,
  unit,
  compare,
  compareLabel = "دورهٔ قبل",
  height = 200,
}: {
  points: SeriesPoint[];
  label: string;
  unit?: string | null;
  compare?: SeriesPoint[] | null;
  compareLabel?: string;
  height?: number;
}) {
  const n = points.length;
  const [active, setActive] = useState<number | null>(null);
  const [tabStop, setTabStop] = useState(Math.max(0, n - 1));
  const svgRef = useRef<SVGSVGElement>(null);
  if (n === 0) return <p className="text-small text-fg-muted">داده‌ای برای نمایش نیست.</p>;

  const cmp = compare && compare.length > 0 ? compare.slice(0, n) : null;
  const top = niceMax(Math.max(...points.map((p) => p.value), ...(cmp ?? []).map((p) => p.value)));
  const ticks = yTicks(top, [...points.map((p) => p.value), ...(cmp ?? []).map((p) => p.value)]);
  const tickTexts = ticks.map(compactNumber);
  const unitText = unit ? ` ${unit}` : "";
  const fmt = (v: number) => `${formatNumber(v)}${unitText}`;
  const last = n - 1;

  return (
    <ChartFrame
      height={height}
      legend={cmp ? { series: "این دوره", compare: compareLabel } : null}
      tooltip={(w) => {
        if (active === null) return null;
        const g = geometry(w, height, tickTexts);
        const p = points[active];
        return {
          x: gx(g, active, n),
          y: gy(g, p.value, top),
          title: p.label,
          lines: [fmt(p.value), ...(cmp?.[active] ? [`${compareLabel}: ${fmt(cmp[active].value)}`] : [])],
        };
      }}
    >
      {(w) => {
        const g = geometry(w, height, tickTexts);
        const every = labelEvery(n, Math.max(2, Math.floor((g.right - g.left) / labelWidth(points.map((p) => p.label)))));
        const coords = points.map((p, i) => ({ x: gx(g, i, n), y: gy(g, p.value, top), p }));
        const line = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
        const area = `M${coords[0].x.toFixed(1)},${g.bottom} L${line.replaceAll(" ", " L")} L${coords[last].x.toFixed(1)},${g.bottom} Z`;
        const slot = (g.right - g.left) / n;
        const cmpLine = cmp?.map((p, i) => `${gx(g, i, n).toFixed(1)},${gy(g, p.value, top).toFixed(1)}`).join(" ");
        const lastX = Math.min(Math.max(coords[last].x, g.left + 20), g.right - 20);
        return (
          <svg
            ref={svgRef}
            width={w}
            height={height}
            viewBox={`0 0 ${w} ${height}`}
            role="group"
            aria-label={label}
            className="block"
            onPointerLeave={() => setActive(null)}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line x1={g.left} x2={g.right} y1={gy(g, t, top)} y2={gy(g, t, top)} className="stroke-chart-grid" strokeWidth={1} />
                <text x={g.gutterX} y={gy(g, t, top) + 4} textAnchor="middle" className="fill-chart-label tabular-nums" fontSize={LABEL_PX}>
                  {compactNumber(t)}
                </text>
              </g>
            ))}
            {n > 1 && <path d={area} className="fill-chart-1" fillOpacity={0.1} />}
            {cmpLine && cmp && cmp.length > 1 && (
              <polyline points={cmpLine} fill="none" className="stroke-chart-compare" strokeWidth={1.75} strokeDasharray="5 4" strokeLinejoin="round" />
            )}
            {n > 1 && <polyline points={line} fill="none" className="stroke-chart-1" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
            {coords.map(({ x, y, p }, i) => {
              const isLast = i === last;
              const isActive = active === i;
              const text = `${p.label}: ${fmt(p.value)}${cmp?.[i] ? `، ${compareLabel}: ${fmt(cmp[i].value)}` : ""}`;
              return (
                <g
                  key={`${p.label}-${i}`}
                  data-point={i}
                  tabIndex={i === tabStop ? 0 : -1}
                  role="img"
                  aria-label={text}
                  onPointerEnter={() => setActive(i)}
                  onFocus={() => {
                    setActive(i);
                    setTabStop(i);
                  }}
                  onBlur={() => setActive(null)}
                  onKeyDown={pointKeyHandler(() => svgRef.current, i, n)}
                >
                  {/* A full-height band keeps every point easy to hover, tap and focus. */}
                  <rect x={x - slot / 2} y={g.top - 8} width={slot} height={g.bottom - g.top + 8} fill="transparent" />
                  {(isLast || isActive || n <= 12) && (
                    <circle
                      cx={x}
                      cy={y}
                      r={isLast ? 5 : isActive ? 5 : 3}
                      className={isLast || isActive ? "fill-chart-1 stroke-surface" : "fill-surface stroke-chart-1"}
                      strokeWidth={isLast || isActive ? 2 : 1.75}
                    />
                  )}
                </g>
              );
            })}
            <text
              x={lastX}
              y={Math.max(LABEL_PX + 2, coords[last].y - 11)}
              textAnchor="middle"
              className="fill-fg stroke-surface"
              fontSize={LABEL_PX}
              fontWeight={600}
              strokeWidth={3}
              paintOrder="stroke"
              aria-hidden
            >
              {formatNumber(points[last].value)}
            </text>
            {points.map((p, i) =>
              showsLabel(i, n, every) ? (
                <text key={`x-${i}`} x={gx(g, i, n)} y={height - 8} textAnchor="middle" className="fill-chart-label" fontSize={LABEL_PX} aria-hidden>
                  {p.label}
                </text>
              ) : null,
            )}
          </svg>
        );
      }}
    </ChartFrame>
  );
}
