import * as React from "react";
import { cn } from "@/lib/utils";

/** Loading placeholder. Size it with className (h-4 w-32 ...); it is hidden from assistive tech. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="skeleton" aria-hidden className={cn("animate-skeleton rounded-sm bg-border", className)} {...props} />;
}

export { Skeleton };
