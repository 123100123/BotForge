"use client";

import { useBusiness } from "@/components/app/business-context";
import { SimulatorTab } from "@/components/simulator/simulator-tab";
import { PageHeader } from "@/components/ui/page-header";

export default function TestPage() {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="آزمایش ربات" description="ربات را پیش از انتشار، از نگاه چند کاربر آزمایشی امتحان کنید." />
      <SimulatorTab bot={bot} />
    </>
  );
}
