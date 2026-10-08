"use client";

import type { ReactNode } from "react";
import { useBusiness } from "@/components/app/business-context";
import { SubNav } from "@/components/app/shell/sub-nav";
import { PageHeader } from "@/components/ui/page-header";
import { sectionHref } from "@/lib/routes";

/** Changes: the current proposal (build or change flow) and the history of versions with their tests. */
export default function ChangesLayout({ children }: { children: ReactNode }) {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader
        title="تغییرات"
        description="ربات را با دستیار بسازید یا تغییر دهید؛ هیچ تغییری بدون تأیید شما فعال نمی‌شود."
      />
      <SubNav
        label="بخش‌های تغییرات"
        items={[
          { href: sectionHref(bot.id, "changes"), label: "پیشنهاد تغییر" },
          { href: sectionHref(bot.id, "versions"), label: "نسخه‌ها و آزمون‌ها" },
        ]}
      />
      {children}
    </>
  );
}
