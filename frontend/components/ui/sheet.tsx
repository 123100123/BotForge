"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { XIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { CLOSE_CLASS, OVERLAY_CLASS } from "@/components/ui/dialog";

const SIDES = {
  // start = the reading-start edge: right in RTL. end = left in RTL.
  start:
    "inset-y-0 start-0 h-dvh w-[min(100%-2rem,26rem)] rounded-e-lg border-e data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left rtl:data-[state=open]:slide-in-from-right rtl:data-[state=closed]:slide-out-to-right",
  end: "inset-y-0 end-0 h-dvh w-[min(100%-2rem,26rem)] rounded-s-lg border-s data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right rtl:data-[state=open]:slide-in-from-left rtl:data-[state=closed]:slide-out-to-left",
  bottom:
    "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-lg border-t data-[state=open]:slide-in-from-bottom data-[state=closed]:slide-out-to-bottom",
} as const;

function Sheet(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="sheet" {...props} />;
}

function SheetTrigger(props: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="sheet-trigger" {...props} />;
}

function SheetClose(props: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="sheet-close" {...props} />;
}

/** Edge-anchored dialog (focus trapped, Esc closes). `side`: start | end | bottom; start is the right edge in RTL. */
function SheetContent({
  className,
  children,
  side = "end",
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: keyof typeof SIDES }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay data-slot="sheet-overlay" className={OVERLAY_CLASS} />
      <DialogPrimitive.Content
        data-slot="sheet-content"
        data-side={side}
        className={cn(
          "fixed z-modal flex flex-col gap-4 overflow-y-auto border-float bg-surface-raised p-6 text-fg shadow-float outline-none",
          "data-[state=closed]:animate-out data-[state=open]:animate-in motion-safe:data-[state=closed]:duration-base motion-safe:data-[state=open]:duration-slow",
          SIDES[side],
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className={CLOSE_CLASS} aria-label="بستن">
          <XIcon className="size-4" strokeWidth={1.75} />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sheet-header" className={cn("flex flex-col gap-1.5 pe-8 text-start", className)} {...props} />;
}

function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sheet-footer" className={cn("mt-auto flex flex-row-reverse justify-start gap-2", className)} {...props} />;
}

function SheetTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title data-slot="sheet-title" className={cn("text-h2 text-fg", className)} {...props} />;
}

function SheetDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description data-slot="sheet-description" className={cn("text-small text-fg-muted", className)} {...props} />;
}

export { Sheet, SheetTrigger, SheetClose, SheetContent, SheetHeader, SheetFooter, SheetTitle, SheetDescription };
