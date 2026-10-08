"use client";

import { useBusiness } from "@/components/app/business-context";
import { TeamSection } from "@/components/settings/team-section";

export default function TeamSettingsPage() {
  const { bot } = useBusiness();
  return <TeamSection botId={bot.id} />;
}
