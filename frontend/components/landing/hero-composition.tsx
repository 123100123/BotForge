import { AttentionList } from "@/components/app/attention-list";
import { MetricStrip } from "@/components/app/metric-strip";
import { ChatMessageList } from "@/components/simulator/chat-message-list";
import { PhoneFrame } from "@/components/simulator/phone-frame";
import { StatusBadge } from "@/components/ui/status-badge";
import { BUSINESS_NAME, HERO_ATTENTION, HERO_CHAT, HERO_METRICS, HERO_SUMMARY } from "./data";

/**
 * The hero's product picture: a Control Center Overview fragment (real AttentionList and MetricStrip with
 * fixture numbers) overlapped at its start-bottom corner by a real PhoneFrame chat. Decorative for assistive
 * technology apart from one summary label, and inert: nothing in it can be focused or clicked.
 */
export function HeroComposition() {
  return (
    <div role="img" aria-label={HERO_SUMMARY} className="relative min-w-0 pb-[21.25rem]">
      <div inert className="pointer-events-none overflow-hidden rounded-md border border-border-strong bg-page select-none">
        <div className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3">
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-h3 text-fg">{BUSINESS_NAME}</span>
            <span className="text-caption text-fg-muted">نمای کلی</span>
          </div>
          <StatusBadge tone="success" marker>
            ربات فعال
          </StatusBadge>
        </div>
        <div className="flex flex-col gap-3 p-4">
          <AttentionList items={HERO_ATTENTION} />
          <MetricStrip items={HERO_METRICS} label="شاخص‌های امروز" />
        </div>
      </div>
      <div inert aria-hidden className="pointer-events-none absolute bottom-0 start-4 select-none lg:-start-6">
        <PhoneFrame
          title={BUSINESS_NAME}
          subtitle="ربات تلگرام"
          className="mx-0 h-[23rem] w-[17.5rem] max-w-none shadow-float"
        >
          <ChatMessageList messages={HERO_CHAT} />
        </PhoneFrame>
      </div>
    </div>
  );
}
