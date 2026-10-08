import * as React from "react";
import { CircleAlertIcon, RefreshCwIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** A failed load: what happened in plain words, plus a retry. `message` should already be Persian user text. */
function ErrorState({
  message,
  title = "بارگذاری انجام نشد",
  onRetry,
  retryLabel = "تلاش دوباره",
  className,
}: {
  message?: string;
  title?: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <div role="alert" data-slot="error-state" className={cn("flex flex-col items-center gap-3 px-4 py-10 text-center", className)}>
      <span aria-hidden className="flex size-11 items-center justify-center rounded-md bg-danger-soft text-danger-text">
        <CircleAlertIcon className="size-5" strokeWidth={1.75} />
      </span>
      <div className="flex max-w-md flex-col gap-1">
        <p className="text-h3 text-fg">{title}</p>
        {message && <p className="text-small text-fg-muted">{message}</p>}
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RefreshCwIcon />
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

export { ErrorState };
