"use client";

import { useMemo, useState } from "react";
import { CalendarDays, MapPin, Megaphone, Pencil, Plus, Trash2, Users } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { FilterTabs, RowActionsMenu, type RowAction } from "@/components/data/data-table";
import { DeleteRecordDialog, ResourceDrawer, type ResourceDrawerState } from "@/components/data/resource-drawer";
import { recordTitle } from "@/components/data/record-utils";
import { useRecordActions } from "@/components/data/use-record-actions";
import { isEventBooking } from "@/lib/nav";
import { sectionHref } from "@/lib/routes";
import { cn } from "@/lib/utils";
import type { DataCollection, DataRecord } from "@/lib/types";
import { AttendeesDrawer, CapacityMeter } from "./attendees-drawer";
import { jalaliParts } from "./date-parts";
import { itemCapacity, itemFields, itemStartMs, itemText, useItemsAndBookings, type ItemFields } from "./item-bookings";
import { PublishEventDialog } from "./publish-event-dialog";
import { OperationsPage, useScope } from "./scope";

const DEFAULT_REMINDER_HOURS = 24;

type When = "upcoming" | "past";

export function EventsView() {
  const { bot, collections, loading } = useScope("events");
  const { collections: all, capabilities } = useBusiness();
  const booking = collections.find(isEventBooking);
  const resource = booking ? all.find((c) => c.key === booking.resource) : undefined;
  const [createOpen, setCreateOpen] = useState(false);

  const reminder = capabilities.find((c) => c.id === "events")?.config.reminder_hours_before;
  const reminderHours = typeof reminder === "number" && reminder > 0 ? reminder : DEFAULT_REMINDER_HOURS;

  return (
    <OperationsPage
      title="رویدادها"
      description="رویدادهای پیش رو و گذشته، با ظرفیت و ثبت‌نام‌ها؛ هر رویداد را می‌توانید در گروه تلگرام منتشر کنید."
      loading={loading}
      inactive={!booking || !resource}
      actions={
        resource?.writable ? (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus />
            رویداد تازه
          </Button>
        ) : undefined
      }
    >
      {booking && resource && (
        <EventsBoard
          botId={bot.id}
          booking={booking}
          resource={resource}
          reminderHours={reminderHours}
          createOpen={createOpen}
          onCreateClose={() => setCreateOpen(false)}
          onCreate={() => setCreateOpen(true)}
        />
      )}
    </OperationsPage>
  );
}

