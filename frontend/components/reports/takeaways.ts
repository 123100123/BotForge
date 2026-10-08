import { maxIndex } from "@/components/charts/chart-axis";
import { fa, formatNumber } from "@/lib/format";
import type { Period, SeriesPoint } from "@/lib/types";

/** Plain-language data summaries: the one-line takeaway under each chart title, and the screen-reader sentence. */

export const PERIOD_LABELS: Record<Period, string> = {
  today: "امروز",
  yesterday: "دیروز",
  "7d": "۷ روز اخیر",
  "30d": "۳۰ روز اخیر",
  this_week: "این هفته",
  last_week: "هفتهٔ گذشته",
  this_month: "این ماه",
  all: "کل دوره",
};

/** The period a given period is compared with, when the API can report it (a second report call). */
export const COMPARE_PERIOD: Partial<Record<Period, Period>> = { today: "yesterday", this_week: "last_week" };

function withUnit(value: number, unit?: string | null): string {
  return `${formatNumber(value)}${unit ? ` ${unit}` : ""}`;
}

export type Trend = "up" | "down" | "flat";

/** Direction of a series: the average of its newer half against its older half; under 8 percent counts as steady. */
export function trendOf(points: SeriesPoint[]): Trend {
  const n = points.length;
  const half = Math.floor(n / 2);
  const avg = (xs: SeriesPoint[]) => xs.reduce((s, p) => s + p.value, 0) / Math.max(1, xs.length);
  const older = avg(points.slice(0, half));
  const newer = avg(points.slice(n - half));
  if (older === 0) return newer === 0 ? "flat" : "up";
  const change = (newer - older) / Math.abs(older);
  return change > 0.08 ? "up" : change < -0.08 ? "down" : "flat";
}

const TREND_WORD: Record<Trend, string> = { up: "افزایشی", down: "کاهشی", flat: "تقریباً ثابت" };

/** «روند ۷ روز اخیر: افزایشی. بیشترین: ۱۲ مهر با ۱۸.» Needs four points for a trend, two for a peak. */
export function seriesTakeaway(points: SeriesPoint[], unit: string | null | undefined, period: Period | null): string | null {
  if (points.length < 2) return null;
  const peak = points[maxIndex(points)];
  const peakText = peak.value > 0 ? `بیشترین: ${peak.label} با ${withUnit(peak.value, unit)}.` : null;
  if (points.length < 4) return peakText;
  return [`روند ${period ? PERIOD_LABELS[period] : "این فایل"}: ${TREND_WORD[trendOf(points)]}.`, peakText].filter(Boolean).join(" ");
}

export function seriesSummary(title: string, points: SeriesPoint[], unit: string | null | undefined): string {
  if (points.length === 0) return `${title}: داده‌ای برای نمایش نیست.`;
  const values = points.map((p) => p.value);
  const peak = points[maxIndex(points)];
  const first = points[0];
  const last = points[points.length - 1];
  return (
    `${title}: ${fa(points.length)} نقطه از ${first.label} تا ${last.label}. ` +
    `کمترین ${withUnit(Math.min(...values), unit)}، بیشترین ${withUnit(peak.value, unit)} در ${peak.label}، ` +
    `آخرین مقدار ${withUnit(last.value, unit)}.`
  );
}

/** «بیشترین: کارگاه طراحی لوگو با ۱۸ ثبت‌نام (۴۱٪ از کل).» */
export function breakdownTakeaway(points: SeriesPoint[], unit: string | null | undefined): string | null {
  if (points.length < 2) return null;
  const total = points.reduce((s, p) => s + p.value, 0);
  const top = points[maxIndex(points)];
  if (top.value <= 0 || total <= 0) return null;
  return `بیشترین: ${top.label} با ${withUnit(top.value, unit)} (${fa(Math.round((top.value / total) * 100))}٪ از کل).`;
}

export function breakdownSummary(title: string, points: SeriesPoint[], unit: string | null | undefined): string {
  if (points.length === 0) return `${title}: داده‌ای برای نمایش نیست.`;
  const total = points.reduce((s, p) => s + p.value, 0);
  const parts = points.map((p) => `${p.label} ${withUnit(p.value, unit)}${total > 0 ? ` (${fa(Math.round((p.value / total) * 100))}٪)` : ""}`);
  return `${title}: ${parts.join("، ")}.`;
}

type Row = Record<string, unknown>;

export interface TableShape {
  columns: string[];
  /** Columns whose every filled cell is a number. */
  numeric: Set<string>;
}

export function tableShape(rows: Row[]): TableShape {
  const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const numeric = new Set(
    columns.filter((c) => {
      const filled = rows.map((r) => r[c]).filter((v) => v !== null && v !== undefined && v !== "");
      return filled.length > 0 && filled.every((v) => typeof v === "number");
    }),
  );
  return { columns, numeric };
}

/** «بیشترین: کارگاه طراحی لوگو با ۱۸ رزرو» from the first text column and the first number column. */
export function tableTakeaway(rows: Row[]): string | null {
  if (rows.length < 2) return null;
  const { columns, numeric } = tableShape(rows);
  const numCol = columns.find((c) => numeric.has(c));
  const nameCol = columns.find((c) => !numeric.has(c));
  if (!numCol || !nameCol) return null;
  let best = rows[0];
  for (const r of rows) if ((r[numCol] as number) > (best[numCol] as number)) best = r;
  const value = best[numCol] as number;
  if (value <= 0) return null;
  return `بیشترین: ${String(best[nameCol] ?? "")} با ${formatNumber(value)} ${numCol}.`;
}

export function tableSummary(title: string, rows: Row[]): string {
  if (rows.length === 0) return `${title}: داده‌ای برای نمایش نیست.`;
  const { columns } = tableShape(rows);
  return `${title}: جدول با ${fa(rows.length)} ردیف و ستون‌های ${columns.join("، ")}. ${tableTakeaway(rows) ?? ""}`.trim();
}
