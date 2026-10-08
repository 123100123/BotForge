"use client";

import { useBusiness } from "@/components/app/business-context";
import { DataTab } from "@/components/data/data-tab";
import { PageHeader } from "@/components/ui/page-header";

/** Every collection of the active version, including those whose capability is switched off. */
export default function RecordsPage() {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="همهٔ داده‌ها" description="همهٔ مجموعه‌های دادهٔ ربات، از جمله بخش‌هایی که قابلیتشان خاموش است." />
      <DataTab bot={bot} />
    </>
  );
}
