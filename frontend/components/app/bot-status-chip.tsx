import { Badge } from "@/components/ui/badge";
import type { BotStatus } from "@/lib/types";

const LABELS: Record<BotStatus, string> = {
  draft: "پیش‌نویس",
  live: "فعال",
  paused: "متوقف",
};

const VARIANTS: Record<BotStatus, "secondary" | "success" | "warning"> = {
  draft: "secondary",
  live: "success",
  paused: "warning",
};

export function BotStatusChip({ status }: { status: BotStatus }) {
  return <Badge variant={VARIANTS[status]}>{LABELS[status]}</Badge>;
}
