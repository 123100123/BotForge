"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { BarChart3Icon, MessageCircleQuestionIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { MetricStrip } from "@/components/app/metric-strip";
import { useAssistant } from "@/components/copilot/assistant-provider";
import { useLoader } from "@/components/app/use-loader";
import { isPeriod, PeriodSelect } from "@/components/reports/period-select";
import { ReportMetrics } from "@/components/reports/metric-view";
import { ScrollFade } from "@/components/reports/scroll-fade";
import { COMPARE_PERIOD, PERIOD_LABELS } from "@/components/reports/takeaways";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { sectionHref } from "@/lib/routes";
import type { Bot, CapabilityOut, CapabilityReportOut, Period, SeriesPoint } from "@/lib/types";
import { cn } from "@/lib/utils";

const DEFAULT_PERIOD: Period = "7d";

/** One report: a capability and one of its spec keys (the key the report endpoint and the URL use). */
interface ReportRow {
  cap: CapabilityOut;
  key: string;
  /** The capability has more than one spec key, so the key is shown next to its name. */
  multi: boolean;
}

function RowLabel({ row }: { row: ReportRow }) {
  return (
    <>
      {row.cap.name}
      {row.multi && (
        <span dir="ltr" className="ms-1.5 text-caption text-fg-muted">
          {row.key}
        </span>
      )}
    </>
  );
}

/** The prompt the «خلاصه با دستیار» button puts in the assistant's question box (it is not sent). */
export function summaryPrompt(label: string, period: Period): string {
  return `گزارش ${label} را برای دورهٔ ${PERIOD_LABELS[period]} خلاصه کن و نکته‌های مهمش را بگو.`;
}

