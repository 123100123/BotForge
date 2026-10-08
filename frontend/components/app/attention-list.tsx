import Link from "next/link";
import { ChevronRightIcon, CircleAlertIcon, CircleCheckIcon, InfoIcon, TriangleAlertIcon, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type AttentionTone = "warning" | "info" | "danger" | "brand";

export interface AttentionListItem {
  id: string;
  tone: AttentionTone;
  /** One full sentence (it already contains any count). */
  text: string;
  href: string;
  actionLabel: string;
}

const TONE: Record<AttentionTone, { stripe: string; icon: string; Icon: LucideIcon }> = {
  warning: { stripe: "border-s-warning", icon: "text-warning-text", Icon: TriangleAlertIcon },
  danger: { stripe: "border-s-danger", icon: "text-danger-text", Icon: CircleAlertIcon },
  info: { stripe: "border-s-info", icon: "text-info-text", Icon: InfoIcon },
  brand: { stripe: "border-s-brand", icon: "text-brand-text", Icon: InfoIcon },
};

/**
 * Things that wait for the owner: one ruled row each, with a 4px tone stripe on the start edge, a sentence and
 * a link-style action at the end. Pure (props only). With no items it shows one quiet line.
 */
export function AttentionList({
  items,
  emptyText = "فعلاً چیزی منتظر شما نیست.",
  className,
}: {
  items: AttentionListItem[];
  emptyText?: string;
  className?: string;
}) {
  if (items.length === 0) {
    return (
      <p className={cn("flex items-center gap-2 rounded-md border border-border bg-surface px-4 py-3 text-small text-fg-secondary", className)}>
        <CircleCheckIcon className="size-4 shrink-0 text-success-text" strokeWidth={1.75} aria-hidden />
        {emptyText}
      </p>
    );
  }
  return (
    <ul className={cn("divide-y divide-border overflow-hidden rounded-md border border-border bg-surface", className)}>
      {items.map((item) => {
        const { stripe, icon, Icon } = TONE[item.tone];
        return (
          <li key={item.id} className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 border-s-4 px-4 py-3", stripe)}>
            <Icon className={cn("size-4 shrink-0", icon)} strokeWidth={1.75} aria-hidden />
            <span className="min-w-0 flex-1 basis-56 text-body text-fg">{item.text}</span>
            <Link
              href={item.href}
              className="inline-flex shrink-0 items-center gap-1 rounded-xs text-small font-medium text-brand-text underline-offset-4 hover:underline"
            >
              {item.actionLabel}
              <ChevronRightIcon className="size-4 rtl:-scale-x-100" strokeWidth={1.75} aria-hidden />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
