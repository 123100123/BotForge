"use client";

import { useState } from "react";
import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { useLoader } from "@/components/app/use-loader";
import type { WorkspaceTab } from "@/components/app/workspace";
import { openSection } from "@/components/capabilities/labels";
import { MetricGrid } from "@/components/reports/metric-view";
import { PeriodSelect } from "@/components/reports/period-select";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Bot, CapabilityOut, Period } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The key a report is requested with: the first spec key, or the capability id for modules and presets. */
function reportKey(c: CapabilityOut): string {
  return c.spec_keys[0] ?? c.id;
}

function ReportBody({ botId, capKey, period }: { botId: string; capKey: string; period: Period }) {
  const { data, error } = useLoader(() => api.getCapabilityReport(botId, capKey, period), `${botId}:${capKey}:${period}`);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <LoadingBlock />;
  if (data.metrics.length === 0) {
    return <EmptyState title="هنوز داده‌ای برای این گزارش نیست">با شروع کار ربات، شاخص‌ها اینجا نمایش داده می‌شود.</EmptyState>;
  }
  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        از {formatDate(data.since)} تا {formatDate(data.until)}
      </p>
      <MetricGrid metrics={data.metrics} />
    </div>
  );
}

/**
 * Reports: pick an enabled capability on the right, then a period; its metrics render as stat tiles,
 * SVG charts, bar lists and tables. `onOpenTab` is optional (see the Capability Center).
 */
export function ReportsTab({ bot, onOpenTab }: { bot: Bot; onOpenTab?: (tab: WorkspaceTab) => void }) {
  const { data, error } = useLoader(() => api.listCapabilities(bot.id), bot.id);
  const [selected, setSelected] = useState<{ botId: string; key: string } | null>(null);
  const [period, setPeriod] = useState<Period>("7d");

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <LoadingBlock />;

  const reportable = data.categories.flatMap((c) => c.capabilities).filter((c) => c.enabled && c.metrics.length > 0);
  if (reportable.length === 0) {
    return (
      <EmptyState
        title="هنوز گزارشی وجود ندارد"
        action={
          <Button variant="outline" onClick={() => openSection("capabilities", onOpenTab)}>
            رفتن به قابلیت‌ها
          </Button>
        }
      >
        بعد از فعال‌کردن قابلیت‌هایی مثل رزرو یا سفارش، گزارش آن‌ها اینجا نمایش داده می‌شود.
      </EmptyState>
    );
  }

  const current = reportable.find((c) => selected?.botId === bot.id && reportKey(c) === selected.key) ?? reportable[0];

  return (
    <div className="flex flex-col gap-4 md:grid md:grid-cols-[13rem_minmax(0,1fr)] md:items-start md:gap-6">
      <nav aria-label="قابلیت‌های دارای گزارش">
        <ul className="flex flex-wrap gap-2 md:flex-col md:gap-1">
          {reportable.map((c) => {
            const active = c.id === current.id;
            return (
              <li key={c.id}>
                <button
                  type="button"
                  aria-current={active ? "true" : undefined}
                  onClick={() => setSelected({ botId: bot.id, key: reportKey(c) })}
                  className={cn(
                    "w-full rounded-md border px-3 py-2 text-start text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                    active
                      ? "border-primary/40 bg-accent font-medium text-accent-foreground"
                      : "bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {c.name}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">{current.name}</h2>
          <PeriodSelect value={period} onChange={setPeriod} />
        </div>
        <ReportBody botId={bot.id} capKey={reportKey(current)} period={period} />
      </div>
    </div>
  );
}
