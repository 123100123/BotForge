"use client";

import { useState } from "react";
import { BarChart } from "@/components/charts/bar-chart";
import { BreakdownList } from "@/components/charts/breakdown-list";
import { StatTile } from "@/components/charts/stat-tile";
import { ErrorNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime, formatNumber } from "@/lib/format";
import type { AnalysisAnomaly, AnalysisProfileOut, AnalysisRunOut, MetricValue } from "@/lib/types";
import { SEVERITY_LABELS, SEVERITY_VARIANT, STATUS_LABELS, STATUS_VARIANT } from "./labels";

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function MetricTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">داده‌ای برای نمایش نیست.</p>;
  const headers = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-max text-start text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            {headers.map((h) => (
              <th key={h} scope="col" className="px-3 py-2 text-start font-medium whitespace-nowrap">
                <bdi>{h}</bdi>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t">
              {headers.map((h) => (
                <td key={h} className="px-3 py-2 whitespace-nowrap">
                  <bdi>{cellText(row[h])}</bdi>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricView({ metric }: { metric: MetricValue }) {
  if (metric.kind === "scalar") {
    return <StatTile label={metric.label} value={metric.value} unit={metric.unit} previous={metric.previous} />;
  }
  return (
    <Card className="gap-3 py-4 sm:col-span-2">
      <CardHeader>
        <CardTitle className="text-sm">{metric.label}</CardTitle>
      </CardHeader>
      <CardContent>
        {metric.kind === "series" && <BarChart points={metric.series ?? []} label={metric.label} unit={metric.unit} />}
        {metric.kind === "breakdown" && <BreakdownList points={metric.series ?? []} unit={metric.unit} />}
        {metric.kind === "table" && <MetricTable rows={metric.rows ?? []} />}
      </CardContent>
    </Card>
  );
}

function AnomalyRow({ a }: { a: AnalysisAnomaly }) {
  const parts: string[] = [];
  if (a.value !== null) parts.push(`مقدار ${formatNumber(a.value)}`);
  if (a.expected !== null) parts.push(`انتظار ${formatNumber(a.expected)}`);
  return (
    <li className="flex flex-col gap-1.5 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium">{a.label}</span>
        <span className="text-xs text-muted-foreground">
          ستون <bdi>{a.field}</bdi>
          {a.group && (
            <>
              {" · "}
              <bdi>{a.group}</bdi>
            </>
          )}
          {parts.length > 0 && ` · ${parts.join("، ")}`}
        </span>
      </div>
      <Badge variant={SEVERITY_VARIANT[a.severity] ?? "accent"}>{SEVERITY_LABELS[a.severity] ?? a.severity}</Badge>
    </li>
  );
}

function NameList({ title, names, tone }: { title: string; names: string[]; tone: "warning" | "success" }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h4 className="text-sm font-semibold">{title}</h4>
      {names.length === 0 ? (
        <p className="text-sm text-muted-foreground">موردی نیست.</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {names.map((n) => (
            <li key={n}>
              <Badge variant={tone}>
                <bdi>{n}</bdi>
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The result of one run: metrics and anomalies, or what changed in the file's layout, or the error. */
export function RunResult({
  run,
  profile,
  onUpdateProfile,
}: {
  run: AnalysisRunOut;
  profile: AnalysisProfileOut | null;
  /** Creates a new profile from the run's upload; throws a Persian error to show it here. */
  onUpdateProfile: (run: AnalysisRunOut, profile: AnalysisProfileOut | null) => Promise<void>;
}) {
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function update() {
    setUpdating(true);
    setError(null);
    try {
      await onUpdateProfile(run, profile);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setUpdating(false);
    }
  }

  const metrics = run.metrics ?? [];
  const anomalies = run.anomalies ?? [];
  const profileName = profile?.name ?? "تحلیل";

  return (
    <Card className="gap-4 py-5">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <CardTitle className="text-base">
            نتیجهٔ تحلیل «{profileName}»
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            {run.filename && (
              <>
                <bdi>{run.filename}</bdi>
                {" · "}
              </>
            )}
            {formatDateTime(run.created_at)}
          </p>
        </div>
        <Badge variant={STATUS_VARIANT[run.status] ?? "secondary"}>{STATUS_LABELS[run.status] ?? run.status}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {run.status === "ok" && (
          <>
            {run.narrative && <p className="rounded-lg bg-accent/40 p-3 text-sm leading-8">{run.narrative}</p>}
            {metrics.length === 0 ? (
              <p className="text-sm text-muted-foreground">این اجرا شاخصی نداشت.</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {metrics.map((m) => (
                  <MetricView key={m.id} metric={m} />
                ))}
              </div>
            )}
            <section className="flex flex-col gap-2">
              <h4 className="text-sm font-semibold">
                ناهنجاری‌ها{anomalies.length > 0 && <span className="ms-1 text-muted-foreground">({fa(anomalies.length)})</span>}
              </h4>
              {anomalies.length === 0 ? (
                <p className="text-sm text-muted-foreground">ناهنجاری‌ای پیدا نشد.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {anomalies.map((a, i) => (
                    <AnomalyRow key={`${a.check_id}-${i}`} a={a} />
                  ))}
                </ul>
              )}
            </section>
          </>
        )}

        {run.status === "schema_changed" && (
          <div className="flex flex-col gap-4 rounded-lg border border-warning/40 bg-warning/10 p-4">
            <p className="text-sm leading-7 font-medium">
              این فایل با پروفایل «{profileName}» مطابقت ندارد
            </p>
            <p className="text-sm leading-7 text-muted-foreground">
              ستون‌های فایل با ستون‌های مورد انتظار پروفایل فرق دارد، برای همین تحلیل اجرا نشد تا نتیجهٔ نادرست نگیرید.
              اگر ساختار جدید درست است، پروفایل را از همین فایل به‌روز کنید.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <NameList title="ستون‌های گمشده" names={run.schema_diff?.missing ?? []} tone="warning" />
              <NameList title="ستون‌های جدید" names={run.schema_diff?.new ?? []} tone="success" />
            </div>
            {error && <ErrorNote>{error}</ErrorNote>}
            <div className="flex flex-col gap-1.5">
              <Button
                type="button"
                onClick={() => void update()}
                disabled={updating || !run.upload_id}
                className="w-full sm:w-fit"
              >
                {updating ? "در حال ساخت…" : "به‌روزرسانی پروفایل"}
              </Button>
              {!run.upload_id && <p className="text-xs text-muted-foreground">فایل این اجرا دیگر در دسترس نیست.</p>}
            </div>
          </div>
        )}

        {run.status === "failed" && <ErrorNote>{run.error || "تحلیل این فایل با خطا روبه‌رو شد."}</ErrorNote>}
      </CardContent>
    </Card>
  );
}
