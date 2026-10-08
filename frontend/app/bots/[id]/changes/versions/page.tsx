"use client";

import { useBusiness } from "@/components/app/business-context";
import { VersionsTab } from "@/components/versions/versions-tab";

export default function VersionsPage() {
  const { bot, reload } = useBusiness();
  return <VersionsTab bot={bot} onBotChanged={reload} />;
}
