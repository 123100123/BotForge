"use client";

import { useEffect, useMemo, useRef } from "react";
import { MessageSquareText, TriangleAlert } from "lucide-react";
import type { AgentRunContextValue } from "@/components/agent/agent-run-provider";
import { ChatInput, ChatLog, type ChatLine } from "@/components/agent/chat-thread";
import { DeployedState } from "@/components/agent/deployed-state";
import { RunStatus } from "@/components/agent/run-status";
import { CAPABILITY_TYPE_LABELS, RISK_LABELS } from "@/components/agent/labels";
import { useOpenSection } from "@/components/app/shell/use-open-section";
import { ScenarioBrowser } from "@/components/tests/scenario-browser";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatDateTime, fa } from "@/lib/format";
import { sectionHref } from "@/lib/routes";
import { latestReport } from "@/lib/agent-state";
import type { Bot, RevisionSummary, RiskLevel, SpecChange, TestGroup } from "@/lib/types";
import { ChangeStateBadge } from "./change-state";
import { ConfigDiff } from "./config-diff";
import { DecisionBar, type DecisionPhase } from "./decision-bar";
import { DetailSection } from "./detail-section";
import { Disclosure } from "./disclosure";
import { QuestionCard } from "./question-card";
import { RequirementsList } from "./requirements-list";
import { feedItems, proposalState, requestedChange, reviewDecision, runRevisionId } from "./run-model";
import { TestSummary, type TestGroupView } from "./test-summary";
import { useRevisionDetail } from "./use-revision-detail";

type AgentCtx = AgentRunContextValue;

interface ProposalDetailProps {
  bot: Bot;
  agent: AgentCtx;
  /** The business has no active version yet: the same page, worded as building the bot. */
  firstBuild: boolean;
  /** The run's version as the revisions list knows it, if it is listed yet. */
  revision: RevisionSummary | null;
}

const RISK_TONE: Record<RiskLevel, "success" | "warning" | "danger"> = { low: "success", medium: "warning", high: "danger" };

function countOf(group: TestGroup): { count: number; items: { title: string; reason?: string }[] } {
  return typeof group === "number"
    ? { count: group, items: [] }
    : { count: group.length, items: group.map((t) => ({ title: t.title, reason: t.reason ?? undefined })) };
}

function countNumber(value: number | unknown[]): number {
  return typeof value === "number" ? value : value.length;
}

/**
 * The change proposal of the current run, in the order the owner needs it: the request, what the assistant
 * understood, a question if it is waiting, the effect on the bot, the tests, then conversation and technical
 * details collapsed, and the decision bar at the bottom. All data comes from the run controller; the
 * presentational pieces (RequirementsList, QuestionCard, ConfigDiff, TestSummary, DecisionBar) are pure.
 */
