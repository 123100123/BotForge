"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bot as BotIcon, Plus } from "lucide-react";
import { BotStatusChip } from "@/components/app/bot-status-chip";
import { NewBotDialog } from "@/components/app/new-bot-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, relativeTime } from "@/lib/format";
import type { Bot } from "@/lib/types";

export default function BotsPage() {
  const [bots, setBots] = useState<Bot[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.listBots().then(
      (list) => {
        if (!cancelled) setBots(list);
      },
      (err) => {
        if (!cancelled) setError(errorMessage(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-h1">ربات‌های من</h1>
        {bots && bots.length > 0 && (
          <NewBotDialog>
            <Button>
              <Plus />
              ربات جدید
            </Button>
          </NewBotDialog>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-sm bg-danger-soft p-3 text-sm text-danger-text">
          {error}
        </p>
      )}

      {!bots && !error && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" role="status" aria-label="در حال بارگذاری">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-md border bg-border" />
          ))}
        </div>
      )}

      {bots && bots.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <BotIcon className="size-10 text-muted-foreground" />
            <h2 className="text-h3">هنوز رباتی نساخته‌اید</h2>
            <p className="max-w-sm text-sm leading-7 text-muted-foreground">
              کسب‌وکارتان را توضیح دهید؛ دستیار، سیستم‌عامل تلگرامی آن را می‌سازد و نگهداری می‌کند.
            </p>
            <NewBotDialog>
              <Button>
                <Plus />
                ساخت اولین ربات
              </Button>
            </NewBotDialog>
          </CardContent>
        </Card>
      )}

      {bots && bots.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {bots.map((bot) => (
            <li key={bot.id}>
              <Link
                href={`/bots/${bot.id}`}
                className="block rounded-md"
              >
                <Card className="h-full gap-3 transition-colors hover:border-primary/40">
                  <CardContent className="flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-2">
                      <h2 className="text-h3">{bot.name}</h2>
                      <BotStatusChip status={bot.status} />
                    </div>
                    <div className="flex flex-col gap-1 text-sm text-muted-foreground">
                      {bot.tg_username ? (
                        <span dir="ltr" className="self-start">
                          @{bot.tg_username}
                        </span>
                      ) : (
                        <span>به تلگرام وصل نشده</span>
                      )}
                      <span>
                        {bot.active_revision_number !== null
                          ? `نسخهٔ فعال: ${fa(bot.active_revision_number)}`
                          : "هنوز نسخهٔ فعالی ندارد"}
                      </span>
                      <span>ساخته‌شده {relativeTime(bot.created_at)}</span>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
