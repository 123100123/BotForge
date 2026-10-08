"use client";

import { StatusBadge } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import { fa } from "@/lib/format";
import type { AnalysisProfileOut } from "@/lib/types";

/** Saved analysis profiles, one ruled row each: name, sheet, how much it measures and how often it ran. */
export function ProfileList({
  profiles,
  onRun,
  onEdit,
}: {
  profiles: AnalysisProfileOut[];
  onRun: (profile: AnalysisProfileOut) => void;
  onEdit: (profile: AnalysisProfileOut) => void;
}) {
  return (
    <ul className="overflow-hidden rounded-md border border-border bg-surface">
      {profiles.map((p) => (
        <li key={p.id} className="flex flex-col gap-3 border-t border-border p-4 first:border-t-0 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 className="text-h3 text-fg">{p.name}</h3>
              {p.daily_report && (
                <StatusBadge tone="brand" marker>
                  گزارش روزانهٔ کارکنان
                </StatusBadge>
              )}
            </div>
            <p className="text-small text-fg-secondary">
              {p.sheet && (
                <>
                  برگهٔ <bdi>{p.sheet}</bdi> ·{" "}
                </>
              )}
              {fa((p.metrics ?? []).length)} شاخص · {fa(p.runs_count)} بار اجرا شده
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button type="button" size="sm" onClick={() => onRun(p)}>
              اجرای تحلیل
            </Button>
            <Button type="button" size="sm" variant="secondary" onClick={() => onEdit(p)}>
              ویرایش
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
