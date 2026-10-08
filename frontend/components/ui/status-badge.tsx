import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const statusBadgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1.5 rounded-xs px-2 py-0.5 text-caption whitespace-nowrap [&>svg]:size-3.5 [&>svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "bg-surface-sunken text-fg-secondary",
        brand: "bg-brand-soft text-brand-text",
        success: "bg-success-soft text-success-text",
        warning: "bg-warning-soft text-warning-text",
        danger: "bg-danger-soft text-danger-text",
        info: "bg-info-soft text-info-text",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

type StatusBadgeProps = React.ComponentProps<"span"> &
  VariantProps<typeof statusBadgeVariants> & {
    /** Leading icon (pass a lucide icon element, 14px is applied). */
    icon?: React.ReactNode;
    /** A 7px square marker in the tone color, for places where an icon is too heavy. Ignored when `icon` is set. */
    marker?: boolean;
  };

/**
 * Status chip: soft tone background, tone text, 6px radius (never a pill). Status is never color alone:
 * the label is the word, and `icon` or `marker` adds a shape.
 */
function StatusBadge({ className, tone, icon, marker, children, ...props }: StatusBadgeProps) {
  return (
    <span data-slot="status-badge" data-tone={tone ?? "neutral"} className={cn(statusBadgeVariants({ tone }), className)} {...props}>
      {icon}
      {!icon && marker && <span aria-hidden className="size-[7px] shrink-0 rounded-[2px] bg-current" />}
      {children}
    </span>
  );
}

export { StatusBadge, statusBadgeVariants };
