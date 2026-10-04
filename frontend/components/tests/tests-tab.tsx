import { TabPlaceholder } from "@/components/app/tab-placeholder";
import type { Bot } from "@/lib/types";

// Placeholder: the tests tab is built in a later work package.
export function TestsTab({ bot }: { bot: Bot }) {
  void bot;
  return (
    <TabPlaceholder title="تست‌ها">
      اینجا فهرست آزمون‌ها و روایت فارسی هر مرحله را می‌بینید. این بخش به‌زودی اضافه می‌شود.
    </TabPlaceholder>
  );
}
