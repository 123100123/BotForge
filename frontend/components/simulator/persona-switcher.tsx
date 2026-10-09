"use client";

import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Persona } from "@/lib/types";
import { PERSONAS, type Unread } from "./chat";

interface PersonaSwitcherProps {
  value: Persona;
  unread: Unread;
  onChange: (persona: Persona) => void;
}

/** Who the owner is playing. A badge counts messages that arrived for a persona that is not selected. */
export function PersonaSwitcher({ value, unread, onChange }: PersonaSwitcherProps) {
  return (
    <div role="group" aria-label="کاربر آزمایشی" className="grid grid-cols-2 gap-1.5 rounded-2xl bg-surface-secondary/70 p-1.5 sm:grid-cols-5 xl:grid-cols-2 2xl:grid-cols-3">
      {PERSONAS.map((p) => {
        const active = p.id === value;
        const count = unread[p.id];
        return (
          <button
            key={p.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(p.id)}
            className={cn(
              "relative min-h-10 rounded-xl px-2 py-2 text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
              active ? "bg-card font-semibold text-primary shadow-sm" : "text-muted-foreground hover:bg-card/60 hover:text-foreground",
            )}
          >
            {p.label}
            {count > 0 && (
              <span
                aria-label={`${fa(count)} پیام خوانده‌نشده`}
                className="absolute -top-1.5 -end-1 grid min-w-5 place-items-center rounded-full bg-destructive px-1 text-[11px] leading-5 font-medium text-white"
              >
                {fa(count)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
