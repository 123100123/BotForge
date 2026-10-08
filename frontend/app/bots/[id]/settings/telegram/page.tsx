"use client";

import { useBusiness } from "@/components/app/business-context";
import { TelegramSettings } from "@/components/settings/telegram-settings";

export default function TelegramSettingsPage() {
  const { bot, reloadBot } = useBusiness();
  return <TelegramSettings bot={bot} onBotChanged={reloadBot} />;
}
