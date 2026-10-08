"use client";

import { useState } from "react";
import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { useLoader } from "@/components/app/use-loader";
import type { WorkspaceTab } from "@/components/app/workspace";
import { openSection } from "@/components/capabilities/labels";
import { StatTile } from "@/components/charts/stat-tile";
import { PeriodSelect } from "@/components/reports/period-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LaunchChecklist } from "@/components/app/launch-checklist";
import { PageHeader } from "@/components/app/presentation";
import { api } from "@/lib/api";
import { fa, relativeTime } from "@/lib/format";
import type { Bot, OverviewOut, Period } from "@/lib/types";

function isEmpty(data: OverviewOut): boolean {
  const noNumbers = data.kpis.every((m) => m.kind !== "scalar" || m.value === null || m.value === 0);
  return noNumbers && data.activity.length === 0;
}

/**
 * Overview: the state of the business at a glance. Everything comes from the reports API: KPIs for the picked
 * period with their change against the previous one, the enabled capabilities and the latest activity.
 * `onOpenTab` is optional: without it the links activate the sidebar trigger.
 */
export function OverviewTab({ bot, onOpenTab }: { bot: Bot; onOpenTab?: (tab: WorkspaceTab) => void }) {
  const [period, setPeriod] = useState<Period>("7d");
  const { data, error } = useLoader(() => api.getOverview(bot.id, period), `${bot.id}:${period}`);
  const caps = useLoader(() => api.listCapabilities(bot.id), bot.id);
  const nameById = new Map(caps.data?.categories.flatMap((c) => c.capabilities).map((c) => [c.id, c.name]) ?? []);
  const open = (tab: WorkspaceTab) => openSection(tab, onOpenTab);

  return (
    <div className="flex min-w-0 flex-col gap-7">
      <PageHeader eyebrow="میز کار" title="نمای کلی کسب‌وکار" description="شاخص‌های کلیدی، آمادگی راه‌اندازی و تازه‌ترین اتفاق‌های ربات در یک نگاه" action={<PeriodSelect value={period} onChange={setPeriod} />} />
      <LaunchChecklist bot={bot} onOpenTab={open} />

      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : !data ? (
        <LoadingBlock />
      ) : (
        <>
          {isEmpty(data) ? (
            <EmptyState
              title="هنوز داده‌ای ثبت نشده"
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <Button onPress={() => open("settings")}>اتصال به تلگرام</Button>
                  <Button variant="outline" onPress={() => open("simulator")}>
                    تست در شبیه‌ساز
                  </Button>
                </div>
              }
            >
              هنوز داده‌ای ثبت نشده؛ ربات را به تلگرام وصل کنید یا در شبیه‌ساز تست کنید.
            </EmptyState>
          ) : (
            <>
              {data.kpis.length > 0 && (
                <section aria-label="شاخص‌های کلیدی" className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
                  {data.kpis.map((m) => (
                    <StatTile key={m.id} label={m.label} value={m.value} unit={m.unit} previous={m.previous} />
                  ))}
                </section>
              )}
              <Card className="rounded-2xl border border-border">
                <CardHeader>
                  <CardTitle className="text-base">فعالیت‌های اخیر</CardTitle>
                </CardHeader>
                <CardContent>
                  {data.activity.length === 0 ? (
                    <p className="text-sm text-muted-foreground">هنوز فعالیتی ثبت نشده است.</p>
                  ) : (
                    <ul className="flex flex-col divide-y divide-border">
                      {data.activity.map((a, i) => (
                        <li
                          key={`${a.at}-${i}`}
                          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3 text-sm"
                        >
                          <span>{a.text}</span>
                          <span className="text-xs text-muted-foreground">{relativeTime(a.at)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </>
          )}

          <Card className="rounded-2xl border border-border">
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
              <CardTitle className="text-base">
                قابلیت‌های فعال{data.enabled_capabilities.length > 0 && ` (${fa(data.enabled_capabilities.length)})`}
              </CardTitle>
              <Button variant="ghost" size="sm" className="h-auto p-0" onPress={() => open("capabilities")}>
                مدیریت قابلیت‌ها
              </Button>
            </CardHeader>
            <CardContent>
              {data.enabled_capabilities.length === 0 ? (
                <p className="text-sm text-muted-foreground">هنوز قابلیتی فعال نیست.</p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {data.enabled_capabilities.map((id) => (
                    <li key={id}>
                      <button
                        type="button"
                        onClick={() => open("capabilities")}
                        className="rounded-full outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40"
                      >
                        <Badge variant="accent" className="cursor-pointer hover:bg-accent/70">
                          <span aria-hidden className="text-success">
                            ●
                          </span>
                          {nameById.get(id) ?? id}
                        </Badge>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
