"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, ArrowUpLeft, Sparkles, WifiOff, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LaunchChecklist } from "@/components/app/launch-checklist";
import { IS_MOCK } from "@/lib/config";
import { GOLDEN_CREATE_PROMPT, GOLDEN_MODIFY_PROMPT } from "@/lib/fixtures/common";
import { latestReport, type FeedItem, type RunView } from "@/lib/agent-state";
import type { WorkspaceTab } from "@/components/app/workspace";
import type { Bot, RunKind, RunStatus } from "@/lib/types";
import { ActivityTimeline } from "./activity-timeline";
import { ChatMessage, ChatThread, type ChatItem } from "./chat-thread";
import { DeployedState } from "./deployed-state";
import { QuestionsCard } from "./questions-card";
import { RequirementsCard } from "./requirements-card";
import { ReviewCard, type ReviewDecision } from "./review-card";
import { DeployedLine, PastRunGroup, RunDivider } from "./run-history";
import { TestSummary } from "./test-summary";
import { useAgentRun } from "./use-agent-run";

interface AgentTabProps {
  bot: Bot;
  /** The bot changed on the server (a revision was activated); reload it. */
  onBotChanged: () => void;
  onOpenTab: (tab: WorkspaceTab) => void;
}

function reviewDecision(
  view: RunView,
  status: RunStatus | null,
  decided: "approved" | "rejected" | null,
): ReviewDecision {
  if (decided) return decided;
  const approvalPhase = [...view.phases].reverse().find((p) => p.phase === "await_approval");
  if (approvalPhase?.state === "running" || (!approvalPhase && status === "waiting_approval")) return "pending";
  if (view.feed.some((i) => i.kind === "deployed")) return "approved";
  if (status === "rejected" || approvalPhase?.state === "failed") return "rejected";
  if (approvalPhase?.state === "done") return "approved";
  return status === "waiting_approval" ? "pending" : "closed";
}

function EmptyState({ live, onPick, bot, onOpenTab }: { live: boolean; onPick: (text: string) => void; bot: Bot; onOpenTab: (tab: WorkspaceTab) => void }) {
  const example = live ? GOLDEN_MODIFY_PROMPT : GOLDEN_CREATE_PROMPT;
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-3 py-8 text-center sm:py-14">
      <div className="grid size-16 place-items-center rounded-3xl bg-primary/10 text-primary shadow-inner"><Sparkles className="size-8" /></div>
      <h3 className="text-xl font-bold tracking-tight">{live ? "چه تغییری در ربات می‌خواهید؟" : "ربات‌تان را برای من توضیح دهید"}</h3>
      <p className="max-w-lg text-sm leading-7 text-muted-foreground">
        {live
          ? "تغییر را به زبان ساده بنویسید. ایجنت آن را روی یک نسخهٔ پیش‌نویس اعمال و آزمایش می‌کند و فقط با تأیید شما فعال می‌شود."
          : "کسب‌وکارتان و کاری که ربات باید انجام دهد را بنویسید. ایجنت در صورت نیاز چند پرسش می‌پرسد، ربات را می‌سازد و آزمایش می‌کند."}
      </p>
      {IS_MOCK && (
        <Button variant="outline" size="sm" onPress={() => onPick(example)}>
          استفاده از پیام نمونه <ArrowUpLeft className="size-4" />
        </Button>
      )}
      {!live && <div className="mt-4 w-full max-w-xl text-start"><LaunchChecklist bot={bot} onOpenTab={onOpenTab} compact /></div>}
    </div>
  );
}

