import { Check, CircleAlert, Loader2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fa, formatNumber } from "@/lib/format";
import type { PhaseEntry, PhaseState, ToolEntry } from "@/lib/agent-state";
import type { RunStatus, Usage } from "@/lib/types";
import { PHASE_LABELS, RUN_STATUS_LABELS } from "./labels";
import { cn } from "@/lib/utils";

function StateIcon({ state }: { state: PhaseState }) {
  if (state === "running") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-accent text-accent-foreground" role="img" aria-label="در حال انجام">
        <Loader2 className="size-3.5 animate-spin" />
      </span>
    );
  }
  if (state === "done") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-success text-white" role="img" aria-label="انجام شد">
        <Check className="size-3.5" />
      </span>
    );
  }
  return (
    <span className="flex size-5 items-center justify-center rounded-full bg-destructive text-white" role="img" aria-label="ناموفق">
      <X className="size-3.5" />
    </span>
  );
}

function ToolRow({ tool }: { tool: ToolEntry }) {
  return (
    <li className="flex flex-col gap-0.5 text-sm">
      <div className="flex items-start gap-2">
        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/50" aria-hidden />
        <div className="min-w-0">
          <span>{tool.summary}</span>{" "}
          <span dir="ltr" className="inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
            {tool.name}
          </span>
        </div>
      </div>
      {tool.result ? (
        <div
          className={cn(
            "ms-3.5 flex items-start gap-1.5 text-xs",
            tool.result.ok ? "text-success" : "text-destructive",
          )}
        >
          {tool.result.ok ? <Check className="mt-0.5 size-3 shrink-0" /> : <CircleAlert className="mt-0.5 size-3 shrink-0" />}
          <span>{tool.result.summary}</span>
        </div>
      ) : (
        <div className="ms-3.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" />
          <span>در حال اجرا…</span>
        </div>
      )}
    </li>
  );
}

function PhaseRow({ entry, last }: { entry: PhaseEntry; last: boolean }) {
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!last && <span className="absolute start-[9.5px] top-6 bottom-0 w-px bg-muted-foreground/25" aria-hidden />}
      <div className="z-10 shrink-0">
        <StateIcon state={entry.state} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium">
          <span>{PHASE_LABELS[entry.phase]}</span>
          {entry.attempt > 1 && <span className="text-xs font-normal text-muted-foreground">(تلاش {fa(entry.attempt)})</span>}
        </div>
        {entry.summary && <p className="mt-0.5 text-xs text-muted-foreground">{entry.summary}</p>}
        {entry.tools.length > 0 && (
          <ul className="mt-2 flex flex-col gap-2 rounded-lg bg-muted/60 p-2.5">
            {entry.tools.map((tool) => (
              <ToolRow key={tool.id} tool={tool} />
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

const STATUS_VARIANT: Record<RunStatus, "accent" | "success" | "warning" | "destructive" | "secondary"> = {
  running: "accent",
  waiting_user: "warning",
  waiting_approval: "warning",
  done: "success",
  failed: "destructive",
  rejected: "secondary",
  interrupted: "destructive",
};

interface ActivityTimelineProps {
  phases: PhaseEntry[];
  status: RunStatus | null;
  usage: Usage | null;
}

/** Phases as a vertical checklist; tool calls are nested under the phase that made them. */
export function ActivityTimeline({ phases, status, usage }: ActivityTimelineProps) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle>فعالیت ایجنت</CardTitle>
        {status && <Badge variant={STATUS_VARIANT[status]}>{RUN_STATUS_LABELS[status]}</Badge>}
      </CardHeader>
      <CardContent>
        {phases.length === 0 ? (
          <p className="text-sm text-muted-foreground">هنوز فعالیتی ثبت نشده است. پیام خود را بفرستید تا ایجنت شروع کند.</p>
        ) : (
          <ol className="flex flex-col">
            {phases.map((entry, i) => (
              <PhaseRow key={entry.key} entry={entry} last={i === phases.length - 1} />
            ))}
          </ol>
        )}
        {usage && (
          <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
            <dt>توکن ورودی</dt>
            <dd className="text-end">{formatNumber(usage.input_tokens)}</dd>
            <dt>توکن خروجی</dt>
            <dd className="text-end">{formatNumber(usage.output_tokens)}</dd>
            <dt>توکن از حافظهٔ نهان</dt>
            <dd className="text-end">{formatNumber(usage.cached_tokens)}</dd>
            <dt>فراخوانی ابزار</dt>
            <dd className="text-end">{formatNumber(usage.tool_calls)}</dd>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
