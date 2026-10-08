import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Nothing here yet: icon, what it is, why, and the one next action. Pass `icon` as an element
 * (<InboxIcon />); it is drawn at 20px in a sunken tile.
 */
function EmptyState({
  icon,
  title,
  description,
  action,
  as: Heading = "h3",
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  /** Heading level of the title; keep the page's heading order intact. */
  as?: "h2" | "h3" | "h4" | "p";
  className?: string;
}) {
  return (
    <div data-slot="empty-state" className={cn("flex flex-col items-center gap-3 px-4 py-10 text-center", className)}>
      {icon && (
        <span
          aria-hidden
          className="flex size-11 items-center justify-center rounded-md bg-surface-sunken text-fg-muted [&_svg]:size-5"
        >
          {icon}
        </span>
      )}
      <div className="flex max-w-md flex-col gap-1">
        <Heading className="text-h3 text-fg">{title}</Heading>
        {description && <p className="text-small text-fg-muted">{description}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export { EmptyState };
