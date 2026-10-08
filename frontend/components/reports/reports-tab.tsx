"use client";

import { useState } from "react";
import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { useLoader } from "@/components/app/use-loader";
import type { WorkspaceTab } from "@/components/app/workspace";
import { openSection } from "@/components/capabilities/labels";
import { MetricGrid } from "@/components/reports/metric-view";
import { PeriodSelect } from "@/components/reports/period-select";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/app/presentation";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Bot, CapabilityOut, Period } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One report row: a capability and one of its spec keys (the key the report endpoint is called with). */
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
        <span dir="ltr" className="ms-1.5 text-xs text-muted-foreground">
          {row.key}
        </span>
      )}
    </>
  );
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

  // One row per spec key. Module capabilities have no spec keys and no report endpoint of their own.
  const reportable: ReportRow[] = data.categories
    .flatMap((c) => c.capabilities)
    .filter((c) => c.enabled && c.metrics.length > 0 && c.spec_keys.length > 0)
    .flatMap((cap) => cap.spec_keys.map((key) => ({ cap, key, multi: cap.spec_keys.length > 1 })));
  if (reportable.length === 0) {
    return (
      <EmptyState
        title="هنوز گزارشی وجود ندارد"
        action={
          <Button variant="outline" onPress={() => openSection("capabilities", onOpenTab)}>
            رفتن به قابلیت‌ها
          </Button>
        }
      >
        بعد از فعال‌کردن قابلیت‌هایی مثل رزرو یا سفارش، گزارش آن‌ها اینجا نمایش داده می‌شود.
      </EmptyState>
    );
  }

  const current = reportable.find((r) => selected?.botId === bot.id && r.key === selected.key) ?? reportable[0];

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader eyebrow="بینش" title="گزارش‌های کسب‌وکار" description="عملکرد هر قابلیت را در بازه‌های زمانی مختلف ببینید و روندها را مقایسه کنید." action={<PeriodSelect value={period} onChange={setPeriod} />} />
      <div className="grid min-w-0 gap-5 lg:grid-cols-[15rem_minmax(0,1fr)] lg:items-start">
      <nav aria-label="قابلیت‌های دارای گزارش" className="app-subtle-surface min-w-0 p-3 lg:sticky lg:top-24">
        <p className="mb-3 px-2 text-xs font-bold text-muted-foreground">گزارش‌های فعال</p>
        <ul className="flex flex-wrap gap-2 lg:flex-col lg:gap-1">
          {reportable.map((r) => {
            const active = r.key === current.key;
            return (
              <li key={`${r.cap.id}:${r.key}`}>
                <button
                  type="button"
                  aria-current={active ? "true" : undefined}
                  onClick={() => setSelected({ botId: bot.id, key: r.key })}
                  className={cn(
                    "w-full rounded-xl border px-3 py-2.5 text-start text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                    active
                      ? "border-primary/35 bg-primary/10 font-bold text-primary"
                      : "bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  <RowLabel row={r} />
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
          <h2 className="text-xl font-bold">
            <RowLabel row={current} />
          </h2>
        </div>
        <ReportBody botId={bot.id} capKey={current.key} period={period} />
      </div>
      </div>
    </div>
  );
}
