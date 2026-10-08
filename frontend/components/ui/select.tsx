import * as React from "react";
import { cn } from "@/lib/utils";
import { FIELD_CLASS } from "@/components/ui/input";

/** Native select styled like Input; native keeps keyboard and mobile behavior for free. */
function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <select data-slot="select" className={cn(FIELD_CLASS, "flex h-10 py-1 sm:h-9", className)} {...props}>
      {children}
    </select>
  );
}

export { Select };
