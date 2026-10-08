import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircleIcon } from "lucide-react";
import { Slot } from "radix-ui";
import { cn } from "@/lib/utils";

const PRIMARY = "bg-brand text-on-brand hover:bg-brand-hover";
const SECONDARY = "border border-border-strong bg-surface text-fg hover:bg-surface-sunken";
const DANGER = "bg-danger text-on-brand hover:bg-danger/90";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-sm text-body leading-snug font-medium whitespace-nowrap transition-colors duration-fast outline-none disabled:pointer-events-none disabled:opacity-50 aria-busy:pointer-events-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary: PRIMARY,
        secondary: SECONDARY,
        ghost: "text-fg-secondary hover:bg-surface-sunken hover:text-fg",
        danger: DANGER,
        link: "h-auto rounded-xs px-0 text-brand-text underline-offset-4 hover:underline",
        // Legacy names, kept so existing call sites compile: default = primary, outline = secondary, destructive = danger.
        default: PRIMARY,
        outline: SECONDARY,
        destructive: DANGER,
      },
      size: {
        sm: "h-8 gap-1.5 px-3 text-small",
        md: "h-10 px-4 sm:h-9",
        lg: "h-11 px-6",
        icon: "size-10 sm:size-9",
        default: "h-10 px-4 sm:h-9",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    /** Shows a spinner, sets aria-busy and disables the button until it flips back. */
    loading?: boolean;
  };

function Button({ className, variant, size, asChild = false, loading = false, disabled, children, ...props }: ButtonProps) {
  const classes = cn(buttonVariants({ variant, size }), variant === "link" && "p-0", className);
  if (asChild) {
    return (
      <Slot.Root data-slot="button" className={classes} {...props}>
        {children}
      </Slot.Root>
    );
  }
  return (
    <button
      data-slot="button"
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <LoaderCircleIcon className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export { Button, buttonVariants };
