"use client";

import { useId, type ReactNode } from "react";
import { BreakdownList } from "@/components/charts/breakdown-list";
import { LineChart } from "@/components/charts/line-chart";
import { MetricStrip, type MetricStripItem } from "@/components/app/metric-strip";
import {
  breakdownSummary,
  breakdownTakeaway,
  seriesSummary,
  seriesTakeaway,
  tableShape,
  tableSummary,
  tableTakeaway,
} from "@/components/reports/takeaways";
import { MetricTable, type MetricColumn } from "@/components/reports/metric-table";
import { fa, formatNumber } from "@/lib/format";
import { metricPolarity } from "@/lib/polarity";
import type { MetricValue, Period, SeriesPoint } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Series with fewer points than this are a short list of numbers; a line through three points says nothing. */
const MIN_TREND_POINTS = 4;

/**
 * One chart in a bordered panel: a plain title (h3), a one-line takeaway computed from the data, the chart
 * itself and a sentence for screen readers (the chart is a graphic; this is its text equivalent).
 */
export function ChartPanel({
  title,
  takeaway,
  summary,
  children,
  className,
}: {
  title: string;
  takeaway?: string | null;
  summary: string;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("flex min-w-0 flex-col gap-3 rounded-md border border-border bg-surface p-5", className)}>
      <div className="flex flex-col gap-0.5">
        <h3 id={id} className="text-h3 text-fg">
          {title}
        </h3>
        {takeaway && <p className="text-small text-fg-secondary">{takeaway}</p>}
      </div>
      <p className="sr-only">{summary}</p>
      {children}
    </section>
  );
}

/** A few points as plain numbers, each with the same point of the comparison period when there is one. */
function NumberList({ points, unit, compare, compareLabel }: { points: SeriesPoint[]; unit?: string | null; compare?: SeriesPoint[] | null; compareLabel: string }) {
  if (points.length === 0) return <p className="text-small text-fg-muted">داده‌ای برای نمایش نیست.</p>;
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
      {points.map((p, i) => (
        <div key={`${p.label}-${i}`} className="flex flex-col gap-0.5 border-s-2 border-chart-1 ps-3">
          <dt className="text-caption text-fg-muted">{p.label}</dt>
          <dd className="flex flex-wrap items-baseline gap-x-1.5">
            <span className="text-metric-sm text-fg">{formatNumber(p.value)}</span>
            {unit && <span className="text-caption text-fg-muted">{unit}</span>}
          </dd>
          {compare?.[i] && (
            <dd className="text-caption text-fg-muted">
              {compareLabel}: {formatNumber(compare[i].value)}
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

function splitStrips<T>(items: T[]): T[][] {
  const groups = Math.ceil(items.length / 5);
  const size = Math.ceil(items.length / Math.max(1, groups));
  return Array.from({ length: groups }, (_, g) => items.slice(g * size, (g + 1) * size));
}

/** Columns of a metric table: every key of its rows, numbers detected from the data. */
function columnsOf(rows: Record<string, unknown>[]): MetricColumn[] {
  const { columns, numeric } = tableShape(rows);
  return columns.map((key) => ({ key, label: key, numeric: numeric.has(key) }));
}

/** A breakdown as a ranked table: position, name, value, share of the total. */
function rankingOf(metric: MetricValue): { columns: MetricColumn[]; rows: Record<string, unknown>[] } {
  const points = metric.series ?? [];
  const total = points.reduce((s, p) => s + p.value, 0);
  const valueLabel = metric.unit ? `مقدار (${metric.unit})` : "مقدار";
  return {
    columns: [
      { key: "rank", label: "رتبه", numeric: true, narrow: true, render: (v) => fa(v as number) },
      { key: "name", label: "مورد" },
      { key: "value", label: valueLabel, numeric: true },
      { key: "share", label: "سهم", numeric: true, narrow: true, render: (v) => `${fa(v as number)}٪` },
    ],
    rows: points.map((p, i) => ({ rank: i + 1, name: p.label, value: p.value, share: total > 0 ? Math.round((p.value / total) * 100) : 0 })),
  };
}

/**
 * All metrics of a report in reading order: scalars as a metric strip with period comparison, trends
 * (a line from four points, else numbers), breakdowns as labelled bars (or ranked tables), then tables.
 * `compare` holds the previous period's series by metric id, drawn dashed behind the trend.
 */
export function ReportMetrics({
  metrics,
  period,
  compare = {},
  compareLabel = "دورهٔ قبل",
  breakdownAs = "bars",
}: {
  metrics: MetricValue[];
  /** The report period; null for data that has none (a spreadsheet run). */
  period: Period | null;
  compare?: Record<string, SeriesPoint[]>;
  compareLabel?: string;
  breakdownAs?: "bars" | "table";
}) {
  const scalars = metrics.filter((m) => m.kind === "scalar");
  const series = metrics.filter((m) => m.kind === "series");
  const breakdowns = metrics.filter((m) => m.kind === "breakdown");
  const tables = metrics.filter((m) => m.kind === "table");
  const stripItems: MetricStripItem[] = scalars.map((m) => ({
    id: m.id,
    label: m.label,
    value: m.value,
    unit: m.unit,
    previous: m.previous,
    polarity: metricPolarity(m.id),
  }));
  const charts = [...series, ...breakdowns.filter(() => breakdownAs === "bars")];
  const rankings = breakdownAs === "table" ? breakdowns : [];

  return (
    <div className="flex flex-col gap-4">
      {splitStrips(stripItems).map((items, i) => (
        <MetricStrip key={i} items={items} />
      ))}

      {charts.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          {charts.map((m, index) => {
            const points = m.series ?? [];
            // An odd one out at the end takes the full row instead of leaving a hole.
            const span = charts.length % 2 === 1 && index === charts.length - 1 ? "lg:col-span-2" : undefined;
            if (m.kind === "series") {
              const trend = points.length >= MIN_TREND_POINTS;
              const cmp = compare[m.id] ?? null;
              return (
                <ChartPanel key={m.id} className={span} title={m.label} takeaway={seriesTakeaway(points, m.unit, period)} summary={seriesSummary(m.label, points, m.unit)}>
                  {trend ? (
                    <LineChart points={points} label={m.label} unit={m.unit} compare={cmp} compareLabel={compareLabel} />
                  ) : (
                    <NumberList points={points} unit={m.unit} compare={cmp} compareLabel={compareLabel} />
                  )}
                </ChartPanel>
              );
            }
            return (
              <ChartPanel key={m.id} className={span} title={m.label} takeaway={breakdownTakeaway(points, m.unit)} summary={breakdownSummary(m.label, points, m.unit)}>
                <BreakdownList points={points} unit={m.unit} />
              </ChartPanel>
            );
          })}
        </div>
      )}

      {rankings.map((m) => {
        const ranking = rankingOf(m);
        return (
          <ChartPanel key={m.id} title={m.label} takeaway={breakdownTakeaway(m.series ?? [], m.unit)} summary={breakdownSummary(m.label, m.series ?? [], m.unit)}>
            <MetricTable label={m.label} columns={ranking.columns} rows={ranking.rows} />
          </ChartPanel>
        );
      })}

      {tables.map((m) => {
        const rows = m.rows ?? [];
        return (
          <ChartPanel key={m.id} title={m.label} takeaway={tableTakeaway(rows)} summary={tableSummary(m.label, rows)}>
            <MetricTable label={m.label} columns={columnsOf(rows)} rows={rows} />
          </ChartPanel>
        );
      })}
    </div>
  );
}
