"use client";

import { ChevronLeft, ChevronRight, Pencil, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fa, formatDateTime, toFaDigits } from "@/lib/format";
import type { BookingCapability, BotSpec, DataCollection, DataRecord, OwnerAction, RequestCapability } from "@/lib/types";
import { formatCell } from "./field-utils";

const BOOKING_STATUSES: Record<string, { label: string; variant: "success" | "warning" | "secondary" }> = {
  confirmed: { label: "تأیید شده", variant: "success" },
  waitlisted: { label: "لیست انتظار", variant: "warning" },
  cancelled: { label: "لغو شده", variant: "secondary" },
};

interface RecordTableProps {
  collection: DataCollection;
  spec: BotSpec | null;
  records: DataRecord[];
  total: number;
  offset: number;
  limit: number;
  /** item_id -> title of the resource record, for booking and request collections. */
  titles: Record<number, string>;
  onPage: (offset: number) => void;
  onEdit: (record: DataRecord) => void;
  onDelete: (record: DataRecord) => void;
  onCancelBooking: (record: DataRecord) => void;
  onOwnerAction: (record: DataRecord, action: OwnerAction) => void;
}

export function RecordTable({
  collection,
  spec,
  records,
  total,
  offset,
  limit,
  titles,
  onPage,
  onEdit,
  onDelete,
  onCancelBooking,
  onOwnerAction,
}: RecordTableProps) {
  const isResource = collection.kind === "resource";
  const hasItem = collection.system_columns.some((c) => c.key === "item_id");
  const requestCap =
    collection.kind === "request"
      ? (spec?.capabilities.find((c): c is RequestCapability => c.type === "request" && c.key === collection.key) ?? null)
      : null;
  const bookingCap =
    collection.kind === "booking"
      ? (spec?.capabilities.find((c): c is BookingCapability => c.type === "booking" && c.key === collection.key) ?? null)
      : null;

  function statusChip(status: string | null) {
    if (!status) return null;
    if (collection.kind === "booking") {
      const s = BOOKING_STATUSES[status];
      return <Badge variant={s?.variant ?? "secondary"}>{s?.label ?? status}</Badge>;
    }
    const label = requestCap?.statuses.find((s) => s.key === status)?.label ?? status;
    return <Badge variant={status === requestCap?.initial_status ? "warning" : "secondary"}>{label}</Badge>;
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
    if (collection.kind === "booking") {
      const active = r.status === "confirmed" || r.status === "waitlisted";
      if (!active || (bookingCap && !bookingCap.cancellation.enabled)) return null;
      return (
        <Button variant="outline" size="sm" onClick={() => onCancelBooking(r)} aria-label={`لغو ثبت‌نام ${fa(r.id)}`}>
          لغو ثبت‌نام
        </Button>
      );
    }
    const actions = requestCap?.owner_actions.filter((a) => r.status !== null && a.from_statuses.includes(r.status)) ?? [];
    if (actions.length === 0) return null;
    return (
      <div className="flex flex-wrap justify-end gap-1">
        {actions.map((a) => (
          <Button key={a.key} variant="outline" size="sm" onClick={() => onOwnerAction(r, a)}>
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
                  <td className="px-3 py-2">{r.item_id !== null ? (titles[r.item_id] ?? `مورد ${fa(r.item_id)}`) : ""}</td>
                )}
                {!isResource && (
                  <td className="px-3 py-2">
                    <span dir="ltr" className="tabular-nums text-muted-foreground">
                      {r.actor_id ? toFaDigits(r.actor_id) : ""}
                    </span>
                  </td>
                )}
                {collection.fields.map((f) => (
                  <td key={f.key} className="max-w-64 px-3 py-2">
                    <span className={f.type === "long_text" ? "line-clamp-2" : undefined} dir={f.type === "phone" ? "ltr" : undefined}>
                      {formatCell(f, r.data[f.key])}
                    </span>
                  </td>
                ))}
                {!isResource && <td className="px-3 py-2">{statusChip(r.status)}</td>}
                {!isResource && <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{formatDateTime(r.created_at)}</td>}
                <td className="px-3 py-2">{rowActions(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

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
