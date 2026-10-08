"use client";

import { useBusiness } from "@/components/app/business-context";
import { ReportsTab } from "@/components/reports/reports-tab";

/** /reports: redirects to the first report that can be shown. */
export default function ReportsPage() {
  const { bot } = useBusiness();
  return <ReportsTab bot={bot} capabilityKey={null} />;
}
