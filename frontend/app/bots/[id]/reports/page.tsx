"use client";

import { useBusiness } from "@/components/app/business-context";
import { ReportsTab } from "@/components/reports/reports-tab";

export default function ReportsPage() {
  const { bot } = useBusiness();
  return <ReportsTab bot={bot} />;
}
