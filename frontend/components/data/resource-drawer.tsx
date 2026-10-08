"use client";

import { useRef, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api";
import { DateTimeValue, DetailList, FieldValue, RecordDrawer } from "./data-table";
import { RecordForm } from "./record-form";
import { recordTitle } from "./record-utils";
import type { DataCollection, DataRecord } from "@/lib/types";

export type ResourceDrawerState = { mode: "create" } | { mode: "view" | "edit"; record: DataRecord };

/**
 * Detail, edit, create and delete of one record of a writable resource collection (products, workshops,
 * events ...). One drawer: a read-only view with «ویرایش» and «حذف», or the form straight away.
 */
export function ResourceDrawer({
  botId,
  collection,
  state,
  onClose,
  onChanged,
}: {
  botId: string;
  collection: DataCollection;
  /** null closes the drawer. */
  state: ResourceDrawerState | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  // The form remounts for every record / mode, so its state always starts clean. While the drawer closes
  // (state null) the last content stays, so the exit animation plays.
  const [shown, setShown] = useState<ResourceDrawerState | null>(state);
  if (state && state !== shown) setShown(state);
  const content = state ?? shown;
  const formKey = content ? (content.mode === "create" ? "create" : `${content.mode}:${content.record.id}`) : "closed";
  return (
    <ResourceDrawerInner
      key={formKey}
      botId={botId}
      collection={collection}
      state={content}
      open={state !== null}
      onClose={onClose}
      onChanged={onChanged}
    />
  );
}

function ResourceDrawerInner({
  botId,
  collection,
  state,
  open,
  onClose,
  onChanged,
}: {
  botId: string;
  collection: DataCollection;
  state: ResourceDrawerState | null;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(state?.mode === "edit");
  const [deleting, setDeleting] = useState(false);
  const deleted = useRef(false);
  const record = state && state.mode !== "create" ? state.record : null;
  const creating = state?.mode === "create";
  const form = creating || editing;
  const title = creating ? `افزودن ${collection.label}` : form ? `ویرایش ${collection.label}` : record ? recordTitle(record, collection) : collection.label;

  return (
    <>
      <RecordDrawer open={open && !deleting} onOpenChange={(o) => !o && onClose()} title={title}>
        {form ? (
          <RecordForm
            botId={botId}
            collection={collection}
            record={record}
            onCancel={() => (creating ? onClose() : setEditing(false))}
            onSaved={() => {
              toast({ title: creating ? `${collection.label} اضافه شد.` : "تغییرات ذخیره شد.", tone: "success" });
              onChanged();
              onClose();
            }}
          />
        ) : (
          record && (
            <>
              <DetailList
                items={[
                  ...collection.fields.map((f) => ({
                    label: f.label,
                    value: <FieldValue field={f} value={record.data[f.key]} timeZone={collection.timezone} />,
                  })),
                  { label: "ثبت‌شده", value: <DateTimeValue value={record.created_at} timeZone={collection.timezone} /> },
                ]}
              />
              <div className="mt-auto flex flex-row-reverse flex-wrap items-center justify-start gap-2 border-t border-border pt-4">
                <Button onClick={() => setEditing(true)}>
                  <Pencil />
                  ویرایش
                </Button>
                <Button variant="secondary" className="text-danger-text hover:text-danger-text" onClick={() => setDeleting(true)}>
                  <Trash2 />
                  حذف
                </Button>
              </div>
            </>
          )
        )}
      </RecordDrawer>

      <ConfirmDialog
        open={deleting}
        onOpenChange={(o) => {
          if (o) return;
          setDeleting(false); // cancelled: back to the record
          if (deleted.current) onClose();
        }}
        title={`حذف ${collection.label}`}
        description={`«${record ? recordTitle(record, collection) : ""}» برای همیشه حذف می‌شود و از ربات هم برداشته می‌شود.`}
        confirmLabel="حذف"
        destructive
        onConfirm={async () => {
          if (!record) return;
          await api.deleteRecord(botId, collection.key, record.id);
          deleted.current = true;
          toast({ title: `${collection.label} حذف شد.`, tone: "success" });
          onChanged();
        }}
      />
    </>
  );
}

/** Delete with confirmation, for views that offer «حذف» in a row menu instead of a drawer. */
export function DeleteRecordDialog({
  botId,
  collection,
  record,
  onClose,
  onDeleted,
}: {
  botId: string;
  collection: DataCollection;
  record: DataRecord | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  return (
    <ConfirmDialog
      open={record !== null}
      onOpenChange={(o) => !o && onClose()}
      title={`حذف ${collection.label}`}
      description={`«${record ? recordTitle(record, collection) : ""}» برای همیشه حذف می‌شود و از ربات هم برداشته می‌شود.`}
      confirmLabel="حذف"
      destructive
      onConfirm={async () => {
        if (!record) return;
        await api.deleteRecord(botId, collection.key, record.id);
        toast({ title: `${collection.label} حذف شد.`, tone: "success" });
        onDeleted();
      }}
    />
  );
}
