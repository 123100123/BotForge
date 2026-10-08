"use client";

import type { ReactNode } from "react";
import { useBusiness } from "@/components/app/business-context";
import { SubNav } from "@/components/app/shell/sub-nav";
import { PageHeader } from "@/components/ui/page-header";
import { sectionHref } from "@/lib/routes";

/** Settings holds only configuration (D10): Telegram, Team, Groups, Account. */
export default function SettingsLayout({ children }: { children: ReactNode }) {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="تنظیمات" />
      <SubNav
        label="بخش‌های تنظیمات"
        items={[
          { href: sectionHref(bot.id, "telegram"), label: "تلگرام" },
          { href: sectionHref(bot.id, "team"), label: "تیم" },
          { href: sectionHref(bot.id, "groups"), label: "گروه‌ها" },
          { href: sectionHref(bot.id, "account"), label: "حساب" },
        ]}
      />
      <div className="flex w-full max-w-3xl flex-col gap-5">{children}</div>
    </>
  );
}