function EventsBoard({
  botId,
  booking,
  resource,
  reminderHours,
  createOpen,
  onCreateClose,
  onCreate,
}: {
  botId: string;
  booking: DataCollection;
  resource: DataCollection;
  reminderHours: number;
  createOpen: boolean;
  onCreateClose: () => void;
  onCreate: () => void;
}) {
  const data = useItemsAndBookings(botId, booking, resource);
  const fields = useMemo(() => itemFields(resource), [resource]);
  const [when, setWhen] = useState<When>("upcoming");
  const [category, setCategory] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [edit, setEdit] = useState<DataRecord | null>(null);
  const [deleting, setDeleting] = useState<DataRecord | null>(null);
  const [publishing, setPublishing] = useState<DataRecord | null>(null);
  const { actionsFor, dialog } = useRecordActions(botId, booking, data.reloadAll);
  const tz = resource.timezone;

  const [now] = useState(() => Date.now());
  const split = useMemo(() => {
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

  const categories = fields.category?.choices ?? [];
  const list = split[when].filter((it) => !category || itemText(it, fields.category) === category);
  const open = data.items?.find((i) => i.id === openId) ?? null;

  function menuFor(item: DataRecord): RowAction[] {
    const out: RowAction[] = [{ key: "attendees", label: "ثبت‌نام‌ها", icon: <Users />, onSelect: () => setOpenId(item.id) }];
    if (resource.writable) out.push({ key: "edit", label: "ویرایش", icon: <Pencil />, onSelect: () => setEdit(item) });
    out.push({ key: "publish", label: "انتشار در گروه", icon: <Megaphone />, onSelect: () => setPublishing(item) });
    if (resource.writable) out.push({ key: "delete", label: "حذف رویداد", icon: <Trash2 />, danger: true, onSelect: () => setDeleting(item) });
    return out;
  }

  if (data.error && !data.items) return <ErrorState message={data.error} onRetry={data.reloadAll} />;
  if (!data.items) return <Skeleton className="h-64 w-full" />;

  const drawerState: ResourceDrawerState | null = createOpen ? { mode: "create" } : edit ? { mode: "edit", record: edit } : null;
  const addAction = resource.writable ? (
    <Button onClick={onCreate}>
      <Plus />
      رویداد تازه
    </Button>
  ) : undefined;

  const openStart = open ? itemStartMs(open, fields) : null;
  const openCategory = open ? itemText(open, fields.category) : "";
  const announcementQuery = open
    ? new URLSearchParams({
        prefill: `یادآوری: رویداد «${recordTitle(open, resource)}»${(() => {
          const p = openStart !== null ? jalaliParts(openStart, tz) : null;
          return p ? ` ${p.weekday} ${p.day} ${p.month} ساعت ${p.time}` : "";
        })()} برگزار می‌شود.`,
        ...(openCategory ? { category: openCategory } : {}),
      }).toString()
    : "";

  return (
    <div className="flex flex-col gap-4">
      {data.items.length === 0 ? (
        <div className="rounded-md border border-border bg-surface">
          <EmptyState
            icon={<CalendarDays />}
            title="هنوز رویدادی ساخته نشده"
            description="رویداد بسازید تا مشتری‌ها در ربات آن را ببینند و ثبت‌نام کنند؛ ثبت‌نام‌ها همین‌جا نمایش داده می‌شود."
            action={addAction}
          />
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <FilterTabs
              label="زمان رویدادها"
              value={when}
              onChange={(k) => k && setWhen(k as When)}
              options={[
                { key: "upcoming", label: "پیش رو", count: split.upcoming.length },
                { key: "past", label: "گذشته", count: split.past.length },
              ]}
            />
            {categories.length > 0 && (
              <Select aria-label="دسته‌بندی" value={category} onChange={(e) => setCategory(e.target.value)} className="w-full sm:w-48">
                <option value="">همهٔ دسته‌ها</option>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </Select>
            )}
          </div>

          {list.length === 0 ? (
            <div className="rounded-md border border-border bg-surface">
              <EmptyState
                icon={<CalendarDays />}
                title={when === "upcoming" ? "رویداد پیش رویی نیست" : "رویداد گذشته‌ای نیست"}
                description={category ? "برای این دسته رویدادی پیدا نشد؛ دسته را تغییر دهید." : when === "upcoming" ? "با «رویداد تازه» رویداد بعدی را بسازید." : "رویدادهایی که برگزار شوند اینجا می‌مانند."}
                action={when === "upcoming" && !category ? addAction : undefined}
              />
            </div>
          ) : (
            <ul aria-label="رویدادها" className="rounded-md border border-border bg-surface">
              {list.map((item) => (
                <EventRow
                  key={item.id}
                  item={item}
                  resource={resource}
                  fields={fields}
                  stats={data.statsOf(item.id)}
                  past={when === "past"}
                  selected={openId === item.id}
                  onOpen={() => setOpenId(item.id)}
                  actions={menuFor(item)}
                />
              ))}
            </ul>
          )}
        </>
      )}

      <AttendeesDrawer
        resource={resource}
        booking={booking}
        item={open}
        bookings={open ? data.bookingsOf(open.id) : []}
        stats={open ? data.statsOf(open.id) : { confirmed: 0, waitlisted: 0, cancelled: 0 }}
        fields={fields}
        actionsFor={actionsFor}
        extras={{
          reminderHours,
          capabilitiesHref: sectionHref(botId, "capabilities"),
          reportsHref: sectionHref(botId, "reports"),
          announcementHref: `${sectionHref(botId, "announcements")}?${announcementQuery}`,
          onPublish: () => open && setPublishing(open),
        }}
        onClose={() => setOpenId(null)}
      />
      {resource.writable && (
        <>
          <ResourceDrawer
            botId={botId}
            collection={resource}
            state={drawerState}
            onClose={() => {
              onCreateClose();
              setEdit(null);
            }}
            onChanged={data.reloadItems}
          />
          <DeleteRecordDialog botId={botId} collection={resource} record={deleting} onClose={() => setDeleting(null)} onDeleted={data.reloadAll} />
        </>
      )}
      <PublishEventDialog
        botId={botId}
        resourceKey={resource.key}
        eventId={publishing?.id ?? null}
        eventTitle={publishing ? recordTitle(publishing, resource) : ""}
        onClose={() => setPublishing(null)}
      />
      {dialog}
    </div>
  );
}

function EventRow({
  item,
  resource,
  fields,
  stats,
  past,
  selected,
  onOpen,
  actions,
}: {
  item: DataRecord;
  resource: DataCollection;
  fields: ItemFields;
  stats: { confirmed: number; waitlisted: number; cancelled: number };
  past: boolean;
  selected: boolean;
  onOpen: () => void;
  actions: RowAction[];
}) {
  const start = itemStartMs(item, fields);
  const parts = start !== null ? jalaliParts(start, resource.timezone) : null;
  const category = itemText(item, fields.category);
  const location = itemText(item, fields.location);
  return (
    <li className={cn("flex items-center gap-1 border-b border-border last:border-b-0", selected && "bg-brand-soft")}>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-3 rounded-md p-3 text-start transition-colors duration-fast hover:bg-surface-sunken sm:flex-nowrap sm:p-4"
      >
        <span
          aria-hidden={!parts}
          className={cn(
            "flex w-[4.5rem] shrink-0 flex-col items-center rounded-md bg-surface-sunken px-2 py-1.5 text-center leading-tight",
            past && "text-fg-muted",
          )}
        >
          {parts ? (
            <>
              <span className="text-caption text-fg-secondary">{parts.weekday}</span>
              <span className="text-h2">{parts.day}</span>
              <span className="text-caption">{parts.month}</span>
              <span className="mt-0.5 text-caption text-fg-secondary">{parts.time}</span>
            </>
          ) : (
            <span className="text-caption text-fg-muted">بدون تاریخ</span>
          )}
        </span>
        <span className="flex min-w-0 flex-1 basis-40 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className={cn("text-body font-medium", past ? "text-fg-secondary" : "text-fg")}>{recordTitle(item, resource)}</span>
            {category && (
              <StatusBadge tone="neutral" marker>
                {category}
              </StatusBadge>
            )}
          </span>
          {location && (
            <span className="flex items-center gap-1.5 text-small text-fg-secondary">
              <MapPin aria-hidden className="size-4 shrink-0 text-fg-muted" strokeWidth={1.75} />
              <span className="min-w-0 truncate">{location}</span>
            </span>
          )}
        </span>
        <CapacityMeter stats={stats} capacity={itemCapacity(item, fields)} className="w-full sm:w-44 sm:shrink-0" />
      </button>
      <div className="shrink-0 pe-2">
        <RowActionsMenu actions={actions} />
      </div>
    </li>
  );
}
