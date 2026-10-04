"use client";

import { REVISION_STATUS_LABELS, REVISION_STATUS_VARIANTS } from "@/components/app/revision-labels";
import { Badge } from "@/components/ui/badge";
import { fa, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RevisionSummary } from "@/lib/types";

interface RevisionListProps {
  revisions: RevisionSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** Revisions, newest first: number, status, the owner's request, time and test counts. */
export function RevisionList({ revisions, selectedId, onSelect }: RevisionListProps) {
  return (
    <ul className="flex flex-col gap-2" aria-label="نسخه‌ها">
      {revisions.map((r) => {
        const active = r.id === selectedId;
        return (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onSelect(r.id)}
              aria-current={active ? "true" : undefined}
              className={cn(
                "flex w-full flex-col gap-1.5 rounded-xl border bg-card p-3 text-start transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                active ? "border-primary/60 bg-accent/50" : "hover:bg-muted/60",
              )}
            >
              <span className="flex items-center gap-2">
                <span className="font-semibold">نسخهٔ {fa(r.number)}</span>
                <Badge variant={REVISION_STATUS_VARIANTS[r.status]}>{REVISION_STATUS_LABELS[r.status]}</Badge>
              </span>
              <span className="line-clamp-2 text-sm leading-6 text-muted-foreground">{r.change_request ?? "بدون شرح"}</span>
              <span className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{formatDateTime(r.created_at)}</span>
                {r.tests ? (
                  <span className={r.tests.failed > 0 ? "font-medium text-destructive" : undefined}>
                    {fa(r.tests.passed)} از {fa(r.tests.total)} آزمون موفق
                  </span>
                ) : (
                  <span>آزمونی اجرا نشده</span>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
