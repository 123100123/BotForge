import { BarChart } from "@/components/charts/bar-chart";
import { BreakdownList } from "@/components/charts/breakdown-list";
import { LineChart } from "@/components/charts/line-chart";
import { StatTile } from "@/components/charts/stat-tile";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import type { MetricValue } from "@/lib/types";

/** Series up to this many points are bars (a few comparable buckets); longer ones read better as a line. */
const MAX_BAR_POINTS = 10;
const MAX_TABLE_ROWS = 50;

function cell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "بله" : "خیر";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function MetricTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  if (rows.length === 0 || columns.length === 0) return <p className="text-sm text-muted-foreground">داده‌ای برای نمایش نیست.</p>;
  const shown = rows.slice(0, MAX_TABLE_ROWS);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-muted-foreground">
            {columns.map((c) => (
              <th key={c} scope="col" className="px-2 py-2 text-start font-medium whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i} className="border-b last:border-b-0">
              {columns.map((c) => (
                <td key={c} className="px-2 py-2 text-start">
                  {cell(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <p className="pt-2 text-caption text-muted-foreground">فقط {formatNumber(shown.length)} ردیف اول از {formatNumber(rows.length)} نمایش داده شد.</p>
      )}
    </div>
  );
}

/** A non-scalar metric in its own card: a chart for series, a bar list for breakdowns, a table for rows. */
export function MetricCard({ metric }: { metric: MetricValue }) {
  const points = metric.series ?? [];
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="text-sm">{metric.label}</CardTitle>
      </CardHeader>
      <CardContent>
        {metric.kind === "series" &&
          (points.length <= MAX_BAR_POINTS ? (
            <BarChart points={points} label={metric.label} unit={metric.unit} />
          ) : (
            <LineChart points={points} label={metric.label} unit={metric.unit} />
          ))}
        {metric.kind === "breakdown" && <BreakdownList points={points} unit={metric.unit} />}
        {metric.kind === "table" && <MetricTable rows={metric.rows ?? []} />}
      </CardContent>
    </Card>
  );
}

/** All metrics of a report: scalars as tiles first, then one card per series, breakdown or table. */
export function MetricGrid({ metrics }: { metrics: MetricValue[] }) {
  const scalars = metrics.filter((m) => m.kind === "scalar");
  const others = metrics.filter((m) => m.kind !== "scalar");
  return (
    <div className="flex flex-col gap-4">
      {scalars.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {scalars.map((m) => (
            <StatTile key={m.id} label={m.label} value={m.value} unit={m.unit} previous={m.previous} />
          ))}
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        {others.map((m) => (
          <div key={m.id} className={m.kind === "table" ? "xl:col-span-2" : undefined}>
            <MetricCard metric={m} />
          </div>
        ))}
      </div>
    </div>
  );
}
