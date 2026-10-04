import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Inline error line for a failed request. */
export function ErrorNote({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p role="alert" className={cn("rounded-md bg-destructive/10 p-3 text-sm leading-7 text-destructive", className)}>
      {children}
    </p>
  );
}

/** Inline result line (for example the message of a data action). */
export function InfoNote({
  children,
  tone = "success",
  className,
}: {
  children: ReactNode;
  tone?: "success" | "warning";
  className?: string;
}) {
  return (
    <p
      role="status"
      className={cn(
        "rounded-md p-3 text-sm leading-7",
        tone === "success" ? "bg-success/10 text-success" : "bg-warning/15 text-warning",
        className,
      )}
    >
      {children}
    </p>
  );
}

export function LoadingBlock({ className }: { className?: string }) {
  return (
    <div role="status" aria-label="در حال بارگذاری" className={cn("flex flex-col gap-3", className)}>
      <div className="h-8 w-48 animate-pulse rounded bg-muted" />
      <div className="h-40 animate-pulse rounded-xl bg-muted" />
    </div>
  );
}

/** Centered message card with an optional action. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
        <h3 className="text-base font-semibold">{title}</h3>
        {children && <p className="max-w-md text-sm leading-7 text-muted-foreground">{children}</p>}
        {action}
      </CardContent>
    </Card>
  );
}
