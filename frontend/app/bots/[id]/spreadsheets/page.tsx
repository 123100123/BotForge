"use client";

import { AnalystTab } from "@/components/analyst/analyst-tab";
import { useBusiness } from "@/components/app/business-context";
import { PageHeader } from "@/components/ui/page-header";

export default function SpreadsheetsPage() {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="تحلیل فایل اکسل" description="فایل اکسل روزانه را بارگذاری کنید تا خلاصه و هشدارهایش را ببینید." />
      <AnalystTab bot={bot} />
    </>
  );
}
