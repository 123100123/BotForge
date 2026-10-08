import {
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleX,
  FileClock,
  History,
  Minus,
  TriangleAlert,
  ClipboardCheck,
  type LucideIcon,
} from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";

/** Where a change (a proposal in progress, or a version) stands, in the owner's words. */
export type ChangeState =
  | "preparing"
  | "needs_answer"
  | "ready"
  | "active"
  | "previous"
  | "rejected"
  | "draft"
  | "failed"
  | "closed";

type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

export const CHANGE_STATE_LABELS: Record<ChangeState, string> = {
  preparing: "در حال آماده‌سازی",
  needs_answer: "منتظر پاسخ شما",
  ready: "آمادهٔ تأیید",
  active: "فعال",
  previous: "نسخهٔ قبلی",
  rejected: "ردشده",
  draft: "پیش‌نویس",
  failed: "ناموفق",
  closed: "بدون تغییر",
};

const TONES: Record<ChangeState, Tone> = {
  preparing: "info",
  needs_answer: "warning",
  ready: "brand",
  active: "success",
  previous: "neutral",
  rejected: "danger",
  draft: "neutral",
  failed: "danger",
  closed: "neutral",
};

const ICONS: Record<ChangeState, LucideIcon> = {
  preparing: CircleDashed,
  needs_answer: CircleHelp,
  ready: ClipboardCheck,
  active: CircleCheck,
  previous: History,
  rejected: CircleX,
  draft: FileClock,
  failed: TriangleAlert,
  closed: Minus,
};

/** State word + shape + tone (never color alone). Pure: props only. */
export function ChangeStateBadge({ state, className }: { state: ChangeState; className?: string }) {
  const Icon = ICONS[state];
  return (
    <StatusBadge tone={TONES[state]} icon={<Icon strokeWidth={1.75} aria-hidden />} className={className}>
      {CHANGE_STATE_LABELS[state]}
    </StatusBadge>
  );
}
