import { CircleCheck, CircleX, FlaskConical } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fa } from "@/lib/format";
import type { TestReportPayload } from "@/lib/agent-state";
import type { EventPayloads, Scenario } from "@/lib/types";

/** The backend may send a count or the scenario list. */
export function countOf(value: number | Scenario[]): number {
  return typeof value === "number" ? value : value.length;
}

interface TestSummaryProps {
  generated: EventPayloads["tests_generated"] | null;
  /** Every report so far, oldest first. The last one is the current result. */
  reports: TestReportPayload[];
}

/** "N of N passed" for the latest run of the suite, with failures listed. */
export function TestSummary({ generated, reports }: TestSummaryProps) {
  const latest = reports.length > 0 ? reports[reports.length - 1] : null;
  const earlier = reports.slice(0, -1);
  const allPassed = latest !== null && latest.failed === 0;

  return (
    <Card className={allPassed ? "border-success/40 bg-success/[.025] shadow-sm" : latest ? "border-destructive/40 bg-destructive/[.025] shadow-sm" : "border-border/70 shadow-sm"}>
      <CardHeader className="flex-row items-center gap-2">
        <FlaskConical className="size-5 text-muted-foreground" />
        <CardTitle>آزمون‌ها</CardTitle>
        {latest && (
          <Badge variant={allPassed ? "success" : "destructive"} className="ms-auto">
            {allPassed ? "همه موفق" : "ناموفق"}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {generated && (
          <p className="text-sm leading-7 text-muted-foreground">
            {fa(countOf(generated.derived))} آزمون از روی مشخصات ربات و {fa(countOf(generated.acceptance))} آزمون از روی
            نیازمندی‌های شما ساخته شد.
          </p>
        )}
        {generated?.notes && generated.notes.length > 0 && (
          <ul aria-label="نکته‌های ساخت آزمون" className="flex flex-col gap-1 rounded-lg bg-surface-secondary/60 p-3 text-sm leading-7">
            {generated.notes.map((n, i) => (
              <li key={i} className="whitespace-pre-line">
                {n}
              </li>
            ))}
          </ul>
        )}

        {latest ? (
          <>
            <div className="flex items-center gap-2 text-lg font-semibold">
              {allPassed ? (
                <CircleCheck className="size-5 text-success" />
              ) : (
                <CircleX className="size-5 text-destructive" />
              )}
              <span>
                {fa(latest.passed)} از {fa(latest.total)} آزمون موفق
              </span>
            </div>

            {latest.failures.length > 0 && (
              <ul className="flex flex-col gap-2">
                {latest.failures.map((f) => (
                  <li key={f.id} className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm leading-7">
                    <div className="font-medium">{f.title}</div>
                    <div className="text-muted-foreground">{f.message}</div>
                  </li>
                ))}
              </ul>
            )}

            {earlier.length > 0 && (
              <div className="border-t pt-3 text-xs text-muted-foreground">
                <div className="mb-1 font-medium">تلاش‌های قبلی</div>
                <ul className="flex flex-col gap-0.5">
                  {earlier.map((r, i) => (
                    <li key={i}>
                      تلاش {fa(i + 1)}: {fa(r.passed)} از {fa(r.total)} موفق
                      {r.failures.length > 0 && ` (ناموفق: ${r.failures.map((f) => f.title).join("، ")})`}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">آزمون‌ها در انتظار اجرا هستند.</p>
        )}
      </CardContent>
    </Card>
  );
}
