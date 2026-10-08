"use client";

import Link from "next/link";
import { CircleCheckIcon, XIcon } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { useCapabilities } from "@/components/capabilities/capabilities-provider";
import { sectionHref } from "@/lib/routes";

/** The result of the last toggle, kept on the page (a toast fades) with a link to Changes when a version was made. */
export function ToggleNoticeBar() {
  const { bot } = useBusiness();
  const { notice, dismissNotice } = useCapabilities();
  if (!notice) return null;
  return (
    <div role="status" className="flex items-start gap-2 rounded-sm bg-success-soft p-3 text-small text-success-text">
      <CircleCheckIcon className="mt-1 size-4 shrink-0" strokeWidth={1.75} aria-hidden />
      <p className="min-w-0 flex-1">
        {notice.text}
        {notice.revisionNumber !== null && (
          <>
            {" "}
            <Link href={sectionHref(bot.id, "changes")} className="font-semibold underline underline-offset-4">
              رفتن به تغییرات
            </Link>
          </>
        )}
      </p>
      <button
        type="button"
        onClick={dismissNotice}
        aria-label="بستن پیام"
        className="inline-flex size-6 shrink-0 items-center justify-center rounded-xs hover:bg-success/15"
      >
        <XIcon className="size-4" strokeWidth={1.75} aria-hidden />
      </button>
    </div>
  );
}
