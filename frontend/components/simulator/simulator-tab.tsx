import { TabPlaceholder } from "@/components/app/tab-placeholder";
import type { Bot } from "@/lib/types";

// Placeholder: the simulator tab is built in a later work package.
export function SimulatorTab({ bot }: { bot: Bot }) {
  void bot;
  return (
    <TabPlaceholder title="شبیه‌ساز">
      اینجا می‌توانید ربات را مثل یک کاربر تلگرام و با چند شخصیت آزمایشی امتحان کنید. این بخش به‌زودی اضافه می‌شود.
    </TabPlaceholder>
  );
}
