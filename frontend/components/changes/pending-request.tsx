"use client";

import { RunStatus, type RunStatusAgent } from "@/components/agent/run-status";
import { formatDateTime } from "@/lib/format";
import { DetailSection } from "./detail-section";

/**
 * The page body between the moment the owner presses send and the moment the server has a run for it:
 * their own words at once, «درخواست شما رسید» as soon as the server accepted them, or, when the request
 * itself failed, the error with [ارسال دوباره]. The run's own page (ProposalDetail) takes over from there.
 */
export function PendingRequest({ agent, firstBuild }: { agent: RunStatusAgent; firstBuild: boolean }) {
  const { pending } = agent;
  if (!pending) return null;
  return (
    <article aria-label="درخواست شما" className="flex flex-col overflow-clip rounded-md border border-border bg-surface">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-4">
        <h2 className="text-h2 text-fg">{firstBuild ? "پیشنهاد دستیار برای ربات شما" : "پیشنهاد تغییر"}</h2>
        <span className="ms-auto text-caption text-fg-muted">{formatDateTime(pending.ts)}</span>
      </header>
      <DetailSection title={firstBuild ? "شرح کسب‌وکار" : "تغییر درخواستی"}>
        <p className="text-body whitespace-pre-wrap">{pending.text}</p>
      </DetailSection>
      <RunStatus agent={agent} standalone />
    </article>
  );
}
