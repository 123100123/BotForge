import { StatusBadge } from "@/components/ui/status-badge";
import type { BotStatus } from "@/lib/types";

const LABELS: Record<BotStatus, string> = {
  draft: "پیش‌نویس",
  live: "فعال",
  paused: "متوقف",
};

const TONES: Record<BotStatus, "neutral" | "success" | "warning"> = {
  draft: "neutral",
  live: "success",
  paused: "warning",
};

export function BotStatusChip({ status }: { status: BotStatus }) {
  return (
    <StatusBadge tone={TONES[status]} marker>
      {LABELS[status]}
    </StatusBadge>
  );
}
