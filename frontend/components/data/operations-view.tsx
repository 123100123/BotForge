"use client";

import Link from "next/link";
import { Blocks } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { DataTab } from "@/components/data/data-tab";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { operationsScope } from "@/lib/nav";
import { sectionHref } from "@/lib/routes";

type Route = Parameters<typeof operationsScope>[1];

const TITLES: Record<Route, { title: string; description: string }> = {
  orders: { title: "سفارش‌ها", description: "سفارش‌هایی که مشتری‌ها در ربات ثبت کرده‌اند." },
  events: { title: "رویدادها", description: "رویدادها و ثبت‌نام‌های آن‌ها." },
  bookings: { title: "رزروها", description: "رزروها و ثبت‌نام‌های مشتری‌ها." },
  requests: { title: "درخواست‌ها", description: "درخواست‌ها و فرم‌هایی که مشتری‌ها و کارکنان فرستاده‌اند." },
};

/**
 * An Operations page generated from the business's collections (lib/nav.ts operationsScope). For now it
 * hosts the existing DataTab focused on those collections; Phase 7 replaces it with the DataTable views.
 */
export function OperationsView({ route }: { route: Route }) {
  const { bot, collections, dataStatus } = useBusiness();
  const { title, description } = TITLES[route];
  const keys = operationsScope(collections, route);

  return (
    <>
      <PageHeader title={title} description={description} />
      {dataStatus === "loading" ? (
        <Skeleton className="h-64" />
      ) : keys.length === 0 ? (
        <EmptyState
          icon={<Blocks />}
          as="h2"
          title={`«${title}» در این کسب‌وکار فعال نیست`}
          description="این بخش وقتی نمایش داده می‌شود که قابلیت مربوط به آن در ربات فعال باشد."
          action={
            <Button asChild variant="secondary">
              <Link href={sectionHref(bot.id, "capabilities")}>رفتن به قابلیت‌ها</Link>
            </Button>
          }
        />
      ) : (
        <DataTab bot={bot} collectionKeys={keys} />
      )}
    </>
  );
}
