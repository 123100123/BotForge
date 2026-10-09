import { fa, relativeTime } from "@/lib/format";
import type { RevisionStatus, RevisionSummary } from "@/lib/types";

export const REVISION_STATUS_LABELS: Record<RevisionStatus, string> = {
  draft: "پیش‌نویس",
  active: "فعال",
  superseded: "قدیمی",
  rejected: "ردشده",
};

export const REVISION_STATUS_VARIANTS: Record<RevisionStatus, "secondary" | "success" | "warning" | "destructive"> = {
  draft: "warning",
  active: "success",
  superseded: "secondary",
  rejected: "destructive",
};

/** "نسخهٔ ۳ (فعال)" for revision selectors. */
export function revisionOptionLabel(rev: Pick<RevisionSummary, "number" | "status" | "created_at">): string {
  return `نسخهٔ ${fa(rev.number)} (${REVISION_STATUS_LABELS[rev.status]}) - ${relativeTime(rev.created_at)}`;
}

/** Revision a tab should open on: a draft under review if there is one, otherwise the active one. */
export function defaultRevision(revisions: RevisionSummary[]): RevisionSummary | null {
  return (
    revisions.find((r) => r.status === "draft") ??
    revisions.find((r) => r.status === "active") ??
    revisions[0] ??
    null
  );
}
