import { formatDate, formatTime } from "@/lib/format";
import type { ActivityItem } from "@/lib/types";

const DAY = 86_400_000;

interface DayGroup {
  label: string;
  items: ActivityItem[];
}

/** Groups the feed (newest first) by day: امروز, دیروز, then the Jalali date. */
export function groupByDay(items: ActivityItem[], now: number = Date.now()): DayGroup[] {
  const today = formatDate(now);
  const yesterday = formatDate(now - DAY);
  const groups: DayGroup[] = [];
  for (const item of items) {
    const day = formatDate(item.at);
    const label = day === today ? "امروز" : day === yesterday ? "دیروز" : day;
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}

/** Recent activity as a ruled list, one small heading per day (h3 under the section's h2). */
export function ActivityFeed({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) {
    return <p className="rounded-md border border-border bg-surface px-4 py-3 text-small text-fg-muted">هنوز فعالیتی ثبت نشده است.</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {groupByDay(items).map((group) => (
        <div key={group.label} className="flex flex-col gap-1.5">
          <h3 className="text-caption text-fg-muted">{group.label}</h3>
          <ul className="divide-y divide-border overflow-hidden rounded-md border border-border bg-surface">
            {group.items.map((a, i) => (
              <li key={`${a.at}-${i}`} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-4 py-2.5">
                <span className="min-w-0 flex-1 basis-56 text-small text-fg">{a.text}</span>
                <span className="text-caption text-fg-muted">{formatTime(a.at)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
