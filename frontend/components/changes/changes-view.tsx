"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { WifiOff, X } from "lucide-react";
import { useAgentRunContext } from "@/components/agent/agent-run-provider";
import { useBusiness } from "@/components/app/business-context";
import { useRevisions } from "@/components/app/use-revisions";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/use-toast";
import { fa, relativeTime } from "@/lib/format";
import type { RevisionSummary } from "@/lib/types";
import { ChangeComposer } from "./change-composer";
import { ChangeTimeline, type ChangeTimelineItem } from "./change-timeline";
import { BUSINESS_EXAMPLES, CHANGE_EXAMPLES } from "./examples";
import { PendingRequest } from "./pending-request";
import { ProposalDetail } from "./proposal-detail";
import {
  feedItems,
  isOpenRun,
  oneLine,
  proposalState,
  requestedChange,
  revisionState,
  runRevisionId,
} from "./run-model";
import { VersionDetail } from "./version-detail";
import { latestReport, type PendingOwnerMessage } from "@/lib/agent-state";

/** Activations already announced with a toast (the view remounts when the owner navigates). */
const announced = new Set<string>();

const FIRST_EXAMPLES = BUSINESS_EXAMPLES.map((e) => ({ label: e.label, text: e.description }));

function composerReason(status: string | null, pending: PendingOwnerMessage | null): string | null {
  if (pending?.target === "new" && pending.state === "sending") return "درخواست شما در حال ارسال است.";
  if (pending?.target === "new" && pending.state === "failed") {
    return "درخواست قبلی شما ارسال نشد. آن را دوباره بفرستید یا حذف کنید، بعد می‌توانید درخواست تازه‌ای بنویسید.";
  }
  switch (status) {
    case "running":
      return "دستیار در حال آماده‌سازی یک پیشنهاد است. تا تمام نشود، تغییر تازه‌ای نمی‌شود خواست.";
    case "waiting_user":
      return "دستیار منتظر پاسخ شماست. بعد از پاسخ دادن و تأیید یا رد پیشنهاد، می‌توانید تغییر تازه‌ای بخواهید.";
    case "waiting_approval":
      return "یک پیشنهاد آمادهٔ تأیید دارید. آن را فعال یا رد کنید، بعد تغییر تازه‌ای بخواهید.";
    default:
      return null;
  }
}

/**
 * The Changes page body. A business with an active version shows the timeline of proposals and versions
 * beside the selected one (selection is `?v=`); a business without one is the first build, with a step
 * indicator and a fuller composer. The run itself lives in the bot layout's provider.
 */