function ReportSkeleton() {
  return (
    <div role="status" aria-label="در حال بارگذاری گزارش" className="flex flex-col gap-4">
      <MetricStrip loading count={3} />
      <div className="grid gap-4 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="flex flex-col gap-3 rounded-md border border-border bg-surface p-5">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-64 max-w-full" />
            <Skeleton className="h-[200px] w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

function ReportBody({
  botId,
  capKey,
  period,
  onReport,
}: {
  botId: string;
  capKey: string;
  period: Period;
  onReport: (report: CapabilityReportOut | null) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const { data, error } = useLoader(() => api.getCapabilityReport(botId, capKey, period), `${botId}:${capKey}:${period}:${attempt}`);
  const comparePeriod = COMPARE_PERIOD[period];
  // The comparison is a nicety: if it fails, the report simply has no dashed line.
  const previous = useLoader(
    () => (comparePeriod ? api.getCapabilityReport(botId, capKey, comparePeriod).catch(() => null) : Promise.resolve(null)),
    `${botId}:${capKey}:${comparePeriod ?? "none"}:${attempt}`,
  ).data;

  useEffect(() => {
    onReport(data);
  }, [data, onReport]);

  const compare = useMemo(() => {
    const out: Record<string, SeriesPoint[]> = {};
    for (const m of previous?.metrics ?? []) if (m.kind === "series" && m.series?.length) out[m.id] = m.series;
    return out;
  }, [previous]);

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data) return <ReportSkeleton />;
  if (data.metrics.length === 0) {
    return (
      <EmptyState
        icon={<BarChart3Icon />}
        title="برای این دوره هنوز داده‌ای ثبت نشده است."
        description="اگر این قابلیت تازه فعال شده، بعد از اولین فعالیت مشتری‌ها شاخص‌ها اینجا پیدا می‌شوند. می‌توانید بازهٔ دیگری را هم ببینید."
      />
    );
  }
  return (
    <ReportMetrics
      metrics={data.metrics}
      period={period}
      compare={compare}
      compareLabel={comparePeriod ? PERIOD_LABELS[comparePeriod] : "دورهٔ قبل"}
    />
  );
}

/**
 * Reports. One control row: a tab per enabled capability that has a report, and the period at the end. The
 * report is a URL (`/reports/[capability]?period=7d`), so it can be linked and survives a reload. Without a
 * capability in the path it redirects to the first report.
 */
export function ReportsTab({ bot, capabilityKey }: { bot: Bot; capabilityKey: string | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const assistant = useAssistant();
  const [attempt, setAttempt] = useState(0);
  const { data, error } = useLoader(() => api.listCapabilities(bot.id), `${bot.id}:${attempt}`);
  const [report, setReport] = useState<CapabilityReportOut | null>(null);

  const periodParam = params.get("period");
  const period: Period = isPeriod(periodParam) ? periodParam : DEFAULT_PERIOD;
  const base = sectionHref(bot.id, "reports");
  const query = (p: Period | null) => (p && p !== DEFAULT_PERIOD ? `?period=${p}` : "");

  // One row per spec key. Module capabilities have no spec keys and no report endpoint of their own.
  const reportable: ReportRow[] = useMemo(
    () =>
      (data?.categories ?? [])
        .flatMap((c) => c.capabilities)
        .filter((c) => c.enabled && c.metrics.length > 0 && c.spec_keys.length > 0)
        .flatMap((cap) => cap.spec_keys.map((key) => ({ cap, key, multi: cap.spec_keys.length > 1 }))),
    [data],
  );
  const current = reportable.find((r) => r.key === capabilityKey) ?? null;

  useEffect(() => {
    if (!capabilityKey && reportable.length > 0) router.replace(`${base}/${encodeURIComponent(reportable[0].key)}${query(period)}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capabilityKey, reportable]);

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data || (!capabilityKey && reportable.length > 0)) {
    return (
      <div className="flex flex-col gap-4" role="status" aria-label="در حال بارگذاری">
        <Skeleton className="h-11 w-full" />
        <ReportSkeleton />
      </div>
    );
  }
  if (reportable.length === 0) {
    return (
      <EmptyState
        icon={<BarChart3Icon />}
        title="هنوز گزارشی وجود ندارد"
        description="بعد از فعال‌کردن قابلیت‌هایی مثل رزرو یا سفارش، گزارش آن‌ها اینجا نمایش داده می‌شود."
        action={
          <Button variant="secondary" asChild>
            <Link href={sectionHref(bot.id, "capabilities")}>رفتن به قابلیت‌ها</Link>
          </Button>
        }
      />
    );
  }

  function setPeriod(next: Period) {
    router.replace(`${pathname}${query(next)}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-3 border-b border-border">
        <nav aria-label="قابلیت‌های دارای گزارش" className="min-w-0 flex-1">
          <ScrollFade>
            <ul className="flex w-max items-center gap-1">
              {reportable.map((r) => {
                const active = r.key === current?.key;
                return (
                  <li key={`${r.cap.id}:${r.key}`} className="shrink-0">
                    <Link
                      href={`${base}/${encodeURIComponent(r.key)}${query(period)}`}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "-mb-px inline-flex min-h-11 items-center border-b-2 border-transparent px-4 text-small font-medium whitespace-nowrap text-fg-muted transition-colors duration-fast hover:text-fg",
                        active && "border-brand text-fg",
                      )}
                    >
                      <RowLabel row={r} />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </ScrollFade>
        </nav>
        <PeriodSelect value={period} onChange={setPeriod} className="mb-1 shrink-0" />
      </div>

      {!current ? (
        <EmptyState
          as="h2"
          icon={<BarChart3Icon />}
          title="این گزارش پیدا نشد"
          description="ممکن است قابلیتش غیرفعال شده باشد. یکی از گزارش‌های بالا را انتخاب کنید."
        />
      ) : (
        <section aria-labelledby="report-title" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="flex min-w-0 flex-col gap-0.5">
              <h2 id="report-title" className="text-h2 text-fg">
                <RowLabel row={current} />
              </h2>
              <p className="text-caption text-fg-muted">
                {report && report.period === period ? `از ${formatDate(report.since)} تا ${formatDate(report.until)}` : PERIOD_LABELS[period]}
              </p>
            </div>
            <Button variant="secondary" size="sm" onClick={() => assistant.open(summaryPrompt(current.cap.name, period))}>
              <MessageCircleQuestionIcon aria-hidden />
              خلاصه با دستیار
            </Button>
          </div>
          <ReportBody key={`${current.key}:${period}`} botId={bot.id} capKey={current.key} period={period} onReport={setReport} />
        </section>
      )}
    </div>
  );
}
