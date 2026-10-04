import { TabPlaceholder } from "@/components/app/tab-placeholder";
import type { Bot } from "@/lib/types";

// Placeholder: the data tab is built in a later work package.
export function DataTab({ bot }: { bot: Bot }) {
  void bot;
  return (
    <TabPlaceholder title="داده‌ها">
      اینجا آیتم‌های ربات (مثل کارگاه‌ها) را اضافه و ویرایش می‌کنید و ثبت‌نام‌ها را می‌بینید. این بخش به‌زودی اضافه می‌شود.
    </TabPlaceholder>
  );
}