export function ChangesView() {
  const { bot, reload } = useBusiness();
  const agent = useAgentRunContext();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { view, status } = agent;
  const firstBuild = !bot.active_revision_id;

  const draftId = runRevisionId(view);
  const deployedItem = feedItems(view, "deployed")[0] ?? null;
  // The list is re-read when the active version changes and when the run changes state (a draft appears at approval).
  const { revisions, error: revisionsError, reload: reloadRevisions } = useRevisions(
    bot.id,
    `${bot.active_revision_id ?? ""}|${status ?? ""}|${draftId ?? ""}`,
  );

  // Toasts for the two outcomes the owner decides.
  useEffect(() => {
    if (!agent.runId) return;
    if (agent.decided === "approved" && deployedItem) {
      const key = `${agent.runId}:deployed`;
      if (announced.has(key)) return;
      announced.add(key);
      toast({ title: `نسخهٔ ${fa(deployedItem.number)} فعال شد`, description: "ربات تلگرام از همین حالا مطابق آن رفتار می‌کند.", tone: "success" });
    } else if (agent.decided === "rejected" && status === "rejected") {
      const key = `${agent.runId}:rejected`;
      if (announced.has(key)) return;
      announced.add(key);
      toast({ title: "پیشنهاد رد شد", description: "ربات فعلی بدون تغییر ماند.", tone: "neutral" });
    }
  }, [agent.runId, agent.decided, deployedItem, status]);

  const detailRef = useRef<HTMLDivElement>(null);
  const vParam = searchParams.get("v");
  const firstRender = useRef(true);
  // Below xl the detail sits under the list: bring it into view when the owner picks another item.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (window.matchMedia("(min-width: 1280px)").matches) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    detailRef.current?.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }, [vParam]);

  const [expanded, setExpanded] = useState(false);

  /** A request that is on its way (or failed) before the server has a run for it: shown instead of the run. */
  const pending = agent.pending;
  const pendingNew = pending !== null && pending.target === "new" && pending.state !== "received";

  // `connectionBanner`: the run's own page shows the connection state itself; this is for the pages that do not.
  const banners = (connectionBanner: boolean) => (
    <>
      {connectionBanner && agent.connection === "reconnecting" && isOpenRun(status) && (
        <div role="status" className="flex items-center gap-2 rounded-sm bg-warning-soft p-3 text-small text-warning-text">
          <WifiOff strokeWidth={1.75} aria-hidden className="size-4 shrink-0" />
          ارتباط قطع شد؛ در حال اتصال دوباره…
        </div>
      )}
      {agent.error && (
        <div role="alert" className="flex items-start gap-2 rounded-sm bg-danger-soft p-3 text-small text-danger-text">
          <span className="flex-1">{agent.error}</span>
          <button
            type="button"
            onClick={agent.clearError}
            aria-label="بستن پیام خطا"
            className="rounded-xs p-1 text-danger-text transition-colors duration-fast hover:bg-danger/10"
          >
            <X strokeWidth={1.75} className="size-4" />
          </button>
        </div>
      )}
    </>
  );

  if (agent.loading) {
    return (
      <div role="status" aria-label="در حال بارگذاری" className="flex flex-col gap-4">
        <Skeleton className="h-28 rounded-md" />
        <Skeleton className="h-64 rounded-md" />
      </div>
    );
  }

  const open = isOpenRun(status);
  const hasRun = agent.runId !== null;
  const base = pathname;

  // ------------------------------------------------------------------ first build
  if (firstBuild) {
    const reason = composerReason(status, pending);
    const revision = draftId ? (revisions?.find((r) => r.id === draftId) ?? null) : null;
    return (
      <div className="flex w-full max-w-4xl flex-col gap-6">
        {banners(false)}
        {pendingNew ? (
          <PendingRequest agent={agent} firstBuild />
        ) : (
          hasRun && <ProposalDetail bot={bot} agent={agent} firstBuild revision={revision} />
        )}
        {!open && !pendingNew && (
          <section className="flex flex-col gap-4 rounded-md border border-border bg-surface p-5 sm:p-6">
            <div className="flex flex-col gap-1">
              <h2 className="text-h2 text-fg">{hasRun ? "دوباره توضیح بدهید" : "ربات‌تان را برای دستیار توضیح دهید"}</h2>
              <p className="text-body text-fg-secondary">
                {hasRun
                  ? "این بار می‌توانید کامل‌تر یا به شکل دیگری بنویسید؛ دستیار از نو شروع می‌کند."
                  : "بنویسید کسب‌وکارتان چیست و مشتری‌ها در ربات تلگرام چه کارهایی باید بتوانند بکنند. دستیار در صورت نیاز چند پرسش می‌پرسد، ربات را می‌سازد و آزمایش می‌کند."}
              </p>
            </div>
            <ChangeComposer
              variant="first"
              label="کسب‌وکار و کار ربات را توضیح دهید"
              placeholder="مثلاً: من یک آموزشگاه دارم و می‌خواهم مشتری‌ها در ربات تلگرام کارگاه‌ها را ببینند و ثبت‌نام کنند…"
              submitLabel="ساخت پیشنهاد"
              examples={FIRST_EXAMPLES}
              disabledReason={reason}
              busy={agent.busy}
              hint="هر چه دقیق‌تر بنویسید، پرسش‌های کمتری لازم می‌شود. تا شما تأیید نکنید چیزی فعال نمی‌شود."
              onSubmit={async (text) => {
                await agent.send(text);
              }}
            />
          </section>
        )}
      </div>
    );
  }

  // ------------------------------------------------------------------ business with versions
  const revList: RevisionSummary[] = revisions ?? [];
  const matched = draftId ? (revList.find((r) => r.id === draftId) ?? null) : null;
  const request = requestedChange(view);
  const report = latestReport(view);
  const resolved = status === "done" || status === "rejected";
  const proposalListed = hasRun && (open || status === "failed" || status === "interrupted" || (resolved && !matched));

  // A run that failed or was interrupted stays in front: its failure and the retry are what the owner needs.
  const lastRunBroke = status === "failed" || status === "interrupted";
  const defaultKey = open || lastRunBroke ? (matched?.id ?? "proposal") : (bot.active_revision_id ?? (proposalListed ? "proposal" : (revList[0]?.id ?? null)));
  const hrefFor = (key: string) => (key === defaultKey ? base : `${base}?v=${encodeURIComponent(key)}`);

  const rows: ChangeTimelineItem[] = [];
  if (proposalListed && !matched) {
    rows.push({
      key: "proposal",
      href: hrefFor("proposal"),
      label: "پیشنهاد تغییر",
      summary: oneLine(request?.text),
      state: proposalState(status, Boolean(deployedItem)),
      time: request ? relativeTime(request.ts) : null,
      tests: report ? { passed: report.passed, total: report.total } : null,
    });
  }
  for (const r of revList) {
    const isRun = matched !== null && r.id === matched.id;
    rows.push({
      key: r.id,
      href: hrefFor(r.id),
      label: `نسخهٔ ${fa(r.number)}`,
      summary: oneLine(r.change_request) ?? (isRun ? oneLine(request?.text) : null),
      state: isRun && open ? proposalState(status, Boolean(deployedItem)) : revisionState(r.status),
      time: relativeTime(r.created_at),
      tests: r.tests ? { passed: r.tests.passed, total: r.tests.total } : null,
    });
  }

  let selectedKey: string | null = defaultKey;
  if (vParam && rows.some((r) => r.key === vParam)) selectedKey = vParam;
  else if (vParam === "proposal" && matched) selectedKey = matched.id;
  if (!rows.some((r) => r.key === selectedKey)) selectedKey = rows[0]?.key ?? null;

  const isRunSelection = selectedKey === "proposal" || (matched !== null && selectedKey === matched.id);
  // The run's own page stays while it is open and, after the owner decided it, until they leave.
  const showProposal = hasRun && isRunSelection && (open || agent.decided !== null || !matched);

  const reason = composerReason(status, pending);
  const activeNumber = bot.active_revision_number ?? revList.find((r) => r.id === bot.active_revision_id)?.number ?? null;

  return (
    <div className="grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)] xl:grid-rows-[auto_1fr] xl:items-start">
      <section aria-labelledby="new-change-title" className="flex min-w-0 flex-col gap-3 rounded-md border border-border bg-surface p-5 xl:col-start-1 xl:row-start-1">
        <h2 id="new-change-title" className="text-h3 text-fg">
          درخواست تغییر تازه
        </h2>
        <ChangeComposer
          label="تغییر مورد نظر را به زبان ساده بنویسید"
          placeholder="مثلاً: ظرفیت هر کارگاه را ۱۲ نفر کن."
          submitLabel="ساخت پیشنهاد تغییر"
          examples={CHANGE_EXAMPLES}
          disabledReason={reason}
          busy={agent.busy}
          hint="با این پیام یک پیشنهاد تغییر ساخته می‌شود؛ تا شما تأیید نکنید چیزی در ربات عوض نمی‌شود."
          onSubmit={async (text) => {
            await agent.send(text);
            router.replace(base, { scroll: false });
          }}
        />
      </section>

      <div ref={detailRef} className="flex min-w-0 scroll-mt-20 flex-col gap-4 xl:col-start-2 xl:row-span-2 xl:row-start-1">
        {banners(!showProposal || pendingNew)}
        {pendingNew ? (
          <PendingRequest agent={agent} firstBuild={false} />
        ) : showProposal ? (
          <ProposalDetail bot={bot} agent={agent} firstBuild={false} revision={matched} />
        ) : selectedKey && selectedKey !== "proposal" ? (
          <VersionDetail
            key={selectedKey}
            botId={bot.id}
            revisionId={selectedKey}
            activeNumber={activeNumber}
            onChanged={() => {
              reloadRevisions();
              reload();
            }}
          />
        ) : null}
      </div>

      <section aria-labelledby="timeline-title" className="min-w-0 overflow-hidden rounded-md border border-border bg-surface xl:col-start-1 xl:row-start-2">
        <h2 id="timeline-title" className="px-4 py-3 text-h3 text-fg">
          تغییرات و نسخه‌ها
        </h2>
        <div className="border-t border-border">
          {revisionsError ? (
            <ErrorState message={revisionsError} title="فهرست نسخه‌ها بارگذاری نشد" onRetry={reloadRevisions} />
          ) : revisions === null ? (
            <div role="status" aria-label="در حال بارگذاری" className="flex flex-col gap-3 p-4">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : (
            <ChangeTimeline
              items={rows}
              selectedKey={selectedKey}
              expanded={expanded}
              onToggleExpanded={() => setExpanded((e) => !e)}
            />
          )}
        </div>
      </section>
    </div>
  );
}
