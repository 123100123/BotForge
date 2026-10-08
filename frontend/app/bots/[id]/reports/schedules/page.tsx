"use client";

import { useBusiness } from "@/components/app/business-context";
import { SchedulesSection } from "@/components/settings/schedules-section";

export default function SchedulesPage() {
  const { bot } = useBusiness();
  return (
    <div className="max-w-3xl">
      <SchedulesSection botId={bot.id} />
    </div>
  );
}
