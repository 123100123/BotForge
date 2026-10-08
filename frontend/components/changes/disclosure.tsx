"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface DisclosureProps {
  /** Heading text. */
  title: string;
  /** Short text at the end of the heading row (a count, a state). */
  meta?: ReactNode;
  defaultOpen?: boolean;
  /** Heading level of the title; keep the page's heading order intact. */
  as?: "h2" | "h3" | "h4";
  children: ReactNode;
  className?: string;
}

/** A collapsed-by-default section: the heading is the toggle. Pure UI state, no data. */
export function Disclosure({ title, meta, defaultOpen = false, as: Heading = "h3", children, className }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={className}>
      <Heading className={cn(Heading === "h3" ? "text-h3" : "text-small font-semibold", "text-fg")}>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((o) => !o)}
          className="-mx-2 flex min-h-11 w-[calc(100%+1rem)] items-center gap-2 rounded-sm px-2 text-start transition-colors duration-fast hover:bg-surface-sunken"
        >
          <span className="flex-1">{title}</span>
          {meta && <span className="text-small font-normal text-fg-muted">{meta}</span>}
          <ChevronDown
            strokeWidth={1.75}
            aria-hidden
            className={cn("size-4 shrink-0 text-fg-muted transition-transform duration-fast", open && "rotate-180")}
          />
        </button>
      </Heading>
      <div id={id} hidden={!open} className="pt-2">
        {open && children}
      </div>
    </div>
  );
}
