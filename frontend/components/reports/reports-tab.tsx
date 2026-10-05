"use client";

import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { MetricSummary } from "@/components/app/metric-summary";
import { useLoader } from "@/components/app/use-loader";
import { api } from "@/lib/api";
import type { Bot, CapabilityReportOut } from "@/lib/types";

async function loadReports(botId: string): Promise<CapabilityReportOut[]> {
  const list = await api.listCapabilities(botId);
  const enabled = list.categories.flatMap((c) => c.capabilities).filter((c) => c.enabled && c.metrics.length > 0);
  return Promise.all(enabled.map((c) => api.getCapabilityReport(botId, c.spec_keys[0] ?? c.id, "7d")));
}

/** Reports section (stub): one block per enabled capability that has metrics. W1-FE-CC adds periods and charts. */
export function ReportsTab({ bot }: { bot: Bot }) {
  const { data, error } = useLoader(() => loadReports(bot.id), bot.id);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <LoadingBlock />;
  if (data.length === 0) {
    return (
      <EmptyState title="هنوز گزارشی وجود ندارد">
        بعد از فعال‌کردن قابلیت‌هایی مثل رزرو یا سفارش، گزارش آن‌ها اینجا نمایش داده می‌شود.
      </EmptyState>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {data.map((report) => (
        <section key={report.capability_id} aria-label={report.label} className="flex flex-col gap-3">
          <h2 className="text-base font-semibold">{report.label}</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {report.metrics.map((m) => (
              <MetricSummary key={m.id} metric={m} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
