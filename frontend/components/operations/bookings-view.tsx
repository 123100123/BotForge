"use client";

import { useMemo, useState } from "react";
import { CalendarCheck } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/app/segmented";
import { FilterTabs } from "@/components/data/data-table";
import { recordTitle } from "@/components/data/record-utils";
import { useRecordActions } from "@/components/data/use-record-actions";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataCollection, DataRecord } from "@/lib/types";
import { AttendeesDrawer, CapacityMeter } from "./attendees-drawer";
import { dayHeading, dayKey, jalaliParts } from "./date-parts";
import { itemCapacity, itemFields, itemStartMs, useItemsAndBookings, type BookingStats } from "./item-bookings";
import { OperationsPage, useScope } from "./scope";

type When = "upcoming" | "past";

/** Bookings that are not events (workshops, appointments, slots): the items with their bookings, by date. */
export function BookingsView() {
  const { bot, collections, loading } = useScope("bookings");
  const { collections: all } = useBusiness();
  const [active, setActive] = useState<string | null>(null);
  const booking = collections.find((c) => c.key === active) ?? collections[0];
  const resource = booking ? all.find((c) => c.key === booking.resource) : undefined;

  return (
    <OperationsPage
      title="رزروها"
      description="مواردی که مشتری‌ها در آن‌ها ثبت‌نام یا رزرو کرده‌اند، به ترتیب تاریخ؛ هر ثبت‌نام را می‌توانید لغو کنید."
      loading={loading}
      inactive={collections.length === 0}
    >
      <div className="flex flex-col gap-4">
        {collections.length > 1 && (
          <Segmented label="نوع رزرو" value={booking?.key ?? ""} onChange={setActive} options={collections.map((c) => ({ value: c.key, label: c.label_plural }))} />
        )}
        {booking &&
          (resource ? (
            <BookingGroups key={booking.key} botId={bot.id} booking={booking} resource={resource} />
          ) : (
            <EmptyState icon={<CalendarCheck />} as="h2" title="مورد قابل رزرو پیدا نشد" description="مجموعهٔ مورد این رزرو در نسخهٔ فعال ربات وجود ندارد." />
          ))}
      </div>
    </OperationsPage>
  );
}

function BookingGroups({ botId, booking, resource }: { botId: string; booking: DataCollection; resource: DataCollection }) {
  const data = useItemsAndBookings(botId, booking, resource);
  const fields = useMemo(() => itemFields(resource), [resource]);
  const [when, setWhen] = useState<When>("upcoming");
  const [openId, setOpenId] = useState<number | null>(null);
  const { actionsFor, dialog } = useRecordActions(botId, booking, data.reloadAll);
  const tz = resource.timezone;

  const [now] = useState(() => Date.now());
  const groups = useMemo(() => {
    const upcoming: DataRecord[] = [];
    const past: DataRecord[] = [];
    for (const it of data.items ?? []) {
      const t = itemStartMs(it, fields);
      (t !== null && t < now ? past : upcoming).push(it);
    }
    const startOf = (r: DataRecord) => itemStartMs(r, fields) ?? Number.MAX_SAFE_INTEGER;
    upcoming.sort((a, b) => startOf(a) - startOf(b));
    past.sort((a, b) => startOf(b) - startOf(a));
    return { upcoming, past };
  }, [data.items, fields, now]);

  const open = data.items?.find((i) => i.id === openId) ?? null;
  const list = groups[when];

  // Items sharing a calendar day sit under one heading; items without a date go last.
  const byDay = useMemo(() => {
    const out: { key: string; heading: string; items: DataRecord[] }[] = [];
    for (const it of list) {
      const t = itemStartMs(it, fields);
      const key = t === null ? "none" : dayKey(t, tz);
      let g = out.find((x) => x.key === key);
      if (!g) {
        g = { key, heading: t === null ? "بدون تاریخ" : dayHeading(t, tz), items: [] };
        out.push(g);
      }
      g.items.push(it);
    }
    return out;
  }, [list, fields, tz]);

  if (data.error && !data.items) return <ErrorState message={data.error} onRetry={data.reloadAll} />;
  if (!data.items) return <Skeleton className="h-64 w-full" />;

  if (data.items.length === 0) {
    return (
      <div className="rounded-md border border-border bg-surface">
        <EmptyState
          icon={<CalendarCheck />}
          title={`هنوز ${resource.label} اضافه نشده`}
          description={`وقتی ${resource.label_plural} ساخته شوند و مشتری‌ها ثبت‌نام کنند، رزروها اینجا به ترتیب تاریخ نمایش داده می‌شوند.`}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <FilterTabs
        label="زمان"
        value={when}
        onChange={(k) => k && setWhen(k as When)}
        options={[
          { key: "upcoming", label: "پیش رو", count: groups.upcoming.length },
          { key: "past", label: "گذشته", count: groups.past.length },
        ]}
      />
      {byDay.length === 0 ? (
        <div className="rounded-md border border-border bg-surface">
          <EmptyState icon={<CalendarCheck />} title={when === "upcoming" ? "مورد پیش رویی نیست" : "مورد گذشته‌ای نیست"} />
        </div>
      ) : (
        <div className="rounded-md border border-border bg-surface">
          {byDay.map((g) => (
            <section key={g.key} className="border-b border-border last:border-b-0">
              <h2 className="bg-surface-sunken px-4 py-2 text-caption font-medium text-fg-secondary first:rounded-t-md">{g.heading}</h2>
              <ul>
                {g.items.map((item) => (
                  <BookingItemRow
                    key={item.id}
                    item={item}
                    resource={resource}
                    tz={tz}
                    stats={data.statsOf(item.id)}
                    capacity={itemCapacity(item, fields)}
                    past={when === "past"}
                    selected={openId === item.id}
                    startMs={itemStartMs(item, fields)}
                    onOpen={() => setOpenId(item.id)}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <AttendeesDrawer
        resource={resource}
        booking={booking}
        item={open}
        bookings={open ? data.bookingsOf(open.id) : []}
        stats={open ? data.statsOf(open.id) : { confirmed: 0, waitlisted: 0, cancelled: 0 }}
        fields={fields}
        actionsFor={actionsFor}
        onClose={() => setOpenId(null)}
      />
      {dialog}
    </div>
  );
}

function BookingItemRow({
  item,
  resource,
  tz,
  stats,
  capacity,
  past,
  selected,
  startMs,
  onOpen,
}: {
  item: DataRecord;
  resource: DataCollection;
  tz: string | undefined;
  stats: BookingStats;
  capacity: number | null;
  past: boolean;
  selected: boolean;
  startMs: number | null;
  onOpen: () => void;
}) {
  const parts = startMs !== null ? jalaliParts(startMs, tz) : null;
  return (
    <li className={cn("border-t border-border first:border-t-0", selected && "bg-brand-soft")}>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 p-3 text-start transition-colors duration-fast hover:bg-surface-sunken sm:flex-nowrap sm:px-4"
      >
        <span className="w-14 shrink-0 text-small text-fg-secondary">{parts ? parts.time : "—"}</span>
        <span className={cn("min-w-0 flex-1 basis-40 truncate text-body font-medium", past ? "text-fg-secondary" : "text-fg")}>
          {recordTitle(item, resource)}
        </span>
        <span className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 sm:w-auto sm:shrink-0">
          {capacity === null && stats.waitlisted === 0 ? (
            <span className="text-small">{fa(stats.confirmed)} ثبت‌نام</span>
          ) : (
            <CapacityMeter stats={stats} capacity={capacity} className="w-full sm:w-44" />
          )}
        </span>
      </button>
    </li>
  );
}
