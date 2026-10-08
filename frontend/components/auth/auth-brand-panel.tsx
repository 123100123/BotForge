import { CheckIcon } from "lucide-react";
import { ChangeStateBadge } from "@/components/changes/change-state";
import { ConfigDiff } from "@/components/changes/config-diff";
import type { SpecChange } from "@/lib/types";

const DIFF: SpecChange[] = [
  {
    path: ["capabilities", "book_workshop", "capacity", "value"],
    kind: "changed",
    old: 10,
    new: 12,
    label_fa: "ظرفیت هر کارگاه: ۱۰ نفر ← ۱۲ نفر",
  },
];

const PROMISES = [
  "هیچ تغییری بدون تأیید شما فعال نمی‌شود.",
  "هر تغییر یک نسخه است و می‌توانید به نسخهٔ قبل برگردید.",
  "کارهای روزمرهٔ ربات بدون هوش مصنوعی و قابل‌پیش‌بینی اجرا می‌شوند.",
];

/** End-edge panel of the auth pages: one activated change proposal (real components) and three promises. */
export function AuthBrandPanel() {
  return (
    <div className="flex w-full max-w-md flex-col gap-10">
      <div className="overflow-hidden rounded-md border border-border-strong bg-surface" aria-label="نمونهٔ یک تغییر فعال‌شده" role="group">
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
          <span className="text-small font-medium text-fg-secondary">پیشنهاد تغییر</span>
          <ChangeStateBadge state="active" />
        </div>
        <div className="flex flex-col gap-4 p-5">
          <p className="text-body text-fg">ظرفیت هر کارگاه را ۱۲ نفر کن.</p>
          <ConfigDiff changes={DIFF} />
          <p className="text-small text-fg-secondary">ربات تلگرام از همین حالا مطابق آن رفتار می‌کند.</p>
        </div>
      </div>
      <ul className="flex flex-col gap-3">
        {PROMISES.map((p) => (
          <li key={p} className="flex items-start gap-3 text-body text-fg">
            <CheckIcon className="mt-2 size-4 shrink-0 text-brand-text" strokeWidth={1.75} aria-hidden />
            {p}
          </li>
        ))}
      </ul>
    </div>
  );
}
