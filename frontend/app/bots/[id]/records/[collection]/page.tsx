"use client";

import { useParams } from "next/navigation";
import { useBusiness } from "@/components/app/business-context";
import { DataTab } from "@/components/data/data-tab";
import { PageHeader } from "@/components/ui/page-header";

/** One resource collection (products, workshops...), generated into the Operations navigation. */
export default function CollectionPage() {
  const { collection } = useParams<{ collection: string }>();
  const key = safeDecode(collection);
  const { bot, collections } = useBusiness();
  const found = collections.find((c) => c.key === key);
  return (
    <>
      <PageHeader title={found?.label_plural ?? "داده‌ها"} />
      <DataTab bot={bot} collectionKeys={[key]} />
    </>
  );
}

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
