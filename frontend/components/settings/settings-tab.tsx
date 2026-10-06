"use client";

import { useCallback, useEffect, useState } from "react";
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

  if (!status) return error ? <ErrorNote>{error}</ErrorNote> : <LoadingBlock />;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-5">
      {error && <ErrorNote>{error}</ErrorNote>}
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
      <TeamSection botId={bot.id} />
      <GroupsSection botId={bot.id} />
      <AnnouncementsSection botId={bot.id} />
      <SchedulesSection botId={bot.id} onOpenTab={onOpenTab} />
    </div>
  );
}
