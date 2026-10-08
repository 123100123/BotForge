import { Card, CardContent } from "@/components/ui/card";
import { fa, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface Delta {
  direction: "up" | "down" | "flat";
  /** Persian text such as "۱۲٪" (or "جدید" when the previous value was zero). */
  text: string;
}

/** Change of `value` against `previous`; null when there is nothing to compare with. */
export function computeDelta(value: number | null, previous: number | null): Delta | null {
  if (value === null || previous === null) return null;
  if (previous === 0) return value === 0 ? { direction: "flat", text: "بدون تغییر" } : { direction: "up", text: "جدید" };
  const pct = Math.round(((value - previous) / Math.abs(previous)) * 100);
  if (pct === 0) return { direction: "flat", text: "بدون تغییر" };
  return { direction: pct > 0 ? "up" : "down", text: `${fa(Math.abs(pct))}٪` };
}

/** One number with its label, unit and (when `previous` is known) the change against the previous period. */
export function StatTile({
  label,
  value,
  unit,
  previous = null,
  className,
}: {
  label: string;
  value: number | null;
  unit?: string | null;
  previous?: number | null;
  className?: string;
}) {
  const delta = computeDelta(value, previous);
  return (
    <Card className={cn("min-w-0 gap-4 rounded-2xl border border-border py-5", className)}>
      <CardContent className="flex flex-col gap-2">
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
        <span className="flex min-w-0 flex-wrap items-baseline gap-1 text-3xl leading-tight font-extrabold tabular-nums tracking-tight">
          <span className="min-w-0 [overflow-wrap:anywhere]">{value === null ? "-" : formatNumber(value)}</span>
          {unit && <span className="ms-1 text-xs font-normal text-muted-foreground">{unit}</span>}
        </span>
        {delta && (
          <span
            className={cn(
              "inline-flex flex-wrap items-center gap-1 text-xs",
              delta.direction === "up" && "text-success",
              delta.direction === "down" && "text-destructive",
              delta.direction === "flat" && "text-muted-foreground",
            )}
          >
            {delta.direction !== "flat" && <span aria-hidden>{delta.direction === "up" ? "▲" : "▼"}</span>}
            <span>
              {delta.direction === "up" && <span className="sr-only">افزایش </span>}
              {delta.direction === "down" && <span className="sr-only">کاهش </span>}
              {delta.text}
            </span>
            <span className="text-muted-foreground">نسبت به دورهٔ قبل</span>
          </span>
        )}
      </CardContent>
    </Card>
  );
}
