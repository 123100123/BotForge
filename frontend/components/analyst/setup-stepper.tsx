import { CheckIcon } from "lucide-react";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";

export const SETUP_STEPS = ["فایل", "ساختار", "پروفایل تحلیل", "گزارش"] as const;

/**
 * The four steps of the first analysis, in the order they really happen: file, structure, analysis profile,
 * report. Steps before the current one are done (check mark), the current one is highlighted; the state is
 * also in words for screen readers, never colour alone.
 */
export function SetupStepper({ current }: { current: 1 | 2 | 3 | 4 }) {
  return (
    <ol aria-label="مراحل راه‌اندازی تحلیل فایل" className="grid grid-cols-4">
      {SETUP_STEPS.map((label, i) => {
        const n = i + 1;
        const done = n < current;
        const active = n === current;
        return (
          <li
            key={label}
            aria-current={active ? "step" : undefined}
            className={cn(
              "relative flex flex-col items-center gap-1.5 text-center",
              // The connector runs from this step's circle toward the next one (toward the end edge).
              n < SETUP_STEPS.length && "after:absolute after:start-1/2 after:top-3.5 after:h-px after:w-full",
              n < SETUP_STEPS.length && (done ? "after:bg-brand" : "after:bg-border-strong"),
            )}
          >
            <span
              className={cn(
                "relative z-10 flex size-7 items-center justify-center rounded-full text-caption font-semibold",
                done && "bg-brand text-on-brand",
                active && "border-2 border-brand bg-brand-soft text-brand-text",
                !done && !active && "border border-border-strong bg-page text-fg-muted",
              )}
            >
              {done ? <CheckIcon aria-hidden className="size-4" strokeWidth={2} /> : fa(n)}
            </span>
            <span className={cn("text-small", active ? "font-semibold text-fg" : done ? "text-fg-secondary" : "text-fg-muted")}>
              {label}
              <span className="sr-only">{done ? " (انجام شد)" : active ? " (مرحلهٔ فعلی)" : ""}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
