import * as React from "react";
import { cn } from "@/lib/utils";

/** Shared field chrome: input, textarea and select look identical. Invalid state comes from aria-invalid. */
export const FIELD_CLASS =
  "w-full min-w-0 rounded-sm border border-border-strong bg-surface-raised px-3 text-body text-fg transition-colors duration-fast placeholder:text-fg-muted focus-visible:border-brand disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger aria-invalid:focus-visible:outline-danger";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return <input type={type} data-slot="input" className={cn(FIELD_CLASS, "flex h-10 py-1 sm:h-9", className)} {...props} />;
}

export { Input };
