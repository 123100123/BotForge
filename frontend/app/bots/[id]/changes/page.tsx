"use client";

import { AgentTab } from "@/components/agent/agent-tab";
import { useBusiness } from "@/components/app/business-context";

export default function ChangesPage() {
  const { bot } = useBusiness();
  return <AgentTab bot={bot} />;
}
