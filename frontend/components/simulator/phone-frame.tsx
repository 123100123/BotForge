import type { ReactNode } from "react";
import { Bot as BotIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface PhoneFrameProps {
  /** Chat title, usually the business name. */
  title: string;
  /** One line under the title (who is chatting, which version). */
  subtitle?: string;
  /** A StatusBadge (or similar) shown at the end edge of the header. */
  badge?: ReactNode;
  /** The chat area; fills the space between header and footer. Pass a ChatMessageList. */
  children: ReactNode;
  /** Pinned under the chat (the input bar in the simulator). Omit for a read-only phone. */
  footer?: ReactNode;
  className?: string;
}

/**
 * A Telegram-like phone: device outline, chat header (avatar, title, subtitle, badge), a chat area and an
 * optional footer. Pure: props only, no fetching and no context, so the landing page can reuse it.
 */
export function PhoneFrame({ title, subtitle, badge, children, footer, className }: PhoneFrameProps) {
  return (
    <div
      className={cn(
        "mx-auto flex h-[34rem] w-full max-w-sm flex-col overflow-hidden rounded-[1.75rem] border-[5px] border-border-strong bg-surface",
        className,
      )}
    >
      <div className="flex items-center gap-3 border-b border-border bg-surface px-4 py-3">
        <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-brand text-on-brand">
          <BotIcon className="size-5" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-body font-semibold text-fg">{title}</div>
          {subtitle && <div className="truncate text-caption text-fg-muted">{subtitle}</div>}
        </div>
        {badge && <div className="shrink-0">{badge}</div>}
      </div>
      <div className="flex min-h-0 flex-1 flex-col bg-surface-sunken">{children}</div>
      {footer && <div className="border-t border-border bg-surface p-2">{footer}</div>}
    </div>
  );
}
