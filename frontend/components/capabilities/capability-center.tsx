"use client";

import { useMemo, useState } from "react";
import { SearchIcon, XIcon } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { useCapabilities } from "@/components/capabilities/capabilities-provider";
import { CapabilityDetailPane, capabilityHref } from "@/components/capabilities/capability-detail";
import { CapabilityRow } from "@/components/capabilities/capability-row";
import { normalizeFa } from "@/components/capabilities/labels";
import { ToggleNoticeBar } from "@/components/capabilities/toggle-notice";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/app/segmented";
import { fa } from "@/lib/format";
import { useMediaQuery } from "@/lib/use-media-query";
import type { CapabilityOut } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "all" | "active" | "off";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "همه" },
  { value: "active", label: "فعال" },
  { value: "off", label: "خاموش" },
];

function ListSkeleton() {
  return (
    <div role="status" aria-label="در حال بارگذاری قابلیت‌ها" className="flex flex-col gap-6">
      {[4, 4, 2].map((rows, i) => (
        <div key={i} className="flex flex-col gap-3">
          <Skeleton className="h-6 w-28" />
          <div className="divide-y divide-border overflow-hidden rounded-md border border-border bg-surface">
            {Array.from({ length: rows }, (_, r) => (
              <div key={r} className="flex items-center gap-3 px-4 py-3">
                <div className="flex flex-1 flex-col gap-2">
                  <Skeleton className="h-5 w-40" />
                  <Skeleton className="h-4 w-3/4" />
                </div>
                <Skeleton className="h-5 w-9 rounded-full" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Capability Center: the summary, a filter and search, and every capability as a ruled row grouped by
 * category. At ≥1280px a sticky detail pane sits beside the list; below that a row opens its own route.
 */
export function CapabilityCenter() {
  const { bot } = useBusiness();
  const { categories, error, all, byId, refresh, requestToggle } = useCapabilities();
  const wide = useMediaQuery("(min-width: 1280px)");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string | null>(null);

  const visible = useMemo(() => {
    const q = normalizeFa(query);
    const match = (c: CapabilityOut) =>
      (filter === "all" || (filter === "active") === c.enabled) &&
      (q === "" || normalizeFa(c.name).includes(q) || normalizeFa(c.description).includes(q));
    return (categories ?? []).map((cat) => ({ ...cat, capabilities: cat.capabilities.filter(match) })).filter((cat) => cat.capabilities.length > 0);
  }, [categories, filter, query]);

  if (error) return <ErrorState message={error} onRetry={() => void refresh()} />;
  if (!categories) return <ListSkeleton />;
  if (all.length === 0) {
    return <EmptyState as="h2" title="قابلیتی در دسترس نیست" description="فهرست قابلیت‌های کسب‌وکار پس از ساخت ربات اینجا نمایش داده می‌شود." />;
  }

  const enabledCount = all.filter((c) => c.enabled).length;
  const shown = visible.flatMap((c) => c.capabilities);
  // The pane shows the picked capability, or the first one of the list while nothing is picked or it was filtered out.
  const selected = wide ? (shown.find((c) => c.id === picked) ?? shown[0]) : undefined;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <p className="text-body text-fg" aria-live="polite">
          <span className="font-semibold">
            {fa(enabledCount)} از {fa(all.length)} قابلیت فعال
          </span>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Segmented<Filter> label="نمایش قابلیت‌ها" value={filter} onChange={setFilter} options={FILTERS} />
          <div className="relative min-w-52 max-w-sm flex-1">
            <SearchIcon className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-fg-muted" strokeWidth={1.75} aria-hidden />
            <Input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="جست‌وجوی قابلیت"
              aria-label="جست‌وجوی قابلیت"
              className="ps-9 pe-9 [&::-webkit-search-cancel-button]:hidden"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="پاک کردن جست‌وجو"
                className="absolute end-1.5 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-xs text-fg-muted hover:bg-surface-sunken hover:text-fg"
              >
                <XIcon className="size-4" strokeWidth={1.75} aria-hidden />
              </button>
            )}
          </div>
        </div>
      </div>

      <ToggleNoticeBar />

      <div className={cn("grid items-start gap-6", wide && "grid-cols-[minmax(0,1fr)_26rem]")}>
        <div className="flex min-w-0 flex-col gap-6">
          {visible.length === 0 ? (
            <EmptyState
              as="h2"
              title="قابلیتی پیدا نشد"
              description="با این فیلتر یا جست‌وجو قابلیتی نیست."
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setQuery("");
                    setFilter("all");
                  }}
                >
                  نمایش همهٔ قابلیت‌ها
                </Button>
              }
            />
          ) : (
            visible.map((cat) => {
              const on = cat.capabilities.filter((c) => c.enabled).length;
              return (
                <section key={cat.id} aria-labelledby={`cap-cat-${cat.id}`} className="flex flex-col gap-3">
                  <div className="flex items-baseline gap-3">
                    <h2 id={`cap-cat-${cat.id}`} className="text-h2 text-fg">
                      {cat.name}
                    </h2>
                    <p className="text-caption text-fg-muted">
                      {fa(on)} از {fa(cat.capabilities.length)} فعال
                    </p>
                  </div>
                  <ul className="divide-y divide-border overflow-hidden rounded-md border border-border bg-surface">
                    {cat.capabilities.map((c) => (
                      <CapabilityRow
                        key={c.id}
                        cap={c}
                        byId={byId}
                        href={capabilityHref(bot.id, c.id)}
                        selected={selected?.id === c.id}
                        onSelect={wide ? () => setPicked(c.id) : undefined}
                        onToggleRequest={() => requestToggle(c)}
                      />
                    ))}
                  </ul>
                </section>
              );
            })
          )}
        </div>

        {wide && selected && (
          <aside
            aria-label={`جزئیات ${selected.name}`}
            className="sticky top-20 max-h-[calc(100dvh-7rem)] overflow-y-auto rounded-md border border-border bg-surface p-5"
          >
            <CapabilityDetailPane key={selected.id} cap={selected} onPick={setPicked} />
          </aside>
        )}
      </div>
    </div>
  );
}
