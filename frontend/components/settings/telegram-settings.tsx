"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Bot, TelegramStatus } from "@/lib/types";
import { OwnerLink } from "./owner-link";
import { TelegramConnect } from "./telegram-connect";

/** Settings › Telegram: connecting the Telegram bot and linking the owner's Telegram account. */
export function TelegramSettings({ bot, onBotChanged }: { bot: Bot; onBotChanged: () => void }) {
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
    <div className="flex flex-col gap-6">
      {error && <ErrorNote>{error}</ErrorNote>}
      <TelegramConnect
        botId={bot.id}
        status={status}
        hasActiveRevision={bot.active_revision_id !== null}
        onChanged={(next) => {
          setStatus(next);
          onBotChanged(); // the sidebar shows the Telegram username and the bot status
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
  );
}
