"use client";

import { useEffect, useMemo, useState } from "react";
import { WifiOff, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { IS_MOCK } from "@/lib/config";
import { GOLDEN_CREATE_PROMPT, GOLDEN_MODIFY_PROMPT } from "@/lib/fixtures/common";
import { latestReport, type FeedItem, type RunView } from "@/lib/agent-state";
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

export type WorkspaceTab = "agent" | "simulator" | "tests" | "data" | "versions" | "settings";

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

function EmptyState({ live, onPick }: { live: boolean; onPick: (text: string) => void }) {
  const example = live ? GOLDEN_MODIFY_PROMPT : GOLDEN_CREATE_PROMPT;
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-10 text-center">
      <h3 className="text-base font-semibold">{live ? "چه تغییری در ربات می‌خواهید؟" : "ربات‌تان را برای من توضیح دهید"}</h3>
      <p className="max-w-md text-sm leading-7 text-muted-foreground">
        {live
          ? "تغییر را به زبان ساده بنویسید. ایجنت آن را روی یک نسخهٔ پیش‌نویس اعمال و آزمایش می‌کند و فقط با تأیید شما فعال می‌شود."
          : "کسب‌وکارتان و کاری که ربات باید انجام دهد را بنویسید. ایجنت در صورت نیاز چند پرسش می‌پرسد، ربات را می‌سازد و آزمایش می‌کند."}
      </p>
      {IS_MOCK && (
        <Button variant="outline" size="sm" onClick={() => onPick(example)}>
          استفاده از پیام نمونه
        </Button>
      )}
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
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="flex min-w-0 flex-col gap-3">
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
              />
            )
          }
          onSend={(text) => void agent.send(text)}
          disabledReason={disabledReason}
          placeholder={placeholder}
          seed={seed}
        />
      </div>
      <aside className="min-w-0 lg:sticky lg:top-4 lg:self-start">
        <ActivityTimeline phases={view.phases} status={status} usage={view.usage} />
      </aside>
    </div>
  );
}
