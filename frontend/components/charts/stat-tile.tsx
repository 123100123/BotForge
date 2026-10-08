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
    <Card className={cn("gap-2 py-4", className)}>
      <CardContent className="flex flex-col gap-1.5">
        <span className="text-caption text-muted-foreground">{label}</span>
        <span className="text-2xl leading-tight font-bold">
          {value === null ? "-" : formatNumber(value)}
          {unit && <span className="ms-1 text-caption font-normal text-muted-foreground">{unit}</span>}
        </span>
        {delta && (
          <span
            className={cn(
              "inline-flex items-center gap-1 text-caption",
              delta.direction === "up" && "text-success-text",
              delta.direction === "down" && "text-danger-text",
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
