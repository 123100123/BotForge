"use client";

import { Badge } from "@/components/ui/badge";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataCollection } from "@/lib/types";

const KIND_TITLES: Record<DataCollection["kind"], string> = {
  resource: "اطلاعات",
  booking: "ثبت‌نام‌ها و رزروها",
  request: "درخواست‌ها",
  orders: "سفارش‌ها",
};

interface CollectionNavProps {
  collections: DataCollection[];
  selected: string | null;
  counts: Record<string, number>;
  onSelect: (key: string) => void;
}

/** Resources first, then bookings, then requests (the backend already orders resources first). */
export function CollectionNav({ collections, selected, counts, onSelect }: CollectionNavProps) {
  const order: DataCollection["kind"][] = ["resource", "booking", "request", "orders"];
  const groups = order
    .map((kind) => ({ kind, items: collections.filter((c) => c.kind === kind) }))
    .filter((g) => g.items.length > 0);

  return (
    <nav aria-label="مجموعه‌های داده" className="app-subtle-surface flex min-w-0 flex-col gap-4 p-3 lg:sticky lg:top-24">
      {groups.map((g) => (
        <div key={g.kind} className="flex flex-col gap-1">
          <h3 className="px-2 text-xs font-bold text-muted-foreground">{KIND_TITLES[g.kind]}</h3>
          <ul className="flex flex-row flex-wrap gap-1 lg:flex-col">
            {g.items.map((c) => {
              const active = c.key === selected;
              return (
                <li key={c.key}>
                  <button
                    type="button"
                    onClick={() => onSelect(c.key)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-start text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                      active ? "bg-primary/10 font-bold text-primary" : "bg-card/70 hover:bg-card",
                    )}
                  >
                    <span className={cn("truncate", c.enabled === false && "text-muted-foreground")}>{c.label_plural}</span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      {c.enabled === false && (
                        <Badge variant="outline" className="px-2 py-0 text-muted-foreground">
                          غیرفعال
                        </Badge>
                      )}
                      {counts[c.key] !== undefined && (
                        <span className="rounded-full bg-surface-secondary px-2 text-xs text-muted-foreground">{fa(counts[c.key])}</span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
