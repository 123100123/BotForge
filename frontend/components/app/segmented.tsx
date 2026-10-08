"use client";

import { useRef } from "react";
import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

/**
 * Compact single-choice control for filters and modes that change what a region shows (a radiogroup, not
 * ARIA tabs: there are no tab panels). One tab stop; arrow keys move and select, as a native radio group does.
 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  label: string;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selected = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );

  function onKeyDown(e: React.KeyboardEvent, index: number) {
    const rtl = getComputedStyle(e.currentTarget).direction === "rtl";
    let step = 0;
    if (e.key === "ArrowDown") step = 1;
    else if (e.key === "ArrowUp") step = -1;
    else if (e.key === "ArrowRight") step = rtl ? -1 : 1;
    else if (e.key === "ArrowLeft") step = rtl ? 1 : -1;
    else return;
    e.preventDefault();
    const next = (index + step + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn("inline-flex w-fit max-w-full items-center gap-0.5 overflow-x-auto rounded-sm border bg-surface-sunken p-0.5", className)}
    >
      {options.map((o, i) => {
        const active = i === selected;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              "shrink-0 rounded-xs border px-3 py-1 text-small font-medium whitespace-nowrap transition-colors duration-fast",
              active ? "border-border bg-surface text-fg" : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
