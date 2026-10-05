"use client";

import { ChevronLeft, ChevronRight, Pencil, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fa, formatDateTime, toFaDigits } from "@/lib/format";
import type { CollectionAction, DataCollection, DataRecord } from "@/lib/types";
import { formatCell } from "./field-utils";
import { OrdersTable } from "./orders-table";

const BOOKING_STATUS_VARIANTS: Record<string, "success" | "warning" | "secondary"> = {
  confirmed: "success",
  waitlisted: "warning",
  cancelled: "secondary",
};

interface RecordTableProps {
  collection: DataCollection;
  records: DataRecord[];
  total: number;
  offset: number;
  limit: number;
  onPage: (offset: number) => void;
  onEdit: (record: DataRecord) => void;
  onDelete: (record: DataRecord) => void;
  /** A row action (booking cancel, request owner action) was chosen. */
  onAction: (record: DataRecord, action: CollectionAction) => void;
}

export function RecordTable({
  collection,
  records,
  total,
  offset,
  limit,
  onPage,
  onEdit,
  onDelete,
  onAction,
}: RecordTableProps) {
  const isResource = collection.kind === "resource";
  const isOrders = collection.kind === "orders";
  const hasItem = collection.system_columns.some((c) => c.key === "item_id");
  const statuses = collection.statuses ?? [];
  const actions = collection.actions ?? [];
  const tz = collection.timezone;

  function statusChip(status: string | null) {
    if (!status) return null;
    const label = statuses.find((s) => s.key === status)?.label ?? status;
    const variant =
      collection.kind === "booking"
        ? (BOOKING_STATUS_VARIANTS[status] ?? "secondary")
        : status === statuses[0]?.key
          ? "warning" // the first status is the one a new request starts in
          : "secondary";
    return <Badge variant={variant}>{label}</Badge>;
  }

  function rowActions(r: DataRecord) {
    if (isResource) {
      return (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="sm" onClick={() => onEdit(r)} aria-label={`ویرایش مورد ${fa(r.id)}`}>
            <Pencil />
            ویرایش
          </Button>
          <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => onDelete(r)} aria-label={`حذف مورد ${fa(r.id)}`}>
            <Trash2 />
            حذف
          </Button>
        </div>
      );
    }
    // An action is offered only for records whose status is one of its `from_statuses`.
    const allowed = actions.filter((a) => r.status !== null && a.from_statuses.includes(r.status));
    if (allowed.length === 0) return null;
    return (
      <div className="flex flex-wrap justify-end gap-1">
        {allowed.map((a) => (
          <Button
            key={a.key}
            variant="outline"
            size="sm"
            onClick={() => onAction(r, a)}
            aria-label={collection.kind === "booking" ? `${a.label} ${fa(r.id)}` : undefined}
          >
            {a.label}
          </Button>
        ))}
      </div>
    );
  }

  const pageCount = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor(offset / limit) + 1;

  return (
    <div className="flex flex-col gap-3">
      {isOrders ? (
        <OrdersTable collection={collection} records={records} statusChip={statusChip} rowActions={rowActions} />
      ) : (
      <div className="relative overflow-x-auto rounded-lg border">
        <table className="w-full min-w-max text-sm">
          <thead className="bg-muted/60 text-xs text-muted-foreground">
            <tr>
              {!isResource && hasItem && <th className="px-3 py-2 text-start font-medium">مورد</th>}
              {!isResource && <th className="px-3 py-2 text-start font-medium">مشتری</th>}
              {collection.fields.map((f) => (
                <th key={f.key} className="px-3 py-2 text-start font-medium">
                  {f.label}
                </th>
              ))}
              {!isResource && <th className="px-3 py-2 text-start font-medium">وضعیت</th>}
              {!isResource && <th className="px-3 py-2 text-start font-medium">زمان</th>}
              <th className="px-3 py-2 text-end font-medium">
                <span className="sr-only">اقدام‌ها</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.id} className="border-t align-top">
                {!isResource && hasItem && (
                  <td className="px-3 py-2">{r.item_title ?? (r.item_id !== null ? `مورد ${fa(r.item_id)}` : "")}</td>
                )}
                {!isResource && (
                  <td className="px-3 py-2">
                    {r.actor_name ? (
                      <span title={r.actor_id ?? undefined}>{r.actor_name}</span>
                    ) : (
                      <span dir="ltr" className="tabular-nums text-muted-foreground">
                        {r.actor_id ? toFaDigits(r.actor_id) : ""}
                      </span>
                    )}
                  </td>
                )}
                {collection.fields.map((f) => (
                  <td key={f.key} className="max-w-64 px-3 py-2">
                    <span className={f.type === "long_text" ? "line-clamp-2" : undefined} dir={f.type === "phone" ? "ltr" : undefined}>
                      {formatCell(f, r.data[f.key], tz)}
                    </span>
                  </td>
                ))}
                {!isResource && <td className="px-3 py-2">{statusChip(r.status)}</td>}
                {!isResource && <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{formatDateTime(r.created_at, tz)}</td>}
                <td className="px-3 py-2">{rowActions(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}

      {total > limit && (
        <div className="flex items-center justify-between text-sm">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(offset - limit)}>
            <ChevronRight />
            قبلی
          </Button>
          <span className="text-muted-foreground">
            صفحهٔ {fa(page)} از {fa(pageCount)}
          </span>
          <Button variant="outline" size="sm" disabled={page >= pageCount} onClick={() => onPage(offset + limit)}>
            بعدی
            <ChevronLeft />
          </Button>
        </div>
      )}
    </div>
  );
}
