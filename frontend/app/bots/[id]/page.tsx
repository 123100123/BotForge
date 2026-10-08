"use client";

import { useBusiness } from "@/components/app/business-context";
import { OverviewTab } from "@/components/overview/overview-tab";
import { PageHeader } from "@/components/ui/page-header";

export default function OverviewPage() {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title={bot.name} />
      <OverviewTab bot={bot} />
    </>
  );
}
