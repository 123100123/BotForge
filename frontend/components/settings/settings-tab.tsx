import { TabPlaceholder } from "@/components/app/tab-placeholder";
import type { Bot } from "@/lib/types";

// Placeholder: the settings tab is built in a later work package.
export function SettingsTab({ bot }: { bot: Bot }) {
  void bot;
  return (
    <TabPlaceholder title="تنظیمات">
      اینجا توکن ربات تلگرام را وصل می‌کنید و پیوند دریافت هشدارهای مدیر را می‌گیرید. این بخش به‌زودی اضافه می‌شود.
    </TabPlaceholder>
  );
}
