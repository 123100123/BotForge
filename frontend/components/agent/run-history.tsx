"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, CircleCheck, Loader2, RotateCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fa, formatDateTime } from "@/lib/format";
import type { FeedItem } from "@/lib/agent-state";
import type { AgentRun, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RUN_STATUS_LABELS, RUN_STATUS_VARIANT, runKindLabel } from "./labels";
import type { PastRun } from "./use-agent-run";

/** Feed items that are the conversation itself; the other cards of an earlier run are folded away. */
const CONVERSATION_KINDS: ReadonlySet<FeedItem["kind"]> = new Set(["owner", "agent", "deployed", "error"]);

/** A thin line between runs: what the run was, when it started, and how it ended. */
export function RunDivider({ run, status, children }: { run: AgentRun; status: RunStatus | null; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs whitespace-nowrap text-muted-foreground">
      <span className="hidden h-px flex-1 bg-border sm:block" aria-hidden />
      <span>{runKindLabel(run.kind)}</span>
      <span aria-hidden>·</span>
      <time dateTime={run.created_at}>{formatDateTime(run.created_at)}</time>
      {status && <Badge variant={RUN_STATUS_VARIANT[status]}>{RUN_STATUS_LABELS[status]}</Badge>}
      {children}
      <span className="hidden h-px flex-1 bg-border sm:block" aria-hidden />
    </div>
  );
}

/** Compact "revision N went live" line for an earlier run (the full card with next steps belongs to the latest run). */
export function DeployedLine({ number }: { number: number }) {
  return (
    <div className="flex items-center gap-2 text-sm font-medium text-success">
      <CircleCheck className="size-4" />
      نسخهٔ {fa(number)} فعال شد
    </div>
  );
}

interface PastRunGroupProps {
  entry: PastRun;
  /** Renders one item of this run read-only. */
  renderItem: (item: FeedItem) => ReactNode;
  onRetry: () => void;
}

/**
 * An earlier run in the conversation: its messages are always shown; its cards (requirements, questions,
 * tests, review) are folded until the owner opens them.
 */
export function PastRunGroup({ entry, renderItem, onRetry }: PastRunGroupProps) {
  const [open, setOpen] = useState(false);
  const { run, view, failed } = entry;
  const feed = view?.feed ?? [];
  const folded = feed.filter((item) => !CONVERSATION_KINDS.has(item.kind)).length;
  const shown = open ? feed : feed.filter((item) => CONVERSATION_KINDS.has(item.kind));

  return (
    <section className="flex flex-col gap-4" aria-label={`${runKindLabel(run.kind)}، ${formatDateTime(run.created_at)}`}>
      <RunDivider run={run} status={view?.status ?? run.status}>
        {folded > 0 && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="inline-flex items-center gap-1 rounded px-1 text-primary hover:underline"
          >
            {open ? "بستن جزئیات" : `جزئیات (${fa(folded)})`}
            <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
          </button>
        )}
      </RunDivider>
      {failed ? (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          این بخش از گفت‌وگو بارگذاری نشد.
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RotateCw />
            تلاش دوباره
          </Button>
        </div>
      ) : view === null ? (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          در حال بارگذاری…
        </div>
      ) : (
        shown.map((item) => <div key={`${item.kind}-${item.id}`}>{renderItem(item)}</div>)
      )}
    </section>
  );
}
