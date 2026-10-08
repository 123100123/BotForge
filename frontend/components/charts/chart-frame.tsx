"use client";

import { useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Width used for the first render, before the container has been measured (and on the server). */
const FALLBACK_WIDTH = 420;

/** Width of the element in CSS px, kept up to date with a ResizeObserver. */
function useMeasuredWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(FALLBACK_WIDTH);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => {
      const w = Math.floor(el.getBoundingClientRect().width);
      if (w > 0) setWidth(w);
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export interface ChartTooltipState {
  /** Anchor in px inside the frame (physical left, from the top). */
  x: number;
  y: number;
  title: string;
  lines: string[];
}

/**
 * Wrapper of the hand-written SVG charts. It measures its own width and hands it to `children`, which draw
 * in CSS pixels (so labels keep their size on narrow screens), and renders the hover/focus tooltip as an
 * HTML overlay plus an optional legend for a dashed comparison series.
 */
export function ChartFrame({
  height,
  tooltip,
  legend,
  className,
  children,
}: {
  height: number;
  tooltip: (width: number) => ChartTooltipState | null;
  legend?: { series: string; compare: string } | null;
  className?: string;
  children: (width: number) => ReactNode;
}) {
  const [ref, width] = useMeasuredWidth<HTMLDivElement>();
  // Keep the tooltip inside the frame: it is centered on the point and about 170px wide at most.
  const half = Math.min(86, width / 2);
  const tip = tooltip(width);
  const left = tip ? Math.min(Math.max(tip.x, half), width - half) : 0;
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div ref={ref} className="relative w-full" style={{ height }}>
        {children(width)}
        {tip && (
          <div
            aria-hidden
            className="pointer-events-none absolute z-sticky flex w-max max-w-[172px] flex-col gap-0.5 rounded-sm border border-float bg-surface-raised px-2.5 py-1.5 text-caption text-fg shadow-float"
            style={{ left, top: Math.max(0, tip.y - 8), transform: "translate(-50%, -100%)" }}
          >
            <span className="text-fg-muted">{tip.title}</span>
            {tip.lines.map((line) => (
              <span key={line} className="font-medium">
                {line}
              </span>
            ))}
          </div>
        )}
      </div>
      {legend && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-fg-secondary">
          <span className="inline-flex items-center gap-1.5">
            <svg width="18" height="8" aria-hidden>
              <line x1="0" x2="18" y1="4" y2="4" className="stroke-chart-1" strokeWidth="2" />
            </svg>
            {legend.series}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <svg width="18" height="8" aria-hidden>
              <line x1="0" x2="18" y1="4" y2="4" className="stroke-chart-compare" strokeWidth="2" strokeDasharray="4 3" />
            </svg>
            {legend.compare}
          </span>
        </div>
      )}
    </div>
  );
}

/** Arrow-key navigation between the `[data-point]` targets of a chart (RTL: right is older, left is newer). */
export function pointKeyHandler(container: () => Element | null, index: number, count: number) {
  return (e: KeyboardEvent) => {
    let next = index;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") next = index - 1;
    else if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = index + 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = count - 1;
    else return;
    e.preventDefault();
    container()?.querySelector<SVGElement>(`[data-point="${Math.min(Math.max(next, 0), count - 1)}"]`)?.focus();
  };
}
