"use client";

import { useCallback, useState, type ReactNode } from "react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { CollectionAction, DataCollection, DataRecord } from "@/lib/types";
import type { RowAction } from "./data-table";

/** Cancel, reject and decline change a customer's outcome, so they ask first. */
export function isDestructiveAction(action: Pick<CollectionAction, "key" | "label">): boolean {
  return /(^|_)(cancel|reject|decline|refuse)/.test(action.key) || /^(لغو|رد)(\s|$)/.test(action.label);
}

/** The actions of the collection that apply to a record's current status. */
export function actionsForRecord(collection: DataCollection, record: DataRecord): CollectionAction[] {
  if (record.status === null) return [];
  const status = record.status;
  return (collection.actions ?? []).filter((a) => a.from_statuses.includes(status));
}

function confirmCopy(collection: DataCollection, record: DataRecord, action: CollectionAction): { title: string; description: string } {
  if (collection.kind === "booking") {
    return {
      title: "لغو ثبت‌نام",
      description: `ثبت‌نام این مشتری در «${record.item_title ?? "این مورد"}» لغو شود؟ اگر نفر دیگری در لیست انتظار باشد، جایگزین می‌شود و به او در تلگرام اطلاع داده می‌شود.`,
    };
  }
  if (collection.kind === "orders") {
    return {
      title: `${action.label}؟`,
      description: `سفارش شمارهٔ ${fa(record.id)} ${record.actor_name ? `از ${record.actor_name} ` : ""}تغییر می‌کند و مشتری در تلگرام مطلع می‌شود. این کار برگشت‌پذیر نیست.`,
    };
  }
  return {
    title: `${action.label}؟`,
    description: "وضعیت این درخواست تغییر می‌کند و به درخواست‌دهنده در تلگرام اطلاع داده می‌شود.",
  };
}

/**
 * Row actions of a booking, request or orders collection: the ones allowed for the record's status, run
 * through the API with a toast for the outcome. Destructive ones open a confirmation first.
 */
export function useRecordActions(
  botId: string,
  collection: DataCollection,
  onDone: () => void,
): { actionsFor: (record: DataRecord) => RowAction[]; dialog: ReactNode } {
  const [pending, setPending] = useState<{ record: DataRecord; action: CollectionAction } | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const run = useCallback(
    async (record: DataRecord, action: CollectionAction) => {
      setBusyId(record.id);
      try {
        const res = await api.runRecordAction(botId, collection.key, record.id, action.key);
        toast({ title: res.message, tone: res.ok ? "success" : "warning" });
        onDone();
      } finally {
        setBusyId(null);
      }
    },
    [botId, collection.key, onDone],
  );

  const actionsFor = useCallback(
    (record: DataRecord): RowAction[] =>
      actionsForRecord(collection, record).map((action) => {
        const danger = isDestructiveAction(action);
        return {
          key: action.key,
          label: action.label,
          danger,
          disabled: busyId === record.id,
          onSelect: () => {
            if (danger) setPending({ record, action });
            else run(record, action).catch((err) => toast({ title: errorMessage(err), tone: "danger" }));
          },
        };
      }),
    [collection, busyId, run],
  );

  const copy = pending ? confirmCopy(collection, pending.record, pending.action) : null;
  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      onOpenChange={(o) => !o && setPending(null)}
      title={copy?.title ?? ""}
      description={copy?.description ?? ""}
      confirmLabel={pending?.action.label ?? "تأیید"}
      destructive
      onConfirm={async () => {
        if (pending) await run(pending.record, pending.action);
      }}
    />
  );

  return { actionsFor, dialog };
}
