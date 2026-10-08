"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeftIcon } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { useCapabilities } from "@/components/capabilities/capabilities-provider";
import { CapabilityDetailBody, CapabilityPrimaryAction } from "@/components/capabilities/capability-detail";
import { CapabilityState } from "@/components/capabilities/capability-row";
import { ToggleNoticeBar } from "@/components/capabilities/toggle-notice";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { sectionHref } from "@/lib/routes";

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** One capability on its own route (below 1280px, where the list has no detail pane). */
export default function CapabilityDetailPage() {
  const { capId } = useParams<{ capId: string }>();
  const id = safeDecode(capId);
  const { bot } = useBusiness();
  const { categories, error, byId, refresh } = useCapabilities();
  const listHref = sectionHref(bot.id, "capabilities");
  const cap = byId.get(id);

  const back = (
    <Link href={listHref} className="inline-flex w-fit items-center gap-1.5 rounded-xs text-small text-brand-text underline-offset-4 hover:underline">
      <ArrowLeftIcon className="size-4 rtl:-scale-x-100" strokeWidth={1.75} aria-hidden />
      بازگشت به قابلیت‌ها
    </Link>
  );

  if (error) {
    return (
      <>
        {back}
        <PageHeader title="قابلیت" />
        <ErrorState message={error} onRetry={() => void refresh()} />
      </>
    );
  }
  if (!categories) {
    return (
      <>
        {back}
        <div role="status" aria-label="در حال بارگذاری" className="flex flex-col gap-3">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-40 rounded-md" />
        </div>
      </>
    );
  }
  if (!cap) {
    return (
      <>
        {back}
        <PageHeader title="قابلیت پیدا نشد" />
        <EmptyState
          as="h2"
          title="این قابلیت وجود ندارد"
          description="ممکن است نشانی را اشتباه وارد کرده باشید."
          action={
            <Button asChild variant="secondary" size="sm">
              <Link href={listHref}>همهٔ قابلیت‌ها</Link>
            </Button>
          }
        />
      </>
    );
  }

  return (
    <>
      {back}
      <PageHeader
        title={cap.name}
        description={cap.description}
        actions={
          <>
            <CapabilityState cap={cap} />
            <CapabilityPrimaryAction cap={cap} />
          </>
        }
      />
      <ToggleNoticeBar />
      <div className="max-w-2xl">
        <CapabilityDetailBody cap={cap} level="h2" />
      </div>
    </>
  );
}