/** The Agent tab: chat, live activity timeline, and the cards the agent produces along the way. */
export function AgentTab({ bot, onBotChanged, onOpenTab }: AgentTabProps) {
  const agent = useAgentRun(bot.id);
  const { view, status } = agent;
  const [seed, setSeed] = useState<{ key: number; text: string } | null>(null);

  const deployed = useMemo(() => view.feed.find((i) => i.kind === "deployed")?.id ?? null, [view.feed]);
  useEffect(() => {
    if (deployed !== null) onBotChanged();
    // onBotChanged is a stable refetch callback; only a new deployment should trigger it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deployed]);

  /**
   * Renders one feed item of a run. `live` is the latest run, which the owner acts on; an earlier run is
   * read-only (its questions are closed, its review has no buttons, its deployment is one line).
   */
  function renderItem(item: FeedItem, runView: RunView, ctx: { live: boolean; kind: RunKind; decision: ReviewDecision }) {
    switch (item.kind) {
      case "owner":
      case "agent":
        return <ChatMessage from={item.kind} text={item.text} />;
      case "requirements":
        return <RequirementsCard requirements={item.requirements} />;
      case "questions":
        return (
          <QuestionsCard
            questions={item.questions}
            answer={item.answer}
            disabled={!ctx.live || status !== "waiting_user" || agent.busy}
            onAnswer={(text) => void agent.send(text)}
          />
        );
      case "tests":
        return <TestSummary generated={item.generated} reports={item.reports} />;
      case "review":
        return (
          <ReviewCard
            kind={item.diff ? "modify" : ctx.kind}
            diff={item.diff}
            approval={item.approval}
            requirements={runView.requirements}
            outline={runView.outline}
            report={latestReport(runView)}
            decision={ctx.decision}
            busy={agent.busy}
            onApprove={() => void agent.approve()}
            onReject={() => void agent.reject()}
          />
        );
      case "deployed":
        return ctx.live ? <DeployedState number={item.number} onOpenTab={onOpenTab} /> : <DeployedLine number={item.number} />;
      case "error":
        return (
          <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm leading-7">
            <div className="font-medium">خطا در اجرای ایجنت</div>
            <div>{item.message}</div>
          </div>
        );
    }
  }

  // Earlier runs first (oldest at the top), each folded to its messages; then the latest run in full.
  const items: ChatItem[] = agent.past.map((entry) => {
    const { run, view: pastView } = entry;
    let pastDecision: ReviewDecision = "closed";
    if (pastView) {
      const value = reviewDecision(pastView, pastView.status, null);
      pastDecision = value === "pending" ? "closed" : value; // an earlier run can no longer be decided
    }
    return {
      key: `run-${run.id}`,
      node: (
        <PastRunGroup
          entry={entry}
          renderItem={(item) =>
            pastView && renderItem(item, pastView, { live: false, kind: run.kind, decision: pastDecision })
          }
          onRetry={() => agent.retryPast(run.id)}
        />
      ),
    };
  });
  if (agent.run && agent.past.length > 0) {
    items.push({ key: `divider-${agent.run.id}`, node: <RunDivider run={agent.run} status={status} /> });
  }
  const kind: RunKind = agent.kind ?? (view.feed.some((i) => i.kind === "review" && i.diff) ? "modify" : "create");
  const decision = reviewDecision(view, status, agent.decided);
  for (const item of view.feed) {
    items.push({
      key: `${agent.runId}-${item.kind}-${item.id}`,
      node: renderItem(item, view, { live: true, kind, decision }),
    });
  }

  let disabledReason: string | null = null;
  if (agent.loading) disabledReason = "در حال بارگذاری…";
  else if (status === "running") disabledReason = "ایجنت در حال کار است…";
  else if (agent.busy) disabledReason = "در حال ارسال…";

  let placeholder = bot.active_revision_id ? "تغییر مورد نظر را بنویسید…" : "ربات مورد نظرتان را توضیح دهید…";
  if (status === "waiting_user") placeholder = "پاسخ خود را بنویسید…";
  else if (status === "waiting_approval") placeholder = "برای درخواست تغییر در پیش‌نویس، پیام بنویسید…";

  return (
    <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[minmax(0,1fr)_21rem]">
      <section className="flex min-w-0 flex-col gap-3 rounded-[1.5rem] border border-border/70 bg-card/80 p-3 shadow-sm sm:p-5" aria-label="گفتگو و ساخت ربات">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-4">
          <div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-primary/10 text-primary"><Sparkles className="size-5" /></span><div><h3 className="font-semibold">گفتگو با سازنده</h3><p className="text-xs text-muted-foreground">از ایده تا نسخهٔ آمادهٔ تأیید</p></div></div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground"><Activity className="size-3.5 text-primary" /> {status === "running" ? "در حال ساخت" : status === "waiting_approval" ? "در انتظار تأیید" : status === "waiting_user" ? "در انتظار پاسخ" : "آماده"}</span>
        </div>
        {agent.connection === "reconnecting" && (
          <div className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/5 p-2.5 text-sm">
            <WifiOff className="size-4 text-warning" />
            ارتباط قطع شد؛ در حال اتصال دوباره…
          </div>
        )}
        {agent.error && (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-sm">
            <span className="flex-1 leading-7">{agent.error}</span>
            <button onClick={agent.clearError} aria-label="بستن پیام خطا" className="rounded p-1 text-muted-foreground hover:text-foreground">
              <X className="size-4" />
            </button>
          </div>
        )}
        <ChatThread
          items={items}
          empty={
            agent.loading ? null : (
              <EmptyState
                live={Boolean(bot.active_revision_id)}
                onPick={(text) => setSeed((prev) => ({ key: (prev?.key ?? 0) + 1, text }))}
                bot={bot}
                onOpenTab={onOpenTab}
              />
            )
          }
          onSend={(text) => void agent.send(text)}
          disabledReason={disabledReason}
          placeholder={placeholder}
          seed={seed}
        />
      </section>
      <aside className="min-w-0 xl:sticky xl:top-5 xl:self-start">
        <ActivityTimeline phases={view.phases} status={status} usage={view.usage} />
      </aside>
    </div>
  );
}
