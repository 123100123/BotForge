/**
 * Shared geometry of the hand-written SVG charts.
 *
 * The charts measure their container and draw in CSS pixels (viewBox width = measured width), so a 12.5px
 * label is 12.5px on a 360px phone too. The fixed 420 x 200 helpers (CHART_W ... xFor) remain for callers
 * that still draw in the old box.
 */

export const CHART_W = 420;
export const CHART_H = 200;
export const PLOT = { left: 8, right: CHART_W - 46, top: 14, bottom: CHART_H - 28 };

/** A round upper bound for the y axis (1, 2, 5 times a power of ten). */
export function niceMax(max: number): number {
  if (max <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const f = max / pow;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return nice * pow;
}

/** y position of `value` on an axis that ends at `top`. */
export function yFor(value: number, top: number): number {
  return PLOT.bottom - (Math.max(0, value) / top) * (PLOT.bottom - PLOT.top);
}

/** Center x of point `i` of `n`. The charts are right-to-left: the first (oldest) point is at the right. */
export function xFor(i: number, n: number): number {
  const step = (PLOT.right - PLOT.left) / n;
  return PLOT.right - (i + 0.5) * step;
}

/** Show every k-th x label so they do not collide. */
export function labelEvery(n: number, maxLabels = 7): number {
  return Math.max(1, Math.ceil(n / maxLabels));
}

/* ---- Size-stable geometry ---------------------------------------------------------------------- */

/** Smallest legible chart text (DESIGN.md: nothing under 12.5px). */
export const LABEL_PX = 12.5;
/** Rough width of one Persian glyph at LABEL_PX, used to reserve room for labels. */
const GLYPH_PX = 7.2;

export interface Geometry {
  w: number;
  h: number;
  /** Plot area edges in px. The y-axis labels sit in the gutter right of `right` (the start edge in RTL). */
  left: number;
  right: number;
  top: number;
  bottom: number;
  /** x of the center of the y-axis label gutter. */
  gutterX: number;
}

/** Plot area for a measured width, leaving a gutter wide enough for the longest y tick label. */
export function geometry(w: number, h: number, tickTexts: string[]): Geometry {
  const longest = Math.max(1, ...tickTexts.map((t) => t.length));
  const gutter = Math.min(w * 0.3, Math.ceil(longest * GLYPH_PX) + 12);
  return { w, h, left: 6, right: w - gutter, top: 26, bottom: h - 30, gutterX: w - gutter / 2 };
}

/** Center x of point `i` of `n` in a measured geometry (oldest at the right). */
export function gx(g: Geometry, i: number, n: number): number {
  return g.right - (i + 0.5) * ((g.right - g.left) / n);
}

export function gy(g: Geometry, value: number, top: number): number {
  return g.bottom - (Math.max(0, value) / top) * (g.bottom - g.top);
}

/** Short Persian form of a large number for axis ticks: 12000 -> «۱۲ هزار», 3.5e6 -> «۳٫۵ میلیون». */
export function compactNumber(value: number): string {
  const fmt = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${fmt.format(value / 1e9)} میلیارد`;
  if (abs >= 1e6) return `${fmt.format(value / 1e6)} میلیون`;
  if (abs >= 1e4) return `${fmt.format(value / 1e3)} هزار`;
  return fmt.format(value);
}

/** Estimated px width of the widest label, to decide how many x labels fit. */
export function labelWidth(texts: string[]): number {
  return Math.ceil(Math.max(1, ...texts.map((t) => t.length)) * GLYPH_PX) + 16;
}

/** True when point `i` of `n` carries an x label. Counts back from the newest point so it is always labelled. */
export function showsLabel(i: number, n: number, every: number): boolean {
  return (n - 1 - i) % every === 0;
}

/** Index of the largest value (first on ties). */
export function maxIndex(points: { value: number }[]): number {
  let best = 0;
  points.forEach((p, i) => {
    if (p.value > points[best].value) best = i;
  });
  return best;
}

/** Axis ticks: zero, the middle and the top; counts skip a middle that would be a fraction (2.5 orders). */
export function yTicks(top: number, values: number[]): number[] {
  const mid = top / 2;
  return values.every(Number.isInteger) && !Number.isInteger(mid) ? [0, top] : [0, mid, top];
}
