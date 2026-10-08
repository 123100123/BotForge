import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import type { UpcomingItem } from "@/lib/adapters/attention";
import { formatDate, formatTime, relativeTime } from "@/lib/format";

/** Events starting in the next 7 days: title, Jalali date and time, and how far away it is. */
export function UpcomingList({ items, loading }: { items: UpcomingItem[]; loading: boolean }) {
  if (loading) {
    return (
      <div aria-hidden className="flex flex-col gap-px overflow-hidden rounded-md border border-border bg-surface">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center justify-between gap-4 px-4 py-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-24" />
          </div>
        ))}
      </div>
    );
  }
  if (items.length === 0) {
    return <p className="rounded-md border border-border bg-surface px-4 py-3 text-small text-fg-muted">در ۷ روز آینده چیزی برنامه‌ریزی نشده است.</p>;
  }
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-md border border-border bg-surface">
      {items.slice(0, 6).map((u) => (
        <li key={u.id}>
          <Link href={u.href} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-4 py-2.5 transition-colors duration-fast hover:bg-surface-sunken">
            <span className="min-w-0 flex-1 basis-40 text-small font-medium text-fg">{u.title}</span>
            <span className="flex flex-wrap items-baseline gap-x-3 text-caption text-fg-muted">
              <span>
                {formatDate(u.at)}، {formatTime(u.at)}
              </span>
              <span className="font-medium text-fg-secondary">{relativeTime(u.at)}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
