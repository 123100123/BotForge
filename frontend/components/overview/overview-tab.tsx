"use client";

import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { MetricSummary } from "@/components/app/metric-summary";
import { useLoader } from "@/components/app/use-loader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { Bot } from "@/lib/types";

/** Overview section (stub): last week's KPIs and recent activity. W1-FE-CC replaces the body. */
export function OverviewTab({ bot }: { bot: Bot }) {
  const { data, error } = useLoader(() => api.getOverview(bot.id, "7d"), bot.id);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <LoadingBlock />;

  return (
    <div className="flex flex-col gap-5">
      <section aria-label="شاخص‌های کلیدی" className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">شاخص‌های هفتهٔ گذشته</h2>
        {data.kpis.length === 0 ? (
          <EmptyState title="هنوز شاخصی وجود ندارد">
            با فعال‌کردن قابلیت‌ها و شروع کار ربات، شاخص‌های کسب‌وکار اینجا نمایش داده می‌شود.
          </EmptyState>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {data.kpis.map((m) => (
              <MetricSummary key={m.id} metric={m} />
            ))}
          </div>
        )}
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">فعالیت‌های اخیر</CardTitle>
        </CardHeader>
        <CardContent>
          {data.activity.length === 0 ? (
            <p className="text-sm text-muted-foreground">هنوز فعالیتی ثبت نشده است.</p>
          ) : (
            <ul className="flex flex-col divide-y">
              {data.activity.map((a, i) => (
                <li key={`${a.at}-${i}`} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-sm">
                  <span>{a.text}</span>
                  <span className="text-xs text-muted-foreground">{relativeTime(a.at)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
