import { fa } from "@/lib/format";

/**
 * Which direction of a number is good news (D11/D12). Color on a comparison follows polarity; the arrow and
 * the word follow the direction of the change. A rise in cancellations is «بیشتر», with a down-good tone.
 */
export type Polarity = "up_good" | "down_good" | "neutral";

const DOWN_GOOD = new Set(["cancel_rate", "cancellation_rate", "cancelled_count", "anomaly_count", "open_requests", "pending_approvals", "low_stock", "no_show_rate"]);
const NEUTRAL = new Set(["average_order_value", "response_time", "reports_uploaded", "row_count", "event_count", "events_count"]);

/**
 * Polarity of a metric id. Ids such as `orders.revenue` (two capabilities of one kind) are matched on the last
 * segment. Unknown ids count as up-good, which fits revenue, orders, bookings, customers, RSVPs and capacity use.
 */
export function metricPolarity(id: string): Polarity {
  const key = id.includes(".") ? id.slice(id.lastIndexOf(".") + 1) : id;
  if (DOWN_GOOD.has(key)) return "down_good";
  if (NEUTRAL.has(key)) return "neutral";
  return "up_good";
}

export type ChangeTone = "success" | "danger" | "neutral";

export interface Comparison {
  direction: "more" | "less" | "same";
  /** «بیشتر» / «کمتر» / «بدون تغییر». */
  word: string;
  tone: ChangeTone;
  arrow: "up" | "down" | "none";
  /** Absolute change in percent, rounded; null when the previous value was zero (no base to divide by). */
  percent: number | null;
  /** «۱۲٪», or «جدید» when there was nothing before; empty for no change. */
  percentText: string;
}

/** Change of `current` against `previous`; null when either is unknown. */
export function comparePeriods(current: number | null, previous: number | null, polarity: Polarity = "up_good"): Comparison | null {
  if (current === null || previous === null) return null;
  const same: Comparison = { direction: "same", word: "بدون تغییر", tone: "neutral", arrow: "none", percent: 0, percentText: "" };
  if (current === previous) return same;
  const up = current > previous;
  const percent = previous === 0 ? null : Math.round((Math.abs(current - previous) / Math.abs(previous)) * 100);
  if (percent === 0) return same;
  let tone: ChangeTone = "neutral";
  if (polarity === "up_good") tone = up ? "success" : "danger";
  else if (polarity === "down_good") tone = up ? "danger" : "success";
  return {
    direction: up ? "more" : "less",
    word: up ? "بیشتر" : "کمتر",
    tone,
    arrow: up ? "up" : "down",
    percent,
    percentText: percent === null ? "جدید" : `${fa(percent)}٪`,
  };
}
