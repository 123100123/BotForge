"use client";

import { Fragment, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fa, formatDateTime, formatNumber, toFaDigits } from "@/lib/format";
import type { DataCollection, DataRecord } from "@/lib/types";
import { formatCell } from "./field-utils";

interface OrderLine {
  title: string;
  qty: number;
  unitPrice: number | null;
}

const PAYMENT_LABELS: Record<string, { label: string; variant: "success" | "warning" | "secondary" }> = {
  unpaid: { label: "پرداخت‌نشده", variant: "warning" },
  paid: { label: "پرداخت‌شده", variant: "success" },
  refunded: { label: "بازگشت داده شد", variant: "secondary" },
};

const toman = (n: number) => `${formatNumber(n)} تومان`;

function linesOf(record: DataRecord): OrderLine[] {
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
        unitPrice: e.unit_price === undefined || !Number.isFinite(price) ? null : price,
      },
    ];
  });
}

/** "عنوان ×تعداد" for each line, joined; long orders are cut to the first two lines. */
function itemsSummary(lines: OrderLine[]): string {
  if (lines.length === 0) return "";
  const shown = lines.slice(0, 2).map((l) => `${l.title} ×${fa(l.qty)}`);
  const rest = lines.length - shown.length;
  return shown.join("، ") + (rest > 0 ? `، و ${fa(rest)} مورد دیگر` : "");
}

interface OrdersTableProps {
  collection: DataCollection;
  records: DataRecord[];
  statusChip: (status: string | null) => ReactNode;
  rowActions: (record: DataRecord) => ReactNode;
}

/** The orders collection: one row per order, with an expandable detail row listing the items. */
export function OrdersTable({ collection, records, statusChip, rowActions }: OrdersTableProps) {
  const [openId, setOpenId] = useState<number | null>(null);
  const tz = collection.timezone;

  return (
    <div className="relative overflow-x-auto rounded-lg border">
      <table className="w-full min-w-max text-sm">
        <thead className="bg-muted/60 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-start font-medium">شماره</th>
            <th className="px-3 py-2 text-start font-medium">وضعیت</th>
            <th className="px-3 py-2 text-start font-medium">مبلغ</th>
            <th className="px-3 py-2 text-start font-medium">پرداخت</th>
            <th className="px-3 py-2 text-start font-medium">اقلام</th>
            <th className="px-3 py-2 text-start font-medium">زمان</th>
            <th className="px-3 py-2 text-end font-medium">
              <span className="sr-only">اقدام‌ها</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => {
            const lines = linesOf(r);
            const total = Number(r.data.total);
            const payment = typeof r.data.payment_status === "string" ? r.data.payment_status : null;
            const paymentMeta = payment ? (PAYMENT_LABELS[payment] ?? { label: payment, variant: "secondary" as const }) : null;
            const open = openId === r.id;
            const detailId = `order-detail-${r.id}`;
            return (
              <Fragment key={r.id}>
                <tr className="border-t align-top">
                  <td className="px-3 py-2 tabular-nums">{fa(r.id)}</td>
                  <td className="px-3 py-2">{statusChip(r.status)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{Number.isFinite(total) ? toman(total) : ""}</td>
                  <td className="px-3 py-2">{paymentMeta && <Badge variant={paymentMeta.variant}>{paymentMeta.label}</Badge>}</td>
                  <td className="max-w-64 px-3 py-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-auto max-w-full justify-start px-1 py-1 text-start font-normal whitespace-normal"
                      aria-expanded={open}
                      aria-controls={detailId}
                      aria-label={`جزئیات سفارش ${fa(r.id)}`}
                      onClick={() => setOpenId(open ? null : r.id)}
                    >
                      <ChevronDown className={open ? "rotate-180 transition-transform" : "transition-transform"} />
                      <span className="line-clamp-2">{itemsSummary(lines) || "جزئیات"}</span>
                    </Button>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{formatDateTime(r.created_at, tz)}</td>
                  <td className="px-3 py-2">{rowActions(r)}</td>
                </tr>
                {open && (
                  <tr id={detailId} className="bg-muted/30">
                    <td colSpan={7} className="px-4 py-3">
                      <div className="flex flex-col gap-3 text-sm md:flex-row md:gap-8">
                        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                          <h4 className="text-xs font-medium text-muted-foreground">اقلام سفارش</h4>
                          {lines.length === 0 ? (
                            <p className="text-muted-foreground">اقلامی ثبت نشده است.</p>
                          ) : (
                            <ul className="flex flex-col gap-1">
                              {lines.map((l, i) => (
                                <li key={i} className="flex flex-wrap items-baseline justify-between gap-x-4">
                                  <span>
                                    {l.title} ×{fa(l.qty)}
                                  </span>
                                  {l.unitPrice !== null && (
                                    <span className="text-muted-foreground">
                                      {toman(l.unitPrice)} × {fa(l.qty)} = {toman(l.unitPrice * l.qty)}
                                    </span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                        <dl className="flex min-w-0 flex-1 flex-col gap-1.5">
                          <div className="flex gap-2">
                            <dt className="text-muted-foreground">مشتری:</dt>
                            <dd className="min-w-0">
                              {r.actor_name ?? (r.actor_id ? <span dir="ltr">{toFaDigits(r.actor_id)}</span> : "")}
                            </dd>
                          </div>
                          {collection.fields.map((f) => (
                            <div key={f.key} className="flex gap-2">
                              <dt className="text-muted-foreground">{f.label}:</dt>
                              <dd className="min-w-0" dir={f.type === "phone" ? "ltr" : undefined}>
                                {formatCell(f, r.data[f.key], tz) || "—"}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
