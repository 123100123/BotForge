"use client";

import Link from "next/link";
import { useMemo, type ReactNode } from "react";
import { Blocks, Rocket } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { operationsScope } from "@/lib/nav";
import { sectionHref } from "@/lib/routes";
import type { Bot, DataCollection } from "@/lib/types";

type Route = Parameters<typeof operationsScope>[1];

/** The collections an Operations route shows (lib/nav.ts operationsScope), in display order. */
export function useScope(route: Route): { bot: Bot; collections: DataCollection[]; loading: boolean } {
  const { bot, collections: all, dataStatus } = useBusiness();
  const collections = useMemo(() => {
    const byKey = new Map(all.map((c) => [c.key, c]));
    return operationsScope(all, route)
      .map((k) => byKey.get(k))
      .filter((c): c is DataCollection => c !== undefined);
  }, [all, route]);
  return { bot, collections, loading: dataStatus === "loading" };
}

/** Page frame of an Operations view: the header, then a skeleton / the «not active» state / the content. */
export function OperationsPage({
  title,
  description,
  actions,
  loading,
  inactive,
  children,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  loading: boolean;
  /** True when no collection of this view exists in the active version. */
  inactive: boolean;
  children: ReactNode;
}) {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title={title} description={description} actions={inactive || loading ? undefined : actions} />
      {loading ? (
        <Skeleton className="h-64 w-full" />
      ) : inactive ? (
        bot.active_revision_id === null ? (
          <EmptyState
            icon={<Rocket />}
            as="h2"
            title="هنوز نسخهٔ فعالی وجود ندارد"
            description="ابتدا در «تغییرات» ربات را بسازید و تأیید کنید؛ بعد این بخش داده‌ها را نشان می‌دهد."
            action={
              <Button asChild variant="secondary">
                <Link href={sectionHref(bot.id, "changes")}>رفتن به تغییرات</Link>
              </Button>
            }
          />
        ) : (
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
        )
      ) : (
        children
      )}
    </>
  );
}
