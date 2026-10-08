"use client";

import { AnalystTab } from "@/components/analyst/analyst-tab";
import { useBusiness } from "@/components/app/business-context";
import { PageHeader } from "@/components/ui/page-header";

export default function SpreadsheetsPage() {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="تحلیل فایل اکسل" description="فایل اکسل یا CSV را بارگذاری کنید؛ دستیار شاخص‌ها و هشدارها را پیشنهاد می‌دهد و هر فایل تازه با همان پروفایل تحلیل می‌شود." />
      <AnalystTab bot={bot} />
    </>
  );
}
