"use client";

import { useBusiness } from "@/components/app/business-context";
import { AnnouncementsSection } from "@/components/settings/announcements-section";
import { PageHeader } from "@/components/ui/page-header";

export default function AnnouncementsPage() {
  const { bot } = useBusiness();
  return (
    <>
      <PageHeader title="اطلاع‌رسانی" description="پیام همگانی به مشتری‌ها یا گروه‌های تلگرام." />
      <div className="max-w-3xl">
        <AnnouncementsSection botId={bot.id} />
      </div>
    </>
  );
}
