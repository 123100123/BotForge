"use client";

import type { ReactNode } from "react";
import { useBusiness } from "@/components/app/business-context";
import { PageHeader } from "@/components/ui/page-header";

/** Changes: proposals and versions of the business; for a business with no active version, the first build. */
export default function ChangesLayout({ children }: { children: ReactNode }) {
  const { bot } = useBusiness();
  const firstBuild = !bot.active_revision_id;
  return (
    <>
      <PageHeader
        title={firstBuild ? "ساخت ربات" : "تغییرات"}
        description={
          firstBuild
            ? "کسب‌وکارتان را برای دستیار توضیح دهید تا ربات تلگرامش را بسازد و آزمایش کند. چیزی بدون تأیید شما فعال نمی‌شود."
            : "ربات را با یک جمله تغییر دهید؛ دستیار یک پیشنهاد می‌سازد و هیچ تغییری بدون تأیید شما فعال نمی‌شود."
        }
      />
      {children}
    </>
  );
}
