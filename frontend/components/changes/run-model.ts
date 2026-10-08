/**
 * Pure helpers that read a run's view (lib/agent-state.ts RunView) the way the Changes page needs it:
 * the owner's sentence, which draft version the run produced, where the proposal stands and which step of a
 * first build it is on. No behavior of the run itself lives here.
 */
import type { FeedItem, RunView } from "@/lib/agent-state";
import type { RevisionSummary, RunStatus } from "@/lib/types";
import type { ChangeState } from "./change-state";

type FeedOf<K extends FeedItem["kind"]> = Extract<FeedItem, { kind: K }>;

export function feedItems<K extends FeedItem["kind"]>(view: RunView, kind: K): FeedOf<K>[] {
  return view.feed.filter((i): i is FeedOf<K> => i.kind === kind);
}

/** The owner's first sentence of the run: the requested change. */
export function requestedChange(view: RunView): { text: string; ts: string } | null {
  const first = view.feed.find((i) => i.kind === "owner");
  return first && first.kind === "owner" ? { text: first.text, ts: first.ts } : null;
}

/** The version the run produced (its draft once approval was requested, or the deployed one). */
export function runRevisionId(view: RunView): string | null {
  const deployed = feedItems(view, "deployed")[0];
  if (deployed) return deployed.revisionId;
  for (const review of feedItems(view, "review")) {
    if (review.approval) return review.approval.revision_id;
  }
  return null;
}

export type ReviewDecision = "pending" | "approved" | "rejected" | "closed";

/** Where the run's review stands: waiting for the owner, decided, or ended without a decision. */
export function reviewDecision(
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

/** A run that still needs work or the owner: it is the open proposal. */
export function isOpenRun(status: RunStatus | null): boolean {
  return status === "running" || status === "waiting_user" || status === "waiting_approval";
}

/** State of the current run as a proposal. */
export function proposalState(status: RunStatus | null, hasDeployed: boolean): ChangeState {
  switch (status) {
    case "running":
      return "preparing";
    case "waiting_user":
      return "needs_answer";
    case "waiting_approval":
      return "ready";
    case "done":
      return hasDeployed ? "active" : "closed";
    case "rejected":
      return "rejected";
    case "failed":
    case "interrupted":
      return "failed";
    default:
      return "preparing";
  }
}

/** State of a stored version. */
export function revisionState(status: RevisionSummary["status"]): ChangeState {
  switch (status) {
    case "active":
      return "active";
    case "superseded":
      return "previous";
    case "rejected":
      return "rejected";
    case "draft":
      return "draft";
  }
}

/** Short sentence for a list row: the first line of the request. */
export function oneLine(text: string | null | undefined): string | null {
  if (!text) return null;
  const line = text.split("\n")[0].trim();
  return line || null;
}
