"use client";

import * as React from "react";
import { Toast as ToastPrimitive } from "radix-ui";
import { CircleAlertIcon, CircleCheckIcon, InfoIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast, type ToastTone } from "@/components/ui/use-toast";

const TONES: Record<ToastTone, { icon: React.ReactNode }> = {
  neutral: { icon: null },
  success: { icon: <CircleCheckIcon className="text-success-text" /> },
  warning: { icon: <TriangleAlertIcon className="text-warning-text" /> },
  danger: { icon: <CircleAlertIcon className="text-danger-text" /> },
  info: { icon: <InfoIcon className="text-info-text" /> },
};

/**
 * Mount once (app/layout.tsx). Toasts are announced politely (aria-live polite, type "background") and sit at
 * the end-bottom corner; call `toast({ title, description?, tone? })` from "@/components/ui/use-toast".
 */
function Toaster() {
  const { toasts, dismiss } = useToast();
  return (
    <ToastPrimitive.Provider swipeDirection="down" label="اعلان‌ها">
      {toasts.map((t) => (
        <ToastPrimitive.Root
          key={t.id}
          type="background"
          duration={t.duration}
          onOpenChange={(open) => {
            if (!open) dismiss(t.id);
          }}
          className={cn(
            "relative flex items-start gap-3 rounded-md border border-float bg-surface-raised p-4 pe-10 text-fg shadow-float data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-safe:data-[state=open]:slide-in-from-bottom-2 data-[state=open]:duration-base",
          )}
        >
          {TONES[t.tone].icon && <span aria-hidden className="mt-0.5 shrink-0 [&_svg]:size-5">{TONES[t.tone].icon}</span>}
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <ToastPrimitive.Title className="text-small font-semibold text-fg">{t.title}</ToastPrimitive.Title>
            {t.description && <ToastPrimitive.Description className="text-small text-fg-secondary">{t.description}</ToastPrimitive.Description>}
          </div>
          <ToastPrimitive.Close
            aria-label="بستن"
            className="absolute end-2 top-2 inline-flex size-7 items-center justify-center rounded-xs text-fg-muted transition-colors duration-fast hover:bg-surface-sunken hover:text-fg"
          >
            <XIcon className="size-4" strokeWidth={1.75} />
          </ToastPrimitive.Close>
        </ToastPrimitive.Root>
      ))}
      <ToastPrimitive.Viewport
        aria-live="polite"
        className="fixed inset-x-4 bottom-4 z-toast m-0 flex list-none flex-col gap-2 outline-none sm:inset-x-auto sm:end-4 sm:w-96"
      />
    </ToastPrimitive.Provider>
  );
}

export { Toaster };
