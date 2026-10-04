import { TabPlaceholder } from "@/components/app/tab-placeholder";
import type { Bot } from "@/lib/types";

// Placeholder: the versions tab is built in a later work package.
export function VersionsTab({ bot }: { bot: Bot }) {
  void bot;
  return (
    <TabPlaceholder title="نسخه‌ها">
      اینجا تاریخچهٔ نسخه‌های ربات و تفاوت آن‌ها را می‌بینید و در صورت نیاز به نسخهٔ قبلی برمی‌گردید. این بخش به‌زودی اضافه می‌شود.
    </TabPlaceholder>
  );
}
