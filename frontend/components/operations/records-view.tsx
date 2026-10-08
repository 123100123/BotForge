"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Pencil, Plus, Table2, Trash2 } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { DataTable, FieldCell, fieldPlainText, fieldSortValue, isNumericField, type DataColumn, type RowAction } from "@/components/data/data-table";
import { DeleteRecordDialog, ResourceDrawer, type ResourceDrawerState } from "@/components/data/resource-drawer";
import { recordTitle } from "@/components/data/record-utils";
import { useCollectionRecords } from "@/components/data/use-collection-records";
import { sectionHref } from "@/lib/routes";
import type { DataCollection, DataRecord, FieldDef } from "@/lib/types";
import { ActivityTable } from "./activity-table";
import { OrdersTable } from "./orders-view";

/** The most field columns a table shows; the drawer shows all of them. */
const MAX_FIELD_COLUMNS = 6;

const WIDTH_BY_TYPE: Partial<Record<FieldDef["type"], string>> = {
  integer: "w-28",
  decimal: "w-28",
  datetime: "w-52",
  boolean: "w-24",
  phone: "w-36",
  choice: "w-36",
};

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** /records/[collection]: any collection of the active version, whatever its kind or whether it is switched on. */
export function RecordsCollectionPage() {
  const { collection: segment } = useParams<{ collection: string }>();
  const key = safeDecode(segment);
  const { bot, collections, dataStatus } = useBusiness();
  const collection = collections.find((c) => c.key === key);

  if (dataStatus === "loading") {
    return (
      <>
        <PageHeader title="داده‌ها" />
        <Skeleton className="h-64 w-full" />
      </>
    );
  }
  if (!collection) {
    return (
      <>
        <PageHeader title="داده‌ها" />
        <EmptyState
          icon={<Table2 />}
          as="h2"
          title="این مجموعه پیدا نشد"
          description="ممکن است در نسخهٔ فعال ربات وجود نداشته باشد."
          action={
            <Button asChild variant="secondary">
              <Link href={sectionHref(bot.id, "records")}>همهٔ داده‌ها</Link>
            </Button>
          }
        />
      </>
    );
  }
  return <CollectionView botId={bot.id} collection={collection} />;
}

/** One collection by kind: resources get the editable table, orders / requests / bookings their record tables. */
function CollectionView({ botId, collection }: { botId: string; collection: DataCollection }) {
  if (collection.kind === "resource") return <ResourceView botId={botId} collection={collection} />;
  return (
    <>
      <PageHeader
        title={collection.label_plural}
        description={collection.enabled === false ? "قابلیت این بخش خاموش است؛ داده‌های قبلی همچنان قابل مشاهده‌اند." : undefined}
      />
      {collection.kind === "orders" ? (
        <OrdersTable botId={botId} collection={collection} initialStatus={null} />
      ) : (
        <ActivityTable botId={botId} collection={collection} />
      )}
    </>
  );
}

function ResourceView({ botId, collection }: { botId: string; collection: DataCollection }) {
  const records = useCollectionRecords(botId, collection.key);
  const [drawer, setDrawer] = useState<ResourceDrawerState | null>(null);
  const [deleting, setDeleting] = useState<DataRecord | null>(null);
  const writable = collection.writable;
  const tz = collection.timezone;

  const columns = useMemo<DataColumn<DataRecord>[]>(() => {
    const titleKey = collection.title_field ?? collection.fields[0]?.key;
    const ordered = [
      ...collection.fields.filter((f) => f.key === titleKey),
      ...collection.fields.filter((f) => f.key !== titleKey),
    ].slice(0, MAX_FIELD_COLUMNS);
    return ordered.map((f, i): DataColumn<DataRecord> => ({
      id: f.key,
      header: f.label,
      align: isNumericField(f) ? "end" : "start",
      className: WIDTH_BY_TYPE[f.type],
      hideBelow: i >= 4 ? "lg" : i >= 3 ? "md" : undefined,
      sortValue: (r) => fieldSortValue(f, r.data[f.key]),
      cell: (r) => <FieldCell field={f} value={r.data[f.key]} timeZone={tz} />,
    }));
  }, [collection, tz]);

  const rowActions = (r: DataRecord): RowAction[] =>
    writable
      ? [
          { key: "edit", label: "ویرایش", icon: <Pencil />, onSelect: () => setDrawer({ mode: "edit", record: r }) },
          { key: "delete", label: "حذف", icon: <Trash2 />, danger: true, onSelect: () => setDeleting(r) },
        ]
      : [];

  const [first, second] = collection.fields.filter((f) => f.key !== collection.title_field);

  return (
    <>
      <PageHeader
        title={collection.label_plural}
        description={collection.enabled === false ? "قابلیت این بخش خاموش است؛ داده‌های قبلی همچنان قابل مشاهده‌اند." : undefined}
        actions={
          writable ? (
            <Button onClick={() => setDrawer({ mode: "create" })}>
              <Plus />
              افزودن {collection.label}
            </Button>
          ) : undefined
        }
      />
      <DataTable
        label={collection.label_plural}
        rows={records.items}
        rowKey={(r) => r.id}
        columns={columns}
        error={records.error}
        onRetry={records.reload}
        searchText={(r) => collection.fields.map((f) => fieldPlainText(f, r.data[f.key], tz)).join(" ")}
        searchPlaceholder={`جستجو در ${collection.label_plural}`}
        onRowOpen={writable ? (r) => setDrawer({ mode: "view", record: r }) : undefined}
        selectedKey={drawer && drawer.mode !== "create" ? drawer.record.id : null}
        rowActions={rowActions}
        actionsWidth="sm"
        mobile={{
          title: (r) => recordTitle(r, collection),
          meta: (r) => (
            <>
              {[first, second].filter(Boolean).map((f) => (
                <span key={f.key} className="min-w-0 truncate">
                  <FieldCell field={f} value={r.data[f.key]} timeZone={tz} />
                </span>
              ))}
            </>
          ),
        }}
        total={records.total}
        hasMore={records.hasMore}
        loadingMore={records.loadingMore}
        onLoadMore={records.loadMore}
        empty={{
          icon: <Table2 />,
          title: `هنوز ${collection.label} اضافه نشده`,
          description: writable
            ? `با «افزودن ${collection.label}» شروع کنید؛ مورد تازه بلافاصله در ربات نمایش داده می‌شود.`
            : "وقتی مشتری‌ها از ربات استفاده کنند، اینجا نمایش داده می‌شود.",
          action: writable ? (
            <Button onClick={() => setDrawer({ mode: "create" })}>
              <Plus />
              افزودن {collection.label}
            </Button>
          ) : undefined,
        }}
      />
      {writable && (
        <>
          <ResourceDrawer botId={botId} collection={collection} state={drawer} onClose={() => setDrawer(null)} onChanged={records.reload} />
          <DeleteRecordDialog botId={botId} collection={collection} record={deleting} onClose={() => setDeleting(null)} onDeleted={records.reload} />
        </>
      )}
    </>
  );
}
