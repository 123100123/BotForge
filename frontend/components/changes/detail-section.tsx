import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A titled block inside a detail panel, separated from its neighbours by a divider (no card in a card). */
export function DetailSection({
  title,
  action,
  children,
  className,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-3 border-t border-border px-5 py-5", className)}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-h3 text-fg">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}
