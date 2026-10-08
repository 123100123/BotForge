import { ClockIcon } from "lucide-react";
import { ApiError } from "@/lib/errors";
import { fa } from "@/lib/format";
import { DAILY_CAP_CODE } from "./labels";

/** True when the error is the per-account daily limit on assistant calls. */
export function isDailyCap(err: unknown): boolean {
  return err instanceof ApiError && err.code === DAILY_CAP_CODE;
}

/** The daily limit reached, in plain words: what stopped, what still works, when to come back. */
export function AssistantLimit() {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-sm bg-warning-soft p-4 text-warning-text">
      <ClockIcon aria-hidden className="mt-1 size-5 shrink-0" strokeWidth={1.75} />
      <div className="flex flex-col gap-1 text-small">
        <p className="font-semibold">سهمیهٔ امروز دستیار تمام شده است</p>
        <p>
          دستیار در هر ۲۴ ساعت برای هر حساب حداکثر {fa(30)} بار برای ساخت پروفایل و نوشتن خلاصه استفاده می‌شود و این سهمیه پر شده است. پروفایل‌ها و گزارش‌های قبلی
          همچنان کار می‌کنند؛ فردا دوباره تلاش کنید.
        </p>
      </div>
    </div>
  );
}
