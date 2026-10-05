"use client";

import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { useLoader } from "@/components/app/use-loader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { fa, formatDateTime } from "@/lib/format";
import type { Bot } from "@/lib/types";

/** Data Analyst (stub): saved analysis profiles. W2-FE-AN adds upload, profile review and runs. */
export function AnalystTab({ bot }: { bot: Bot }) {
  const { data, error } = useLoader(() => api.listAnalysisProfiles(bot.id), bot.id);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <LoadingBlock />;
  if (data.length === 0) {
    return (
      <EmptyState title="هنوز پروفایل تحلیلی ساخته نشده است">
        یک فایل اکسل یا CSV بارگذاری کنید تا تحلیلگر داده برای آن شاخص‌ها و هشدارها را بسازد.
      </EmptyState>
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {data.map((p) => (
        <Card key={p.id} className="gap-2 py-4">
          <CardHeader className="flex-row items-center justify-between gap-2">
            <CardTitle className="text-sm">{p.name}</CardTitle>
            {p.daily_report && <Badge variant="accent">گزارش روزانه</Badge>}
          </CardHeader>
          <CardContent className="flex flex-col gap-1 text-sm text-muted-foreground">
            <span>
              {fa(p.metrics.length)} شاخص، {fa(p.checks.length)} بررسی
            </span>
            <span>تعداد اجرا: {fa(p.runs_count)}</span>
            <span>ساخته‌شده در {formatDateTime(p.created_at)}</span>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
