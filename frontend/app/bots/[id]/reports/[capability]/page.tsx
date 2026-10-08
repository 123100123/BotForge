"use client";

import { useParams } from "next/navigation";
import { useBusiness } from "@/components/app/business-context";
import { ReportsTab } from "@/components/reports/reports-tab";

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** One report on its own URL: /reports/[capability]?period=7d. */
export default function ReportPage() {
  const { capability } = useParams<{ capability: string }>();
  const { bot } = useBusiness();
  return <ReportsTab bot={bot} capabilityKey={safeDecode(capability)} />;
}
