"use client";

import * as React from "react";
import { Switch as SwitchPrimitive } from "radix-ui";
import { cn } from "@/lib/utils";

function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent bg-border-strong transition-colors duration-fast outline-none disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-brand",
        className,
      )}
      {...props}
    >
      {/* Thumb starts at the start edge and moves toward the end edge when on (left in RTL). */}
      <SwitchPrimitive.Thumb className="pointer-events-none ms-0.5 block size-4 rounded-full bg-surface shadow-sm transition-transform data-[state=checked]:bg-on-brand duration-fast data-[state=checked]:translate-x-3.5 rtl:data-[state=checked]:-translate-x-3.5" />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
