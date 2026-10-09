"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/app/presentation";
import { Button } from "@/components/ui/button";
import { ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import type { WorkspaceTab } from "@/components/app/workspace";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Bot, TelegramStatus } from "@/lib/types";
import { AnnouncementsSection } from "./announcements-section";
import { GroupsSection } from "./groups-section";
import { OwnerLink } from "./owner-link";
import { SchedulesSection } from "./schedules-section";
import { TeamSection } from "./team-section";
import { TelegramConnect } from "./telegram-connect";

export function SettingsTab({
  bot,
  onBotChanged,
  onOpenTab,
}: {
  bot: Bot;
  onBotChanged: () => void;
  /** Optional: lets the schedules note link to the capabilities tab. */
  onOpenTab?: (tab: WorkspaceTab) => void;
}) {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getTelegram(bot.id).then(
      (s) => {
        if (cancelled) return;
        setStatus(s);
        setError(null);
      },
      (err) => !cancelled && setError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [bot.id]);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.getTelegram(bot.id));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [bot.id]);

  const [section, setSection] = useState("connection");
  if (!status) return error ? <ErrorNote>{error}</ErrorNote> : <LoadingBlock />;

  return (
    <div className="min-w-0 space-y-6">
      <PageHeader eyebrow="مدیریت ربات" title="تنظیمات و اتصال‌ها" description="تلگرام، اعضای تیم و ارتباط با مشتری‌ها را از یک جای مشخص مدیریت کنید." />
      <div className="flex flex-wrap gap-2" role="group" aria-label="بخش تنظیمات">{[{id:"connection",label:"تلگرام و مدیر"},{id:"team",label:"تیم"},{id:"groups",label:"گروه‌ها"},{id:"messages",label:"اعلان و زمان‌بندی"}].map((item) => <Button key={item.id} variant={section === item.id ? "secondary" : "ghost"} aria-pressed={section === item.id} onPress={() => setSection(item.id)} size="sm">{item.label}</Button>)}</div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div hidden={section !== "connection"} className="grid min-w-0 items-start gap-5 xl:grid-cols-2">
      <TelegramConnect
        botId={bot.id}
        status={status}
        hasActiveRevision={bot.active_revision_id !== null}
        onChanged={(next) => {
          setStatus(next);
          onBotChanged(); // the header shows the Telegram username and the bot status
        }}
      />
      <OwnerLink
        status={status}
        onRefresh={async () => {
          await refresh();
          onBotChanged();
        }}
      />
      </div>
      <div hidden={section !== "team"} className="min-w-0"><TeamSection botId={bot.id} /></div>
      <div hidden={section !== "groups"} className="min-w-0"><GroupsSection botId={bot.id} /></div>
      <div hidden={section !== "messages"} className="grid min-w-0 items-start gap-5 xl:grid-cols-2"><AnnouncementsSection botId={bot.id} />
      <SchedulesSection botId={bot.id} onOpenTab={onOpenTab} /></div>
    </div>
  );
}
