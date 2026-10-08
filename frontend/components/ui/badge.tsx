import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/** Generic label chip. For status (active, pending, failed ...) use StatusBadge, which has tones and markers. */
const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 rounded-xs border px-2 py-0.5 text-caption whitespace-nowrap [&>svg]:size-3.5 [&>svg]:pointer-events-none",
  {
    variants: {
      variant: {
        default: "border-transparent bg-brand text-on-brand",
        secondary: "border-transparent bg-surface-sunken text-fg-secondary",
        outline: "border-border bg-surface text-fg-secondary",
        accent: "border-transparent bg-brand-soft text-brand-text",
        success: "border-transparent bg-success-soft text-success-text",
        warning: "border-transparent bg-warning-soft text-warning-text",
        destructive: "border-transparent bg-danger-soft text-danger-text",
      },
    },
    defaultVariants: { variant: "secondary" },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
