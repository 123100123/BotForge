/** Shared geometry of the hand-written SVG charts. Everything is in viewBox units, so the charts scale to their container. */

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
