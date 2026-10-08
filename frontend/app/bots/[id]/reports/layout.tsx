"use client";

import type { ReactNode } from "react";
import { useBusiness } from "@/components/app/business-context";
import { SubNav } from "@/components/app/shell/sub-nav";
import { PageHeader } from "@/components/ui/page-header";
import { sectionHref } from "@/lib/routes";

/** Reports, with scheduled delivery as a sub-page (D10). */
export default function ReportsLayout({ children }: { children: ReactNode }) {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="گزارش‌ها" description="شاخص‌های هر قابلیت در بازهٔ دلخواه، و ارسال خودکار خلاصه در تلگرام." />
      <SubNav
        label="بخش‌های گزارش‌ها"
        items={[
          { href: sectionHref(bot.id, "reports"), label: "گزارش‌ها" },
          { href: sectionHref(bot.id, "schedules"), label: "ارسال زمان‌بندی‌شده" },
        ]}
      />
      {children}
    </>
  );
}
