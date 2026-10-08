"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ShoppingBag } from "lucide-react";
import { DateTimeValue, DataTable, DetailList, DrawerSection, FieldValue, RecordDrawer, RecordStatusBadge, statusLabel, type DataColumn, type RowAction } from "@/components/data/data-table";
import { actorLabel } from "@/components/data/record-utils";
import { useCollectionRecords } from "@/components/data/use-collection-records";
import { useRecordActions } from "@/components/data/use-record-actions";
import { fa, formatNumber } from "@/lib/format";
import type { DataCollection, DataRecord } from "@/lib/types";
import { DrawerActions } from "./drawer-actions";
import { OperationsPage, useScope } from "./scope";

export interface OrderLine {
  title: string;
  qty: number;
  unitPrice: number | null;
}

/** The lines of an order record (`data.items`), tolerant of missing fields. */
export function orderLines(record: DataRecord): OrderLine[] {
  const raw = record.data.items;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry): OrderLine[] => {
    if (typeof entry !== "object" || entry === null) return [];
    const e = entry as Record<string, unknown>;
    const qty = Number(e.qty);
    const price = Number(e.unit_price);
    return [
      {
        title: typeof e.title === "string" && e.title ? e.title : `مورد ${fa(String(e.item_id ?? ""))}`,
        qty: Number.isFinite(qty) ? qty : 1,
        unitPrice: e.unit_price === undefined || e.unit_price === null || !Number.isFinite(price) ? null : price,
      },
    ];
  });
}

export function orderTotal(record: DataRecord): number | null {
  const n = Number(record.data.total);
  return record.data.total === undefined || record.data.total === null || !Number.isFinite(n) ? null : n;
}

/** «عنوان ×تعداد» for the first two lines, then «و N مورد دیگر». */
function itemsSummary(lines: OrderLine[]): string {
  if (lines.length === 0) return "";
  const shown = lines.slice(0, 2).map((l) => `${l.title} ×${fa(l.qty)}`);
  const rest = lines.length - shown.length;
  return shown.join("، ") + (rest > 0 ? `، و ${fa(rest)} مورد دیگر` : "");
}

export function OrdersView() {
  const { bot, collections, loading } = useScope("orders");
  const initialStatus = useSearchParams().get("status");
  const collection = collections[0];
  return (
    <OperationsPage
      title="سفارش‌ها"
      description="سفارش‌هایی که مشتری‌ها در ربات ثبت کرده‌اند؛ وضعیت هر کدام را از اینجا پیش ببرید."
      loading={loading}
      inactive={!collection}
    >
      {collection && <OrdersTable botId={bot.id} collection={collection} initialStatus={initialStatus} />}
    </OperationsPage>
  );
}

export function OrdersTable({ botId, collection, initialStatus }: { botId: string; collection: DataCollection; initialStatus: string | null }) {
  const records = useCollectionRecords(botId, collection.key);
  const [openId, setOpenId] = useState<number | null>(null);
  const { actionsFor, dialog } = useRecordActions(botId, collection, records.reload);
  const tz = collection.timezone;

  const columns = useMemo<DataColumn<DataRecord>[]>(
    () => [
      {
        id: "number",
        header: "شماره",
        className: "w-20",
        sortValue: (r) => r.id,
        cell: (r) => <span className="tabular-nums">{fa(r.id)}</span>,
      },
      {
        id: "customer",
        header: "مشتری",
        className: "w-40 lg:w-48",
        sortValue: (r) => r.actor_name ?? r.actor_id,
        cell: (r) => <CustomerCell record={r} />,
      },
      {
        id: "items",
        header: "اقلام",
        hideBelow: "lg",
        cell: (r) => <span className="block truncate">{itemsSummary(orderLines(r)) || "—"}</span>,
      },
      {
        id: "total",
        header: "مبلغ (تومان)",
        align: "end",
        className: "w-36",
        sortValue: (r) => orderTotal(r),
        cell: (r) => {
          const t = orderTotal(r);
          return <span className="tabular-nums">{t === null ? "—" : formatNumber(t)}</span>;
        },
      },
      {
        id: "status",
        header: "وضعیت",
        className: "w-36",
        sortValue: (r) => statusLabel(collection, r.status),
        cell: (r) => <RecordStatusBadge statusKey={r.status} label={statusLabel(collection, r.status)} kind="orders" />,
      },
      {
        id: "time",
        header: "زمان",
        className: "w-36",
        hideBelow: "lg",
        sortValue: (r) => new Date(r.created_at).getTime(),
        cell: (r) => <DateTimeValue value={r.created_at} timeZone={tz} compact className="text-fg-secondary" />,
      },
    ],
    [collection, tz],
  );

  const open = records.items?.find((r) => r.id === openId) ?? null;

  return (
    <>
      <DataTable
        label="سفارش‌ها"
        rows={records.items}
        rowKey={(r) => r.id}
        columns={columns}
        error={records.error}
        onRetry={records.reload}
        searchText={(r) => `${r.id} ${actorLabel(r).text} ${itemsSummary(orderLines(r))} ${r.data.phone ?? ""}`}
        searchPlaceholder="جستجو در سفارش‌ها"
        statusFilter={{
          options: (collection.statuses ?? []).map((s) => ({ key: s.key, label: s.label })),
          get: (r) => r.status,
          initial: initialStatus,
        }}
        onRowOpen={(r) => setOpenId(r.id)}
        selectedKey={openId}
        rowActions={actionsFor}
        actionsWidth="lg"
        defaultSort={{ id: "number", dir: "desc" }}
        mobile={{
          title: (r) => (
            <>
              سفارش {fa(r.id)}
              <span className="font-normal text-fg-secondary"> · {actorLabel(r).text}</span>
            </>
          ),
          meta: (r) => {
            const t = orderTotal(r);
            return (
              <>
                <span className="min-w-0 truncate">{itemsSummary(orderLines(r))}</span>
                {t !== null && <span className="tabular-nums">{formatNumber(t)} تومان</span>}
              </>
            );
          },
          status: (r) => <RecordStatusBadge statusKey={r.status} label={statusLabel(collection, r.status)} kind="orders" />,
        }}
        total={records.total}
        hasMore={records.hasMore}
        loadingMore={records.loadingMore}
        onLoadMore={records.loadMore}
        empty={{
          icon: <ShoppingBag />,
          title: "هنوز سفارشی ثبت نشده",
          description: "وقتی مشتری‌ها از ربات سفارش بدهند، سفارش‌ها همین‌جا با وضعیت و اقلام نمایش داده می‌شوند.",
        }}
      />
      <OrderDrawer
        collection={collection}
        record={open}
        actions={open ? actionsFor(open) : []}
        onClose={() => setOpenId(null)}
      />
      {dialog}
    </>
  );
}

