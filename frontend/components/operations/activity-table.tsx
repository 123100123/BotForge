"use client";

import { useMemo, useState } from "react";
import { Inbox } from "lucide-react";
import { DateTimeValue, DataTable, DetailList, DrawerSection, FieldValue, RecordDrawer, RecordStatusBadge, statusLabel, type DataColumn, type RowAction } from "@/components/data/data-table";
import { actorLabel, subjectOf } from "@/components/data/record-utils";
import { useCollectionRecords } from "@/components/data/use-collection-records";
import { useRecordActions } from "@/components/data/use-record-actions";
import { fa } from "@/lib/format";
import type { DataCollection, DataRecord } from "@/lib/types";
import { DrawerActions } from "./drawer-actions";

/**
 * Records customers create through the bot: requests (support, feedback, forms, approvals) and plain
 * booking lists. Columns: who, what it is about, status, time, and the collection's owner actions.
 */
export function ActivityTable({
  botId,
  collection,
  initialStatus,
  emptyDescription,
}: {
  botId: string;
  collection: DataCollection;
  initialStatus?: string | null;
  emptyDescription?: string;
}) {
  const records = useCollectionRecords(botId, collection.key);
  const [openId, setOpenId] = useState<number | null>(null);
  const { actionsFor, dialog } = useRecordActions(botId, collection, records.reload);
  const tz = collection.timezone;
  const hasItem = collection.kind === "booking" || collection.system_columns.some((c) => c.key === "item_id");
  const itemHeader = collection.kind === "booking" ? "مورد" : hasItem ? "مورد" : "موضوع";

  const columns = useMemo<DataColumn<DataRecord>[]>(
    () => [
      {
        id: "actor",
        header: collection.kind === "booking" ? "مشتری" : "درخواست‌دهنده",
        className: "w-44",
        sortValue: (r) => r.actor_name ?? r.actor_id,
        cell: (r) => {
          const a = actorLabel(r);
          return a.ltr ? (
            <span dir="ltr" className="inline-block tabular-nums">
              {a.text}
            </span>
          ) : (
            <span className="block truncate">{a.text}</span>
          );
        },
      },
      {
        id: "subject",
        header: itemHeader,
        sortValue: (r) => subjectOf(r, collection),
        cell: (r) => <span className="block truncate font-normal text-fg-secondary">{subjectOf(r, collection) || "—"}</span>,
      },
      {
        id: "status",
        header: "وضعیت",
        className: "w-40",
        sortValue: (r) => statusLabel(collection, r.status),
        cell: (r) => <RecordStatusBadge statusKey={r.status} label={statusLabel(collection, r.status)} kind={collection.kind} />,
      },
      {
        id: "time",
        header: "زمان",
        className: "w-36",
        hideBelow: "md",
        sortValue: (r) => new Date(r.created_at).getTime(),
        cell: (r) => <DateTimeValue value={r.created_at} timeZone={tz} compact className="font-normal text-fg-secondary" />,
      },
    ],
    [collection, itemHeader, tz],
  );

  const open = records.items?.find((r) => r.id === openId) ?? null;

  return (
    <>
      <DataTable
        label={collection.label_plural}
        rows={records.items}
        rowKey={(r) => r.id}
        columns={columns}
        error={records.error}
        onRetry={records.reload}
        searchText={(r) =>
          `${actorLabel(r).text} ${subjectOf(r, collection)} ${collection.fields.map((f) => String(r.data[f.key] ?? "")).join(" ")}`
        }
        searchPlaceholder={`جستجو در ${collection.label_plural}`}
        statusFilter={{
          options: (collection.statuses ?? []).map((s) => ({ key: s.key, label: s.label })),
          get: (r) => r.status,
          initial: initialStatus,
        }}
        onRowOpen={(r) => setOpenId(r.id)}
        selectedKey={openId}
        rowActions={actionsFor}
        actionsWidth="md"
        defaultSort={{ id: "time", dir: "desc" }}
        mobile={{
          title: (r) => actorLabel(r).text,
          meta: (r) => (
            <>
              <span className="min-w-0 truncate">{subjectOf(r, collection)}</span>
              <DateTimeValue value={r.created_at} timeZone={tz} className="text-fg-muted" />
            </>
          ),
          status: (r) => <RecordStatusBadge statusKey={r.status} label={statusLabel(collection, r.status)} kind={collection.kind} />,
        }}
        total={records.total}
        hasMore={records.hasMore}
        loadingMore={records.loadingMore}
        onLoadMore={records.loadMore}
        empty={{
          icon: <Inbox />,
          title: `هنوز ${collection.label} ثبت نشده`,
          description: emptyDescription ?? "وقتی مشتری‌ها از ربات استفاده کنند، موارد همین‌جا نمایش داده می‌شود.",
        }}
      />
      <ActivityDrawer collection={collection} record={open} actions={open ? actionsFor(open) : []} onClose={() => setOpenId(null)} />
      {dialog}
    </>
  );
}

function ActivityDrawer({
  collection,
  record,
  actions,
  onClose,
}: {
  collection: DataCollection;
  record: DataRecord | null;
  actions: RowAction[];
  onClose: () => void;
}) {
  const [last, setLast] = useState<DataRecord | null>(record);
  if (record && record !== last) setLast(record);
  const shown = record ?? last;
  if (!shown) return null;
  const tz = collection.timezone;
  const who = actorLabel(shown);
  const fields = collection.fields.filter((f) => shown.data[f.key] !== undefined);

  return (
    <RecordDrawer
      open={record !== null}
      onOpenChange={(o) => !o && onClose()}
      title={`${collection.label} ${fa(shown.id)}`}
      badge={<RecordStatusBadge statusKey={shown.status} label={statusLabel(collection, shown.status)} kind={collection.kind} />}
      description={<DateTimeValue value={shown.created_at} timeZone={tz} />}
    >
      <DetailList
        items={[
          { label: collection.kind === "booking" ? "مشتری" : "درخواست‌دهنده", value: who.ltr ? <span dir="ltr">{who.text}</span> : who.text },
          ...(shown.item_title ? [{ label: "مورد", value: shown.item_title }] : []),
        ]}
      />
      {fields.length > 0 && (
        <DrawerSection title="اطلاعات فرم">
          <DetailList
            items={fields.map((f) => ({
              label: f.label,
              value: <FieldValue field={f} value={shown.data[f.key]} timeZone={tz} />,
            }))}
          />
        </DrawerSection>
      )}
      <DrawerActions actions={actions} onBeforeSelect={onClose} />
    </RecordDrawer>
  );
}
