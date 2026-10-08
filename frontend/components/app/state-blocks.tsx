import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Inline error line for a failed request. */
export function ErrorNote({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p role="alert" className={cn("rounded-sm bg-danger-soft p-3 text-small text-danger-text", className)}>
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
        "rounded-sm p-3 text-small",
        tone === "success" ? "bg-success-soft text-success-text" : "bg-warning-soft text-warning-text",
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
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-40 rounded-md" />
    </div>
  );
}

/** Centered message card with an optional action. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
        <h3 className="text-h3">{title}</h3>
        {children && <p className="max-w-md text-sm leading-7 text-muted-foreground">{children}</p>}
        {action}
      </CardContent>
    </Card>
  );
}
