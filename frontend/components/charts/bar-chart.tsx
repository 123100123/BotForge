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
 * Vertical bar chart as inline SVG (right-to-left: the oldest bar is at the right). It measures its width and
 * draws in CSS pixels, so labels stay 12.5px on any screen. Hover or focus a bar (arrow keys move between
 * them) for its exact value; the newest bar is emphasized and labelled. `compare` is the previous period,
 * drawn as dashed marks matched to `points` by position.
 */
export function BarChart({
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
        const slot = (g.right - g.left) / n;
        const barW = Math.max(3, Math.min(slot * 0.62, 32));
        const every = labelEvery(n, Math.max(2, Math.floor((g.right - g.left) / labelWidth(points.map((p) => p.label)))));
        const lastX = Math.min(Math.max(gx(g, last, n), g.left + 20), g.right - 20);
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
            {points.map((p, i) => {
              const h = Math.max(p.value > 0 ? 2 : 0, g.bottom - gy(g, p.value, top));
              const cx = gx(g, i, n);
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
                  {/* A full-height transparent hit area keeps tiny bars hoverable and tappable. */}
                  <rect x={cx - slot / 2} y={g.top - 8} width={slot} height={g.bottom - g.top + 8} fill="transparent" />
                  <rect
                    x={cx - barW / 2}
                    y={g.bottom - h}
                    width={barW}
                    height={h}
                    rx={2}
                    className="fill-chart-1 transition-opacity duration-fast"
                    opacity={isLast || isActive ? 1 : 0.62}
                  />
                  {cmp?.[i] && (
                    <line
                      x1={cx - Math.max(barW, slot * 0.7) / 2}
                      x2={cx + Math.max(barW, slot * 0.7) / 2}
                      y1={gy(g, cmp[i].value, top)}
                      y2={gy(g, cmp[i].value, top)}
                      className="stroke-chart-compare"
                      strokeWidth={2}
                      strokeDasharray="4 3"
                    />
                  )}
                </g>
              );
            })}
            <text
              x={lastX}
              y={Math.max(LABEL_PX + 2, gy(g, points[last].value, top) - 7)}
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
