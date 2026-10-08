"use client";

import { useBusiness } from "@/components/app/business-context";
import { GroupsSection } from "@/components/settings/groups-section";

export default function GroupsSettingsPage() {
  const { bot } = useBusiness();
  return <GroupsSection botId={bot.id} />;
}
