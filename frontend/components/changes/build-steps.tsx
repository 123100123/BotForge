import { Check } from "lucide-react";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";

export const BUILD_STEPS = ["توضیح کسب‌وکار", "برداشت دستیار", "پرسش‌ها", "آزمون‌ها", "فعال‌سازی"] as const;

interface BuildStepsProps {
  /** Index of the current step; `steps.length` means every step is done. */
  current: number;
  steps?: readonly string[];
  className?: string;
}

/** A true step indicator for building a business: done steps checked, the current one highlighted. Pure. */
export function BuildSteps({ current, steps = BUILD_STEPS, className }: BuildStepsProps) {
  const allDone = current >= steps.length;
  return (
    <nav aria-label="مراحل ساخت ربات" className={className}>
      <ol className="flex items-start">
        {steps.map((label, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li
              key={label}
              aria-current={active ? "step" : undefined}
              className="relative flex min-w-0 flex-1 flex-col items-center gap-1.5 text-center"
            >
              {i > 0 && (
                <span
                  aria-hidden
                  className={cn("absolute end-1/2 top-[15px] h-px w-full", i <= current ? "bg-brand" : "bg-border-strong")}
                />
              )}
              <span
                className={cn(
                  "relative z-10 flex size-[30px] items-center justify-center rounded-full border text-small font-semibold",
                  done && "border-brand bg-brand text-on-brand",
                  active && "border-brand bg-brand-soft text-brand-text ring-2 ring-brand/30",
                  !done && !active && "border-border-strong bg-surface text-fg-muted",
                )}
              >
                {done ? <Check strokeWidth={2} className="size-4" aria-label="انجام شد" /> : fa(i + 1)}
              </span>
              <span
                className={cn(
                  "px-1 text-caption leading-snug",
                  active ? "font-semibold text-fg" : done ? "text-fg-secondary" : "text-fg-muted",
                  !active && "max-sm:sr-only",
                )}
              >
                {label}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-center text-caption text-fg-muted sm:sr-only">
        {allDone ? "همهٔ مرحله‌ها انجام شد" : `مرحلهٔ ${fa(current + 1)} از ${fa(steps.length)}`}
      </p>
    </nav>
  );
}
