"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DataCollection } from "@/lib/types";
import { ActivityTable } from "./activity-table";
import { OperationsPage, useScope } from "./scope";

/** Requests and approvals: one inbox over the request collections (support, feedback, forms, approvals ...). */
export function RequestsInbox() {
  const { bot, collections, loading } = useScope("requests");
  const params = useSearchParams();
  const status = params.get("status");
  const wanted = params.get("collection");

  return (
    <OperationsPage
      title="درخواست‌ها"
      description="درخواست‌ها، فرم‌ها و تأییدیه‌هایی که مشتری‌ها و کارکنان فرستاده‌اند؛ تصمیم هر کدام را از اینجا بگیرید."
      loading={loading}
      inactive={collections.length === 0}
    >
      <Inbox botId={bot.id} collections={collections} wanted={wanted} status={status} />
    </OperationsPage>
  );
}

function initialCollection(collections: DataCollection[], wanted: string | null, status: string | null): string {
  if (wanted && collections.some((c) => c.key === wanted)) return wanted;
  // An Overview link (?status=new) lands on the first collection that has that status.
  const byStatus = status ? collections.find((c) => c.statuses?.some((s) => s.key === status)) : undefined;
  return (byStatus ?? collections[0]).key;
}

function Inbox({ botId, collections, wanted, status }: { botId: string; collections: DataCollection[]; wanted: string | null; status: string | null }) {
  const [active, setActive] = useState(() => initialCollection(collections, wanted, status));
  const current = collections.find((c) => c.key === active) ?? collections[0];
  // The ?status= filter belongs to the collection it was meant for, not to the ones the person switches to.
  const statusFor = (c: DataCollection) => (c.statuses?.some((s) => s.key === status) ? status : null);

  return (
    <div className="flex flex-col gap-4">
      {collections.length > 1 && (
        <Tabs value={current.key} onValueChange={setActive}>
          <TabsList variant="segmented" aria-label="نوع درخواست">
            {collections.map((c) => (
              <TabsTrigger key={c.key} value={c.key}>
                {c.label_plural}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}
      <ActivityTable
        key={current.key}
        botId={botId}
        collection={current}
        initialStatus={statusFor(current)}
        emptyDescription="وقتی مشتری‌ها یا کارکنان از ربات فرم بفرستند، درخواست‌ها همین‌جا با وضعیت و دکمهٔ تصمیم نمایش داده می‌شوند."
      />
    </div>
  );
}
