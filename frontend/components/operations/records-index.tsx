"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronLeft, Table2 } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { fa } from "@/lib/format";
import { isEventBooking } from "@/lib/nav";
import { sectionHref } from "@/lib/routes";
import type { DataCollection } from "@/lib/types";

const KIND_LABELS: Record<DataCollection["kind"], string> = {
  resource: "اطلاعات",
  booking: "ثبت‌نام و رزرو",
  request: "درخواست",
  orders: "سفارش",
};

/** Where a collection is worked on: its own Operations page while it is on, otherwise the generic table. */
function hrefOf(botId: string, c: DataCollection): string {
  if (c.enabled !== false) {
    if (c.kind === "orders") return sectionHref(botId, "orders");
    if (c.kind === "request") return sectionHref(botId, "requests");
    if (c.kind === "booking") return sectionHref(botId, isEventBooking(c) ? "events" : "bookings");
  }
  return sectionHref(botId, "records", { collection: c.key });
}

/** /records: every collection of the active version, including the ones whose capability is switched off. */
export function RecordsIndex() {
  const { bot, collections, dataStatus } = useBusiness();
  const [counts, setCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    let cancelled = false;
    Promise.all(
      collections.map((c) =>
        api.listRecords(bot.id, c.key, { limit: 1 }).then(
          (p) => [c.key, p.total] as const,
          () => null,
        ),
      ),
    ).then((entries) => {
      if (cancelled) return;
      const next: Record<string, number> = {};
      for (const e of entries) if (e) next[e[0]] = e[1];
      setCounts(next);
    });
    return () => {
      cancelled = true;
    };
  }, [bot.id, collections]);

  return (
    <>
      <PageHeader title="همهٔ داده‌ها" description="همهٔ مجموعه‌های دادهٔ ربات، از جمله بخش‌هایی که قابلیتشان خاموش است." />
      {dataStatus === "loading" ? (
        <Skeleton className="h-64 w-full" />
      ) : collections.length === 0 ? (
        <EmptyState
          icon={<Table2 />}
          as="h2"
          title="هنوز داده‌ای وجود ندارد"
          description="این ربات هنوز نسخهٔ فعالی ندارد. ابتدا در «تغییرات» ربات را بسازید و تأیید کنید."
          action={
            <Button asChild variant="secondary">
              <Link href={sectionHref(bot.id, "changes")}>رفتن به تغییرات</Link>
            </Button>
          }
        />
      ) : (
        <ul className="rounded-md border border-border bg-surface">
          {collections.map((c) => (
            <li key={c.key} className="border-b border-border last:border-b-0">
              <Link
                href={hrefOf(bot.id, c)}
                className="flex min-h-14 items-center gap-3 px-4 py-2 transition-colors duration-fast hover:bg-surface-sunken"
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className={c.enabled === false ? "truncate text-body font-medium text-fg-secondary" : "truncate text-body font-medium text-fg"}>
                    {c.label_plural}
                  </span>
                  <span className="text-small text-fg-muted">{KIND_LABELS[c.kind]}</span>
                </span>
                {c.enabled === false && <StatusBadge tone="neutral" marker>غیرفعال</StatusBadge>}
                {counts[c.key] !== undefined && (
                  <span className="min-w-8 text-end text-small text-fg-secondary tabular-nums">{fa(counts[c.key])}</span>
                )}
                <ChevronLeft aria-hidden className="size-4 shrink-0 text-fg-muted rtl:rotate-0" strokeWidth={1.75} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