function CustomerCell({ record }: { record: DataRecord }) {
  const a = actorLabel(record);
  return a.ltr ? (
    <span dir="ltr" className="inline-block tabular-nums text-fg-secondary">
      {a.text}
    </span>
  ) : (
    <span className="block truncate">{a.text}</span>
  );
}

function OrderDrawer({
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
  // Keep the last order while the drawer slides out.
  const [last, setLast] = useState<DataRecord | null>(record);
  if (record && record !== last) setLast(record);
  const shown = record ?? last;
  const tz = collection.timezone;

  if (!shown) return null;
  const lines = orderLines(shown);
  const total = orderTotal(shown);
  const customer = actorLabel(shown);
  const changed = Math.abs(new Date(shown.updated_at).getTime() - new Date(shown.created_at).getTime()) > 60_000;

  return (
    <RecordDrawer
      open={record !== null}
      onOpenChange={(o) => !o && onClose()}
      title={`سفارش ${fa(shown.id)}`}
      badge={<RecordStatusBadge statusKey={shown.status} label={statusLabel(collection, shown.status)} kind="orders" />}
      description={
        <>
          {customer.ltr ? <span dir="ltr">{customer.text}</span> : customer.text} · <DateTimeValue value={shown.created_at} timeZone={tz} />
        </>
      }
    >
      <DrawerSection title="اقلام سفارش" className="border-t-0 pt-0">
        {lines.length === 0 ? (
          <p className="text-small text-fg-muted">اقلامی ثبت نشده است.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
            {lines.map((l, i) => (
              <li key={i} className="flex items-start justify-between gap-4 px-3 py-2 text-small">
                <span className="min-w-0 break-words">{l.title}</span>
                <span className="shrink-0 text-end tabular-nums">
                  {l.unitPrice === null ? (
                    <span className="text-fg-secondary">{fa(l.qty)} عدد</span>
                  ) : (
                    <>
                      <span className="block text-fg-muted">
                        {fa(l.qty)} × {formatNumber(l.unitPrice)}
                      </span>
                      <span className="block font-medium text-fg">{formatNumber(l.unitPrice * l.qty)} تومان</span>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
        {total !== null && (
          <p className="flex items-baseline justify-between gap-4 text-body font-semibold">
            <span>جمع کل</span>
            <span className="tabular-nums">{formatNumber(total)} تومان</span>
          </p>
        )}
      </DrawerSection>

      <DrawerSection title="مشتری و تحویل">
        <DetailList
          items={[
            { label: "مشتری", value: customer.ltr ? <span dir="ltr">{customer.text}</span> : customer.text },
            ...collection.fields.map((f) => ({
              label: f.label,
              value: <FieldValue field={f} value={shown.data[f.key]} timeZone={tz} />,
            })),
          ]}
        />
      </DrawerSection>

      <DrawerSection title="تاریخچه">
        <ol className="flex flex-col gap-2 text-small">
          <li className="flex items-baseline justify-between gap-3">
            <span>سفارش ثبت شد</span>
            <DateTimeValue value={shown.created_at} timeZone={tz} className="text-fg-muted" />
          </li>
          {changed && (
            <li className="flex items-baseline justify-between gap-3">
              <span>آخرین تغییر: {statusLabel(collection, shown.status)}</span>
              <DateTimeValue value={shown.updated_at} timeZone={tz} className="text-fg-muted" />
            </li>
          )}
        </ol>
      </DrawerSection>

      <DrawerActions actions={actions} onBeforeSelect={onClose} />
    </RecordDrawer>
  );
}
