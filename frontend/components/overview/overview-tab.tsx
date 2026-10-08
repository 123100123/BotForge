"use client";

import { useOpenSection } from "@/components/app/shell/use-open-section";
import { useState } from "react";
import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { useLoader } from "@/components/app/use-loader";
import { StatTile } from "@/components/charts/stat-tile";
import { PeriodSelect } from "@/components/reports/period-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
 */
export function OverviewTab({ bot }: { bot: Bot }) {
  const [period, setPeriod] = useState<Period>("7d");
  const { data, error } = useLoader(() => api.getOverview(bot.id, period), `${bot.id}:${period}`);
  const caps = useLoader(() => api.listCapabilities(bot.id), bot.id);
  const nameById = new Map(caps.data?.categories.flatMap((c) => c.capabilities).map((c) => [c.id, c.name]) ?? []);
  const open = useOpenSection();

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="text-h2">نمای کلی کسب‌وکار</h2>
          <p className="text-sm text-muted-foreground">شاخص‌های کلیدی، قابلیت‌های فعال و آخرین رویدادها</p>
        </div>
        <PeriodSelect value={period} onChange={setPeriod} />
      </header>

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
                  <Button onClick={() => open("settings")}>اتصال به تلگرام</Button>
                  <Button variant="outline" onClick={() => open("simulator")}>
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
                <section aria-label="شاخص‌های کلیدی" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {data.kpis.map((m) => (
                    <StatTile key={m.id} label={m.label} value={m.value} unit={m.unit} previous={m.previous} />
                  ))}
                </section>
              )}
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
                        <li
                          key={`${a.at}-${i}`}
                          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-sm"
                        >
                          <span>{a.text}</span>
                          <span className="text-caption text-muted-foreground">{relativeTime(a.at)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </>
          )}

          <Card>
            <CardHeader className="flex-row items-center justify-between gap-2">
              <CardTitle className="text-base">
                قابلیت‌های فعال{data.enabled_capabilities.length > 0 && ` (${fa(data.enabled_capabilities.length)})`}
              </CardTitle>
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => open("capabilities")}>
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
                        className="rounded-xs"
                      >
                        <Badge variant="accent" className="cursor-pointer hover:bg-accent/70">
                          <span aria-hidden className="text-success-text">
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