export function ProposalDetail({ bot, agent, firstBuild, revision }: ProposalDetailProps) {
  const openSection = useOpenSection();
  const { view, status } = agent;
  // The owner's own words: the run's first message, or the one just sent that has not come back as an event yet.
  const request = requestedChange(view) ?? (agent.pending ? { text: agent.pending.text, ts: agent.pending.ts } : null);
  const deployed = feedItems(view, "deployed")[0] ?? null;
  const reviews = feedItems(view, "review");
  const review = reviews[reviews.length - 1] ?? null;
  const diff = review?.diff ?? null;
  const approval = review?.approval ?? null;
  const questions = feedItems(view, "questions");
  const openQuestions = questions.some((q) => q.answer === null);
  const testsItem = feedItems(view, "tests").at(-1) ?? null;
  const report = latestReport(view);
  const state = proposalState(status, Boolean(deployed));
  const decision = reviewDecision(view, status, agent.decided);
  const draftId = runRevisionId(view);

  // The draft version (diff, scenarios): read when the run reaches approval and again when its status changes.
  const { detail } = useRevisionDetail(
    draftId && (status === "waiting_approval" || status === "done" || status === "rejected") ? draftId : null,
    status ?? "none",
  );

  const number = revision?.number ?? detail?.number ?? deployed?.number ?? null;
  const lastAgentMessage = [...view.feed].reverse().find((i) => i.kind === "agent");

  // Bring the question into view when the run starts waiting for an answer.
  const questionRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (status !== "waiting_user" || !openQuestions) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    questionRef.current?.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }, [status, openQuestions]);

  const pending = agent.pending;
  const chatLines: ChatLine[] = useMemo(() => {
    const lines: ChatLine[] = view.feed.flatMap((item) =>
      item.kind === "owner" || item.kind === "agent" ? [{ key: `${item.kind}-${item.id}`, from: item.kind, text: item.text }] : [],
    );
    // A message that is not in the feed yet shows at once, with its delivery state.
    if (pending) {
      lines.push({
        key: "pending",
        from: "owner",
        text: pending.text,
        note: pending.state === "sending" ? "در حال ارسال…" : pending.state === "received" ? "رسید" : "ارسال نشد",
      });
    }
    return lines;
  }, [view.feed, pending]);

  // ---- effect on the bot
  const outline = view.outline;
  const capTitle = (key: string) => outline?.capabilities.find((c) => c.key === key)?.title ?? key;
  const affected: { key: string; title: string; type: string | null }[] = diff
    ? diff.affected_capabilities.map((key) => ({
        key,
        title: capTitle(key),
        type: null,
      }))
    : (outline?.capabilities ?? []).map((c) => ({ key: c.key, title: c.title, type: CAPABILITY_TYPE_LABELS[c.type] }));
  // The diff the assistant reported is the owner's source of truth; the draft version's own diff fills in when it sent none.
  const changes: SpecChange[] | null = diff
    ? diff.changes.map((c) => ({ path: [], kind: c.kind, old: null, new: null, label_fa: c.label_fa }))
    : detail && detail.parent_id !== null
      ? detail.diff
      : null; // the first version has nothing to compare with
  const showImpact = affected.length > 0 || changes !== null || (diff?.warnings.length ?? 0) > 0;

  // ---- tests
  const groups: TestGroupView[] = diff
    ? [
        { label: "آزمون قبلی بدون تغییر منتقل شد", ...countOf(diff.tests.carried) },
        { label: "آزمون جدید نوشته شد", ...countOf(diff.tests.new) },
        { label: "آزمون قدیمی کنار گذاشته شد", ...countOf(diff.tests.superseded) },
      ]
    : [];
  const reports = testsItem?.reports ?? [];
  const attempts = reports
    .slice(0, -1)
    .map((r, i) => `بار ${fa(i + 1)}: ${fa(r.passed)} از ${fa(r.total)} موفق${r.failures.length ? ` (ناموفق: ${r.failures.map((f) => f.title).join("، ")})` : ""}`);
  const testsNote = testsItem?.generated
    ? `${fa(countNumber(testsItem.generated.derived))} آزمون از روی پیکربندی ربات و ${fa(countNumber(testsItem.generated.acceptance))} آزمون از روی خواستهٔ شما ساخته شد.`
    : null;
  const showTests = testsItem !== null || status === "running";

  // ---- decision bar
  let phase: DecisionPhase | null = null;
  if (approval) {
    if (decision === "pending") phase = "pending";
    else if (decision === "approved") phase = deployed ? "activated" : "activating";
    else if (decision === "rejected") phase = "rejected";
  }

  const assistantAsks = status === "waiting_user" && !openQuestions && lastAgentMessage?.kind === "agent";
  const showAnswer = state === "closed" && lastAgentMessage?.kind === "agent";
  const canChat = status === "waiting_user" || status === "waiting_approval";
  let chatDisabled: string | null = null;
  if (agent.busy) chatDisabled = "در حال ارسال…";

  return (
    <article aria-label="پیشنهاد تغییر" className="flex flex-col overflow-clip rounded-md border border-border bg-surface">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-4">
        <h2 className="text-h2 text-fg">{firstBuild ? "پیشنهاد دستیار برای ربات شما" : "پیشنهاد تغییر"}</h2>
        {number !== null && <span className="text-body text-fg-secondary">نسخهٔ {fa(number)}</span>}
        <ChangeStateBadge state={state} />
        {request && <span className="ms-auto text-caption text-fg-muted">{formatDateTime(request.ts)}</span>}
      </header>

      {request && (
        <DetailSection title={firstBuild ? "شرح کسب‌وکار" : "تغییر درخواستی"}>
          <p className="text-body whitespace-pre-wrap">{request.text}</p>
        </DetailSection>
      )}

      <RunStatus agent={agent} />

      {(assistantAsks || showAnswer) && lastAgentMessage?.kind === "agent" && (
        <DetailSection title={assistantAsks ? "دستیار می‌پرسد" : "پاسخ دستیار"}>
          <p className="text-body whitespace-pre-wrap">{lastAgentMessage.text}</p>
          {assistantAsks && (
            <ChatInput
              onSend={(text) => void agent.send(text)}
              disabledReason={chatDisabled}
              placeholder="پاسخ خود را بنویسید…"
              label="پاسخ شما به دستیار"
            />
          )}
        </DetailSection>
      )}

      {view.requirements && (
        <DetailSection title="آنچه دستیار فهمید">
          <RequirementsList requirements={view.requirements} changes={diff?.requirements} />
        </DetailSection>
      )}

      {questions.length > 0 && (
        <DetailSection title={openQuestions ? "پرسش دستیار" : "پرسش و پاسخ"}>
          <div ref={questionRef} className="flex scroll-mt-24 flex-col gap-3">
            {questions.map((q) => (
              <QuestionCard
                key={q.id}
                questions={q.questions}
                answer={q.answer}
                disabled={status !== "waiting_user" || agent.busy}
                disabledHint="این پرسش دیگر فعال نیست."
                onAnswer={(text) => void agent.send(text)}
              />
            ))}
          </div>
        </DetailSection>
      )}

      {showImpact && (
        <DetailSection
          title="اثر روی ربات"
          action={
            diff && (
              <StatusBadge tone={RISK_TONE[diff.risk]} marker>
                {RISK_LABELS[diff.risk]}
              </StatusBadge>
            )
          }
        >
          {affected.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <h4 className="text-small font-semibold text-fg">{diff ? "قابلیت‌های تحت‌تأثیر" : "قابلیت‌های ربات"}</h4>
              <ul className="flex flex-wrap gap-2" aria-label="قابلیت‌ها">
                {affected.map((c) => (
                  <li key={c.key}>
                    <Badge variant="accent" className="gap-1.5 text-small">
                      {c.title}
                      {c.type && <span className="text-fg-muted">· {c.type}</span>}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!diff && outline && outline.menu.length > 0 && (
            <p className="text-small text-fg-secondary">منوی ربات: {outline.menu.map((m) => m.label).join("، ")}</p>
          )}
          {changes !== null && (
            <div className="flex flex-col gap-1.5">
              <h4 className="text-small font-semibold text-fg">تغییر در پیکربندی</h4>
              <ConfigDiff changes={changes} emptyText="پیکربندی ربات تغییری نکرده است." />
            </div>
          )}
          {diff && diff.warnings.length > 0 && (
            <div className="flex flex-col gap-1.5 rounded-md bg-warning-soft p-4">
              <h4 className="flex items-center gap-2 text-small font-semibold text-warning-text">
                <TriangleAlert strokeWidth={1.75} className="size-4" aria-hidden />
                نکته‌هایی که باید بدانید
              </h4>
              <ul className="flex flex-col gap-1 text-body">
                {diff.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
        </DetailSection>
      )}

      {showTests && (
        <DetailSection title="آزمون‌ها">
          <TestSummary
            total={report?.total ?? null}
            passed={report?.passed ?? 0}
            failed={report?.failed ?? 0}
            failures={report?.failures}
            note={testsNote}
            notes={testsItem?.generated?.notes ?? []}
            groups={groups}
            attempts={attempts}
            pendingText="آزمون‌ها بعد از ساخت اجرا می‌شوند."
            listCount={detail?.scenarios?.length}
          >
            {detail?.scenarios && detail.scenarios.length > 0 ? (
              <ScenarioBrowser scenarios={detail.scenarios} report={detail.test_report} requirements={detail.requirements?.items ?? []} />
            ) : undefined}
          </TestSummary>
        </DetailSection>
      )}

      {deployed && decision === "approved" && (
        <div className="border-t border-border px-5 py-5">
          <DeployedState number={deployed.number} onOpenSection={openSection} />
        </div>
      )}

      <div className="flex flex-col gap-1 border-t border-border px-5 py-3">
        <Disclosure
          title="گفتگو"
          meta={chatLines.length > 0 ? `${fa(chatLines.length)} پیام` : undefined}
        >
          <div className="flex flex-col gap-3">
            <ChatLog lines={chatLines} />
            {canChat && (
              <div className="flex flex-col gap-1.5">
                <span className="flex items-center gap-1.5 text-caption text-fg-muted">
                  <MessageSquareText strokeWidth={1.75} className="size-4" aria-hidden />
                  {status === "waiting_approval"
                    ? "برای اصلاح پیش‌نویس، پیام بنویسید."
                    : "می‌توانید به‌جای دکمه‌ها، پاسخ را اینجا هم بنویسید."}
                </span>
                <ChatInput
                  onSend={(text) => void agent.send(text)}
                  disabledReason={chatDisabled}
                  placeholder={status === "waiting_approval" ? "تغییر دلخواه در پیش‌نویس…" : "پاسخ خود را بنویسید…"}
                />
              </div>
            )}
          </div>
        </Disclosure>
      </div>

      {phase && (
        <DecisionBar
          revisionNumber={number}
          phase={phase}
          canApprove={approval?.can_approve ?? true}
          blockedReason={approval?.blocked_reason}
          busy={agent.busy}
          onApprove={() => void agent.approve()}
          onReject={() => agent.reject()}
          simulatorHref={draftId ? `${sectionHref(bot.id, "test")}?revision=${encodeURIComponent(draftId)}` : null}
        />
      )}
    </article>
  );
}
