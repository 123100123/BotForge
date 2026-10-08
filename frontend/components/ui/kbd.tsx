import * as React from "react";
import { cn } from "@/lib/utils";

/** Keyboard key hint, e.g. <Kbd>Ctrl</Kbd> <Kbd>K</Kbd>. Always left-to-right so the key names are not reordered. */
function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      dir="ltr"
      data-slot="kbd"
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-border-strong bg-surface-sunken px-1 font-mono text-[12px] leading-none text-fg-secondary",
        className,
      )}
      {...props}
    />
  );
}

export { Kbd };
