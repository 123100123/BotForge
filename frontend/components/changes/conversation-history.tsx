"use client";

import { useEffect } from "react";
import { CircleCheck, LoaderCircle, RotateCw } from "lucide-react";
import type { AgentRunContextValue } from "@/components/agent/agent-run-provider";
import { ChatLog, ChatMessage } from "@/components/agent/chat-thread";
import { RUN_STATUS_LABELS, runKindLabel } from "@/components/agent/labels";
import type { PastRun } from "@/components/agent/use-agent-run";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { FeedItem } from "@/lib/agent-state";
import { fa, formatDateTime } from "@/lib/format";
import type { RunStatus } from "@/lib/types";
import { Disclosure } from "./disclosure";

type Tone = "neutral" | "success" | "warning" | "danger";

const STATUS_TONE: Record<RunStatus, Tone> = {
  running: "neutral",
  waiting_user: "warning",
  waiting_approval: "warning",
  done: "success",
  failed: "danger",
  rejected: "neutral",
  interrupted: "danger",
};

/** One line of an earlier run: the messages, the questions the assistant asked, errors and "version N went live". */
function PastItem({ item }: { item: FeedItem }) {
  switch (item.kind) {
    case "owner":
    case "agent":
      return <ChatMessage from={item.kind} text={item.text} />;
    case "questions":
      return <ChatMessage from="agent" text={item.questions.map((q) => q.text).join("\n")} />;
    case "error":
      return <p className="rounded-sm bg-danger-soft px-3 py-2 text-small text-danger-text">{item.message}</p>;
    case "deployed":
      return (
        <p className="flex items-center gap-1.5 text-small font-medium text-success-text">
          <CircleCheck strokeWidth={1.75} className="size-4" aria-hidden />
          نسخهٔ {fa(item.number)} فعال شد
        </p>
      );
    default:
      return null; // requirements, tests and review live with the version (its own page)
  }
}

const SHOWN_KINDS: ReadonlySet<FeedItem["kind"]> = new Set(["owner", "agent", "questions", "error", "deployed"]);

function PastRunGroup({ entry, onRetry }: { entry: PastRun; onRetry: () => void }) {
  const { run, view, failed } = entry;
  const status = view?.status ?? run.status;
  const items = (view?.feed ?? []).filter((item) => SHOWN_KINDS.has(item.kind));
  return (
    <section className="flex flex-col gap-3" aria-label={`${runKindLabel(run.kind)}، ${formatDateTime(run.created_at)}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-fg-muted">
        <span>{runKindLabel(run.kind)}</span>
        <span aria-hidden>·</span>
        <time dateTime={run.created_at}>{formatDateTime(run.created_at)}</time>
        {status && (
          <StatusBadge tone={STATUS_TONE[status]} marker>
            {RUN_STATUS_LABELS[status]}
          </StatusBadge>
        )}
        <span className="h-px min-w-6 flex-1 bg-border" aria-hidden />
      </div>
      {failed ? (
        <div className="flex flex-wrap items-center gap-2 text-small text-fg-muted">
          این بخش از گفتگو بارگذاری نشد.
          <Button size="sm" variant="secondary" onClick={onRetry}>
            <RotateCw strokeWidth={1.75} />
            تلاش دوباره
          </Button>
        </div>
      ) : view === null ? (
        <p className="flex items-center gap-2 text-small text-fg-muted" role="status">
          <LoaderCircle strokeWidth={1.75} className="size-4 animate-spin" aria-hidden />
          در حال بارگذاری…
        </p>
      ) : items.length === 0 ? (
        <p className="text-small text-fg-muted">پیامی در این گفتگو نبود.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((item) => (
            <li key={`${item.kind}-${item.id}`}>
              <PastItem item={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface ConversationHistoryProps {
  /** Earlier runs of the business, oldest first. */
  past: PastRun[];
  /** Starts loading the earlier runs' events (once each); called when the history first shows. */
  onShow: () => void;
  onRetry: (runId: string) => void;
}

/**
 * The earlier conversations with the assistant (every run before the current one), above the current
 * run's messages. Rendered inside the collapsed «گفتگو» section, so the runs' events are read only once
 * the owner opens it.
 */
export function ConversationHistory({ past, onShow, onRetry }: ConversationHistoryProps) {
  useEffect(() => {
    onShow();
  }, [onShow]);
  if (past.length === 0) return null;
  return (
    <div className="flex flex-col gap-5 border-b border-border pb-4">
      {past.map((entry) => (
        <PastRunGroup key={entry.run.id} entry={entry} onRetry={() => onRetry(entry.run.id)} />
      ))}
      <p className="text-caption text-fg-muted">گفتگوی فعلی</p>
    </div>
  );
}

/**
 * The whole conversation (earlier runs, then the latest run's messages) as a collapsed section, for a
 * version page: the version the latest run produced keeps the conversation reachable after the run's
 * own proposal page is gone. Read-only; new messages go through the composer.
 */
export function ConversationSection({ agent }: { agent: AgentRunContextValue }) {
  const lines = agent.view.feed.flatMap((item) =>
    item.kind === "owner" || item.kind === "agent" ? [{ key: `${item.kind}-${item.id}`, from: item.kind, text: item.text }] : [],
  );
  return (
    <Disclosure title="گفتگو با دستیار" meta={agent.past.length > 0 ? `${fa(agent.past.length + 1)} گفتگو` : undefined}>
      <div className="flex flex-col gap-3">
        <ConversationHistory past={agent.past} onShow={agent.loadHistory} onRetry={agent.retryPast} />
        <ChatLog lines={lines} />
      </div>
    </Disclosure>
  );
}
