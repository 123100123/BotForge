"use client";

import { useBusiness } from "@/components/app/business-context";
import { CapabilitiesTab } from "@/components/capabilities/capabilities-tab";
import { PageHeader } from "@/components/ui/page-header";

export default function CapabilitiesPage() {
  const { bot, reload } = useBusiness();
  return (
    <>
      <PageHeader title="قابلیت‌ها" description="هر کاری که ربات برای کسب‌وکارتان انجام می‌دهد؛ روشن یا خاموش کنید." />
      <CapabilitiesTab bot={bot} onBotChanged={reload} />
    </>
  );
}
