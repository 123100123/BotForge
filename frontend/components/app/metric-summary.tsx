import { Card, CardContent } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import type { MetricValue } from "@/lib/types";

/** Placeholder rendering of one metric (scalar value, or a short list for series and breakdowns). Wave 1 replaces it with charts. */
export function MetricSummary({ metric }: { metric: MetricValue }) {
  return (
    <Card className="gap-2 py-4">
      <CardContent className="flex flex-col gap-1.5">
        <span className="text-xs text-muted-foreground">{metric.label}</span>
        {metric.kind === "scalar" ? (
          <span className="text-2xl font-bold">
            {metric.value === null ? "-" : formatNumber(metric.value)}
            {metric.unit && <span className="ms-1 text-xs font-normal text-muted-foreground">{metric.unit}</span>}
          </span>
        ) : (
          <ul className="flex flex-col gap-0.5 text-sm">
            {(metric.series ?? []).map((p) => (
              <li key={p.label} className="flex justify-between gap-3">
                <span className="text-muted-foreground">{p.label}</span>
                <span>{formatNumber(p.value)}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
