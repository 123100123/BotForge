"use client";

import { useState } from "react";
import { AnalystTab } from "@/components/analyst/analyst-tab";
import { Segmented } from "@/components/app/segmented";
import { ReportsTab } from "@/components/reports/reports-tab";
import type { Bot } from "@/lib/types";

type ReportsView = "reports" | "analyst";

/** The Reports section: business reports, with the Data Analyst as a sub-section. */
export function ReportsSection({ bot }: { bot: Bot }) {
  const [view, setView] = useState<ReportsView>("reports");

  return (
    <div className="flex flex-col gap-4">
      <Segmented<ReportsView>
        label="بخش گزارش‌ها"
        value={view}
        onChange={setView}
        options={[
          { value: "reports", label: "گزارش‌های کسب‌وکار" },
          { value: "analyst", label: "تحلیلگر داده" },
        ]}
      />
      {view === "reports" ? <ReportsTab bot={bot} /> : <AnalystTab bot={bot} />}
    </div>
  );
}
