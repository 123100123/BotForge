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

/** Who the owner is playing (segmented control). A counter marks messages that arrived for a persona that is not selected. */
export function PersonaSwitcher({ value, unread, onChange }: PersonaSwitcherProps) {
  return (
    <div role="radiogroup" aria-label="کاربر آزمایشی" className="grid grid-cols-5 gap-0.5 rounded-sm border border-border bg-surface-sunken p-0.5">
      {PERSONAS.map((p) => {
        const active = p.id === value;
        const count = unread[p.id];
        return (
          <button
            key={p.id}
            role="radio"
            type="button"
            aria-checked={active}
            onClick={() => onChange(p.id)}
            className={cn(
              "relative min-h-9 rounded-xs border px-1 py-1 text-small font-medium transition-colors duration-fast",
              active ? "border-border bg-surface text-fg" : "border-transparent text-fg-muted hover:text-fg",
            )}
          >
            {p.label}
            {count > 0 && (
              <span
                aria-label={`${fa(count)} پیام خوانده‌نشده`}
                className="absolute -top-2 -end-1 grid min-w-5 place-items-center rounded-xs bg-danger px-1 text-caption leading-5 font-medium text-on-brand"
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
