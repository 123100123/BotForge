"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useBusiness } from "@/components/app/business-context";
import { LoadingBlock } from "@/components/app/state-blocks";
import { SimulatorTab } from "@/components/simulator/simulator-tab";
import { PageHeader } from "@/components/ui/page-header";

/** `?revision=<id>` preselects the version (linked from a change proposal). */
function TestBody() {
  const { bot } = useBusiness();
  const revision = useSearchParams().get("revision");
  return <SimulatorTab bot={bot} initialRevisionId={revision} />;
}

export default function TestPage() {
  return (
    <>
      <PageHeader title="آزمایش ربات" description="ربات را پیش از انتشار، از نگاه چند کاربر آزمایشی امتحان کنید." />
      <Suspense fallback={<LoadingBlock />}>
        <TestBody />
      </Suspense>
    </>
  );
}
