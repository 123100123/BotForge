"use client";

import { useBusiness } from "@/components/app/business-context";
import { AnnouncementsSection } from "@/components/settings/announcements-section";
import { PageHeader } from "@/components/ui/page-header";

export default function AnnouncementsPage() {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="اطلاع‌رسانی" description="پیام همگانی به مشتری‌ها، کارکنان یا گروه‌های تلگرام؛ سابقهٔ ارسال‌ها هم اینجاست." />
      <AnnouncementsSection botId={bot.id} />
    </>
  );
}
