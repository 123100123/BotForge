import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ChangeStateBadge, type ChangeState } from "./change-state";

export interface ChangeTimelineItem {
  /** Stable key; also the `?v=` value that selects the item (apart from the default selection). */
  key: string;
  href: string;
  /** «نسخهٔ ۴» or «پیشنهاد تغییر». */
  label: string;
  /** The owner's sentence behind the change, if known. */
  summary: string | null;
  state: ChangeState;
  /** Already formatted (relative time). */
  time: string | null;
  tests: { passed: number; total: number } | null;
}

interface ChangeTimelineProps {
  items: ChangeTimelineItem[];
  selectedKey: string | null;
  /** Below xl only the newest items and the selected one are shown until expanded. */
  expanded: boolean;
  onToggleExpanded: () => void;
  /** Items shown below xl before expanding. */
  collapsedCount?: number;
  className?: string;
}

/**
 * Proposals and versions, newest first, as ruled rows with a state word and shape on each. The selection
 * lives in the URL, so every row is a link. Pure: props only.
 */
export function ChangeTimeline({ items, selectedKey, expanded, onToggleExpanded, collapsedCount = 4, className }: ChangeTimelineProps) {
  const hiddenCount = Math.max(0, items.length - collapsedCount);
  return (
    <div className={cn("flex flex-col", className)}>
      <ul aria-label="تغییرات و نسخه‌ها" className="flex flex-col divide-y divide-border">
        {items.map((item, index) => {
          const selected = item.key === selectedKey;
          const collapsedAway = !expanded && index >= collapsedCount && !selected;
          return (
            <li key={item.key} className={cn(collapsedAway && "max-xl:hidden")}>
              <Link
                href={item.href}
                scroll={false}
                aria-current={selected ? "true" : undefined}
                className={cn(
                  "flex flex-col gap-1.5 border-s-2 border-transparent px-4 py-3 transition-colors duration-fast hover:bg-surface-sunken",
                  selected && "border-brand bg-brand-soft hover:bg-brand-soft",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-body font-semibold text-fg">{item.label}</span>
                  <ChangeStateBadge state={item.state} />
                </span>
                {item.summary && <span className="line-clamp-2 text-small text-fg-secondary">{item.summary}</span>}
                {(item.time || item.tests) && (
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-caption text-fg-muted">
                    {item.time && <span>{item.time}</span>}
                    {item.tests && (
                      <span>
                        {fa(item.tests.passed)} از {fa(item.tests.total)} آزمون موفق
                      </span>
                    )}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
      {hiddenCount > 0 && (
        <div className="border-t border-border p-2 xl:hidden">
          <Button variant="ghost" size="sm" onClick={onToggleExpanded} aria-expanded={expanded} className="w-full">
            <ChevronDown strokeWidth={1.75} className={cn("transition-transform duration-fast", expanded && "rotate-180")} />
            {expanded ? "نمایش کمتر" : `نمایش ${fa(hiddenCount)} مورد قدیمی‌تر`}
          </Button>
        </div>
      )}
    </div>
  );
}
