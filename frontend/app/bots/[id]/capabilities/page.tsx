"use client";

import { CapabilityCenter } from "@/components/capabilities/capability-center";
import { PageHeader } from "@/components/ui/page-header";

export default function CapabilitiesPage() {
  return (
    <>
      <PageHeader
        title="قابلیت‌ها"
        description="هر کاری که ربات برای کسب‌وکارتان انجام می‌دهد؛ روشن یا خاموش کنید. پیش از هر تغییر، اثر آن را می‌بینید."
      />
      <CapabilityCenter />
    </>
  );
}
