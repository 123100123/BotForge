import { Ban, CheckCheck, Circle, CircleCheck, CircleDot, CircleX, Clock, type LucideIcon } from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";
import type { DataCollection } from "@/lib/types";

export type StatusTone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

type Kind = DataCollection["kind"];

/** Tone of well-known status keys. Unknown keys are neutral: a custom status never claims a meaning. */
const COMMON: Record<string, StatusTone> = {
  new: "info",
  open: "info",
  placed: "info",
  pending: "info",
  submitted: "info",
  waitlisted: "warning",
  assigned: "brand",
  in_progress: "brand",
  processing: "brand",
  answered: "brand",
  approved: "success",
  delivered: "success",
  shipped: "success",
  closed: "success",
  done: "success",
  completed: "success",
  cancelled: "neutral",
  canceled: "neutral",
  rejected: "danger",
  failed: "danger",
};

export function statusTone(key: string | null, kind?: Kind): StatusTone {
  if (!key) return "neutral";
  // "confirmed" is a middle step for an order (still to be delivered) but a settled outcome for a booking.
  if (key === "confirmed") return kind === "orders" ? "brand" : "success";
  return COMMON[key] ?? "neutral";
}

const TONE_ICONS: Record<StatusTone, LucideIcon> = {
  neutral: Circle,
  brand: CircleCheck,
  success: CheckCheck,
  warning: Clock,
  danger: CircleX,
  info: CircleDot,
};

/** Status is never color alone: a word plus a shape that differs per tone (cancelled gets its own). */
export function RecordStatusBadge({
  statusKey,
  label,
  kind,
  className,
}: {
  statusKey: string | null;
  label?: string;
  kind?: Kind;
  className?: string;
}) {
  if (!statusKey) return null;
  const tone = statusTone(statusKey, kind);
  const Icon = statusKey === "cancelled" || statusKey === "canceled" ? Ban : TONE_ICONS[tone];
  return (
    <StatusBadge tone={tone} className={className} icon={<Icon aria-hidden strokeWidth={1.75} />}>
      {label ?? statusKey}
    </StatusBadge>
  );
}

/** Label of a status key in a collection's vocabulary (falls back to the key). */
export function statusLabel(collection: Pick<DataCollection, "statuses">, key: string | null): string {
  if (!key) return "";
  return collection.statuses?.find((s) => s.key === key)?.label ?? key;
}
