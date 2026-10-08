"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { ChevronRightIcon, RefreshCwIcon } from "lucide-react";
import { AttentionList } from "@/components/app/attention-list";
import { useBusiness } from "@/components/app/business-context";
import { MetricStrip, type MetricStripItem } from "@/components/app/metric-strip";
import { Segmented } from "@/components/app/segmented";
import { useLoader } from "@/components/app/use-loader";
import { SuggestionChips } from "@/components/copilot/ask-panel";
import { useAssistant } from "@/components/copilot/assistant-provider";
import { suggestedQuestions } from "@/components/copilot/sources";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { upcomingResources, useAttention } from "@/lib/adapters/attention";
import { api } from "@/lib/api";
import { fa } from "@/lib/format";
import { metricPolarity } from "@/lib/polarity";
import { sectionHref } from "@/lib/routes";
import type { MetricValue, Period } from "@/lib/types";
import { ActivityFeed } from "./activity-feed";
import { SetupChecklist } from "./setup-checklist";
import { UpcomingList } from "./upcoming-list";

const PERIODS: { value: Period; label: string }[] = [
  { value: "today", label: "امروز" },
  { value: "7d", label: "۷ روز" },
  { value: "30d", label: "۳۰ روز" },
  { value: "this_month", label: "این ماه" },
];

/** Most important first; anything not listed follows in the order the API gave it. */
const KPI_PRIORITY = ["revenue", "order_count", "orders", "booking_count", "bookings", "customers", "rsvp_count", "open_requests", "event_count"];

function rank(id: string): number {
  const key = id.includes(".") ? id.slice(id.lastIndexOf(".") + 1) : id;
  const i = KPI_PRIORITY.indexOf(key);
  return i === -1 ? KPI_PRIORITY.length : i;
}

/** Up to five scalar KPIs, most important first. The API only returns KPIs of enabled capabilities. */
export function pickKpis(kpis: MetricValue[]): MetricStripItem[] {
  return kpis
    .filter((m) => m.kind === "scalar")
    .map((m, i) => ({ m, i }))
    .sort((a, b) => rank(a.m.id) - rank(b.m.id) || a.i - b.i)
    .slice(0, 5)
    .map(({ m }) => ({ id: m.id, label: m.label, value: m.value, unit: m.unit, previous: m.previous, polarity: metricPolarity(m.id) }));
}

function Section({ id, title, children, className }: { id: string; title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-labelledby={id} className={className}>
      <h2 id={id} className="mb-3 text-h2 text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

/**
 * Overview: what needs the owner now, the headline numbers of the period, what is coming up and what
 * happened lately. A setup checklist replaces the empty state while the business is not fully set up.
 */
export function OverviewPage() {
  const { bot, collections, capabilities } = useBusiness();
  const assistant = useAssistant();
  const attention = useAttention();
  const [period, setPeriod] = useState<Period>("7d");
  const [tick, setTick] = useState(0);
  const overview = useLoader(() => api.getOverview(bot.id, period), `${bot.id}:${period}:${tick}`);

  const kpis = useMemo(() => (overview.data ? pickKpis(overview.data.kpis) : []), [overview.data]);
  const questions = useMemo(() => suggestedQuestions(capabilities), [capabilities]);
  const hasEvents = upcomingResources(collections).length > 0;
  const enabledCount = capabilities.filter((c) => c.enabled).length;
  // While the checklist shows, it carries the setup steps; the list keeps the rest.
  const attentionItems = attention.gaps.any ? attention.items.filter((i) => !i.id.startsWith("setup-")) : attention.items;
  const loadingFirst = !overview.data && !overview.error;

  return (
    <>
      <PageHeader
        title="نمای کلی"
        actions={<Segmented<Period> label="بازهٔ زمانی" value={period} onChange={setPeriod} options={PERIODS} />}
      />
      <div className="mt-6 flex flex-col gap-8">
        {attention.gaps.any && <SetupChecklist bot={bot} gaps={attention.gaps} />}

        <Section id="ov-attention" title="نیازمند توجه">
          {attention.loading && attentionItems.length === 0 ? (
            <Skeleton className="h-12 w-full rounded-md" />
          ) : (
            <div className="flex flex-col gap-2">
              <AttentionList items={attentionItems} />
              {attention.failed > 0 && (
                <p className="flex flex-wrap items-center gap-2 text-caption text-fg-muted">
                  بعضی موارد بارگذاری نشد.
                  <Button variant="ghost" size="sm" onClick={attention.refresh}>
                    <RefreshCwIcon strokeWidth={1.75} />
                    تلاش دوباره
                  </Button>
                </p>
              )}
            </div>
          )}
        </Section>

        {overview.error ? (
          <ErrorState title="نمای کلی بارگذاری نشد" message={overview.error} onRetry={() => setTick((t) => t + 1)} className="rounded-md border border-border bg-surface" />
        ) : (
          <>
            {(loadingFirst || kpis.length > 0) && (
              <section aria-labelledby="ov-metrics">
                <h2 id="ov-metrics" className="sr-only">
                  شاخص‌های کلیدی
                </h2>
                <MetricStrip items={kpis} loading={loadingFirst} />
              </section>
            )}

            <div className={hasEvents ? "grid gap-8 xl:grid-cols-2" : undefined}>
              {hasEvents && (
                <Section id="ov-upcoming" title="پیش رو">
                  <UpcomingList items={attention.upcoming} loading={attention.loading} />
                </Section>
              )}
              <Section id="ov-activity" title="فعالیت‌های اخیر">
                {loadingFirst ? (
                  <div aria-hidden className="flex flex-col gap-2">
                    <Skeleton className="h-12 w-full rounded-md" />
                    <Skeleton className="h-12 w-full rounded-md" />
                  </div>
                ) : (
                  <ActivityFeed items={overview.data?.activity ?? []} />
                )}
              </Section>
            </div>
          </>
        )}

        <Section id="ov-ask" title="از دستیارتان بپرسید">
          <SuggestionChips questions={questions} onPick={(q) => assistant.open(q)} />
        </Section>

        <p className="text-small text-fg-secondary">
          <Link href={sectionHref(bot.id, "capabilities")} className="inline-flex items-center gap-1 rounded-xs font-medium text-brand-text underline-offset-4 hover:underline">
            {enabledCount > 0 ? `${fa(enabledCount)} قابلیت فعال` : "هنوز قابلیتی فعال نیست"}
            <ChevronRightIcon className="size-4 rtl:-scale-x-100" strokeWidth={1.75} aria-hidden />
          </Link>
        </p>
      </div>
    </>
  );
}
