"use client";

import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface FilterTabOption {
  /** null is the «همه» entry. */
  key: string | null;
  label: string;
  count?: number;
}

/**
 * A strip of filters over one list (status, upcoming or past ...). Buttons with aria-pressed rather than
 * ARIA tabs: it narrows the list below it, it does not switch panels. Scrolls sideways inside the strip only.
 */
export function FilterTabs({
  options,
  value,
  onChange,
  label,
  className,
}: {
  options: FilterTabOption[];
  value: string | null;
  onChange: (key: string | null) => void;
  label: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={cn("flex max-w-full items-center gap-1 overflow-x-auto border-b border-border", className)}>
      {options.map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key ?? "__all"}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.key)}
            className={cn(
              "-mb-px inline-flex min-h-10 shrink-0 items-center gap-1.5 border-b-2 px-3 text-small font-medium whitespace-nowrap transition-colors duration-fast outline-none",
              active ? "border-brand text-fg" : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {o.label}
            {o.count !== undefined && (
              <span
                className={cn(
                  "min-w-5 rounded-xs px-1 text-center text-caption tabular-nums",
                  active ? "bg-brand-soft text-brand-text" : "bg-surface-sunken text-fg-muted",
                )}
              >
                {fa(o.count)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
