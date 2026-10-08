"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, FlaskConical, LoaderCircle, TriangleAlert, X } from "lucide-react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { Button } from "@/components/ui/button";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";

export type DecisionPhase = "pending" | "activating" | "activated" | "rejected";

interface DecisionBarProps {
  /** Number of the version this activates; null when the draft's number is not known yet. */
  revisionNumber: number | null;
  phase: DecisionPhase;
  /** The server refuses activation (for example failing tests); `blockedReason` says why. */
  canApprove?: boolean;
  blockedReason?: string | null;
  /** A request (approve or reject) is in flight. */
  busy?: boolean;
  onApprove: () => void;
  onReject: () => void | Promise<void>;
  /** Link to try the draft in the simulator; hidden when null. */
  simulatorHref?: string | null;
  className?: string;
}

/**
 * The decision of a change proposal: activate, reject (with a confirmation) or try it in the simulator
 * first. Sticky at the bottom of the proposal (above the mobile tab bar). Pure apart from the open state of
 * its own confirmation dialog.
 */
export function DecisionBar({
  revisionNumber,
  phase,
  canApprove = true,
  blockedReason,
  busy = false,
  onApprove,
  onReject,
  simulatorHref,
  className,
}: DecisionBarProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const label = revisionNumber !== null ? `فعال‌سازی نسخهٔ ${fa(revisionNumber)}` : "فعال‌سازی این نسخه";

  return (
    <div
      data-slot="decision-bar"
      className={cn(
        "sticky bottom-0 z-sticky flex flex-col gap-3 border-t border-border bg-surface px-5 py-3 max-sm:bottom-[calc(3.625rem+env(safe-area-inset-bottom))]",
        className,
      )}
    >
      {phase === "pending" && (
        <>
          {!canApprove && (
            <p role="alert" className="flex items-start gap-2 rounded-sm bg-danger-soft p-3 text-small text-danger-text">
              <TriangleAlert strokeWidth={1.75} aria-hidden className="mt-1 size-4 shrink-0" />
              <span>
                <span className="font-medium">فعال‌سازی ممکن نیست. </span>
                {blockedReason || "این نسخه فعلاً قابل فعال‌سازی نیست."}
              </span>
            </p>
          )}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Button onClick={onApprove} disabled={!canApprove} loading={busy} className="max-sm:flex-1">
              <Check strokeWidth={1.75} />
              {label}
            </Button>
            <Button variant="secondary" onClick={() => setConfirmOpen(true)} disabled={busy}>
              <X strokeWidth={1.75} />
              رد
            </Button>
            {simulatorHref && (
              <Button asChild variant="link" className="ms-auto max-sm:ms-0">
                <Link href={simulatorHref}>
                  <FlaskConical strokeWidth={1.75} />
                  امتحان در شبیه‌ساز
                </Link>
              </Button>
            )}
          </div>
          <p className="hidden text-caption text-fg-muted sm:block">
            تا وقتی فعال نکنید، ربات تلگرام همان‌طور که هست می‌ماند.
          </p>
        </>
      )}

      {phase === "activating" && (
        <p role="status" className="flex items-center gap-2 text-body text-fg-secondary">
          <LoaderCircle strokeWidth={1.75} aria-hidden className="size-5 shrink-0 animate-spin" />
          در حال فعال‌سازی {revisionNumber !== null ? `نسخهٔ ${fa(revisionNumber)}` : "نسخه"}…
        </p>
      )}

      {phase === "activated" && (
        <p role="status" className="flex items-center gap-2 text-body font-medium text-success-text">
          <Check strokeWidth={1.75} aria-hidden className="size-5 shrink-0" />
          {revisionNumber !== null ? `نسخهٔ ${fa(revisionNumber)} فعال شد` : "نسخه فعال شد"}
          <span className="text-small font-normal text-fg-secondary">ربات تلگرام از همین حالا مطابق آن رفتار می‌کند.</span>
        </p>
      )}

      {phase === "rejected" && (
        <p role="status" className="flex items-center gap-2 text-body text-fg-secondary">
          <X strokeWidth={1.75} aria-hidden className="size-5 shrink-0" />
          این پیشنهاد رد شد؛ ربات فعلی بدون تغییر ماند.
        </p>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="رد کردن این پیشنهاد؟"
        description="پیش‌نویس کنار گذاشته می‌شود و ربات فعلی بدون تغییر می‌ماند. اگر بخواهید، می‌توانید تغییر تازه‌ای درخواست کنید."
        confirmLabel="رد کردن پیشنهاد"
        destructive
        onConfirm={async () => {
          await onReject();
        }}
      />
    </div>
  );
}
