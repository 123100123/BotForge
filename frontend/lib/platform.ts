import type { BotPlatform } from "@/lib/types";

/** Mirrors backend/app/integrations/telegram/platforms.py: names, deep-link hosts and setup steps. */
export const PLATFORMS: readonly BotPlatform[] = ["telegram", "bale"];

/** How the Persian UI names each messenger. */
export function platformName(platform: BotPlatform): string {
  return platform === "bale" ? "بله" : "تلگرام";
}

/** The public link host of a bot: t.me for Telegram, ble.ir for Bale. */
export function platformLinkBase(platform: BotPlatform): string {
  return platform === "bale" ? "https://ble.ir" : "https://t.me";
}
