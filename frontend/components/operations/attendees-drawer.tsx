"use client";

import Link from "next/link";
import { useState } from "react";
import { BarChart3, BellRing, Megaphone, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DateTimeValue, DetailList, DrawerSection, FieldValue, RecordDrawer, RecordStatusBadge, RowActionsMenu, statusLabel, type RowAction } from "@/components/data/data-table";
import { actorLabel, recordTitle } from "@/components/data/record-utils";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataCollection, DataRecord } from "@/lib/types";
import { itemCapacity, itemStartMs, type BookingStats, type ItemFields } from "./item-bookings";

const STATUS_ORDER: Record<string, number> = { confirmed: 0, waitlisted: 1, cancelled: 2 };

/** A slim bar: confirmed seats of the capacity, with the waitlist as text. No capacity: just the count. */
export function CapacityMeter({ stats, capacity, className }: { stats: BookingStats; capacity: number | null; className?: string }) {
  const full = capacity !== null && stats.confirmed >= capacity;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <div className="flex items-baseline justify-between gap-2 text-small">
        <span>{capacity === null ? `${fa(stats.confirmed)} ثبت‌نام` : `${fa(stats.confirmed)} از ${fa(capacity)}`}</span>
        {full && <span className="text-caption text-warning-text">تکمیل ظرفیت</span>}
      </div>
      {capacity !== null && (
        <div
          role="meter"
          aria-label="ظرفیت"
          aria-valuemin={0}
          aria-valuemax={capacity}
          aria-valuenow={Math.min(stats.confirmed, capacity)}
          className="h-1.5 overflow-hidden rounded-xs bg-surface-sunken"
        >
          <div className={cn("h-full rounded-xs", full ? "bg-warning" : "bg-brand")} style={{ width: `${Math.min(100, (stats.confirmed / capacity) * 100)}%` }} />
        </div>
      )}
      {stats.waitlisted > 0 && <span className="text-caption text-warning-text">{fa(stats.waitlisted)} نفر در لیست انتظار</span>}
    </div>
  );
}

export interface EventExtras {
  reminderHours: number;
  capabilitiesHref: string;
  reportsHref: string;
  announcementHref: string;
  onPublish: () => void;
}

/**
 * The registrations of one bookable item (an event, a workshop ...): its details, who is registered with
 * their status, and a cancel action per booking. Events add the reminder rule, publishing and report links.
 */
export function AttendeesDrawer({
  resource,
  booking,
  item,
  bookings,
  stats,
  fields,
  actionsFor,
  extras,
  onClose,
}: {
  resource: DataCollection;
  booking: DataCollection;
  item: DataRecord | null;
  bookings: DataRecord[];
  stats: BookingStats;
  fields: ItemFields;
  actionsFor: (booking: DataRecord) => RowAction[];
  extras?: EventExtras;
  onClose: () => void;
}) {
  // Keep the last item while the drawer slides out.
  const [last, setLast] = useState<{ item: DataRecord; bookings: DataRecord[]; stats: BookingStats } | null>(null);
  if (item && last?.item !== item) setLast({ item, bookings, stats });
  const shown = item ? { item, bookings, stats } : last;
  if (!shown) return null;

  const tz = resource.timezone;
  const start = itemStartMs(shown.item, fields);
  const capacity = itemCapacity(shown.item, fields);
  const sorted = [...shown.bookings].sort(
    (a, b) => (STATUS_ORDER[a.status ?? ""] ?? 3) - (STATUS_ORDER[b.status ?? ""] ?? 3) || a.id - b.id,
  );
  const detailFields = resource.fields.filter((f) => f.key !== fields.title?.key);
  const title = recordTitle(shown.item, resource);

  return (
    <RecordDrawer
      open={item !== null}
      onOpenChange={(o) => !o && onClose()}
      title={title}
      wide
      description={start !== null ? <DateTimeValue value={new Date(start).toISOString()} timeZone={tz} /> : undefined}
    >
      <CapacityMeter stats={shown.stats} capacity={capacity} />

      {extras && (
        <DrawerSection title="یادآوری و انتشار">
          <p className="flex items-start gap-2 text-small text-fg-secondary">
            <BellRing aria-hidden className="mt-1 size-4 shrink-0 text-fg-muted" strokeWidth={1.75} />
            <span>
              یادآوری {fa(extras.reminderHours)} ساعت پیش از شروع برای ثبت‌نام‌شدگان فرستاده می‌شود.{" "}
              <Link href={extras.capabilitiesHref} className="rounded-xs text-brand-text underline-offset-4 hover:underline">
                تنظیم یادآوری
              </Link>
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={extras.onPublish}>
              <Send className="rtl:-scale-x-100" />
              انتشار در گروه
            </Button>
            <Button asChild variant="secondary">
              <Link href={extras.announcementHref}>
                <Megaphone />
                اعلان به ثبت‌نام‌شدگان
              </Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href={extras.reportsHref}>
                <BarChart3 />
                گزارش رویدادها
              </Link>
            </Button>
          </div>
        </DrawerSection>
      )}

      {detailFields.length > 0 && (
        <DrawerSection title="جزئیات">
          <DetailList
            items={detailFields.map((f) => ({
              label: f.label,
              value: <FieldValue field={f} value={shown.item.data[f.key]} timeZone={tz} />,
            }))}
          />
        </DrawerSection>
      )}

      <DrawerSection title={`ثبت‌نام‌ها (${fa(sorted.length)})`}>
        {sorted.length === 0 ? (
          <p className="text-small text-fg-muted">هنوز کسی ثبت‌نام نکرده است.</p>
        ) : (
          <ul className="flex flex-col rounded-md border border-border">
            {sorted.map((b) => {
              const who = actorLabel(b);
              const actions = actionsFor(b);
              return (
                <li key={b.id} className="flex items-center gap-2 border-b border-border px-3 py-2 last:border-b-0">
                  <div className={cn("flex min-w-0 flex-1 flex-col", b.status === "cancelled" && "text-fg-muted")}>
                    <span className={cn("truncate text-small font-medium", b.status === "cancelled" ? "text-fg-muted" : "text-fg")}>
                      {who.ltr ? <span dir="ltr">{who.text}</span> : who.text}
                    </span>
                    <DateTimeValue value={b.created_at} timeZone={tz} className="text-caption text-fg-muted" />
                  </div>
                  <RecordStatusBadge statusKey={b.status} label={statusLabel(booking, b.status)} kind="booking" />
                  <div className="w-10 shrink-0">
                    {actions.length > 0 && <RowActionsMenu actions={actions} />}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </DrawerSection>

    </RecordDrawer>
  );
}
