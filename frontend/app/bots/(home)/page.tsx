"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Plus, Store } from "lucide-react";
import { BotStatusChip } from "@/components/app/bot-status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, relativeTime } from "@/lib/format";
import { botHref, readLastBot, sectionHref } from "@/lib/routes";
import type { Bot } from "@/lib/types";

/** A business with no active version is still being built: it opens on Changes, the others on Overview. */
function entryHref(bot: Bot): string {
  return bot.active_revision_id ? botHref(bot.id) : sectionHref(bot.id, "changes");
}

/** Where /bots sends the owner (D02), or null to show the list. `?all=1` always shows the list. */
function landing(bots: Bot[], showAll: boolean): string | null {
  if (showAll) return null;
  if (bots.length === 0) return "/bots/new";
  if (bots.length === 1) return entryHref(bots[0]);
  const last = readLastBot();
  const remembered = last ? bots.find((b) => b.id === last) : undefined;
  return remembered ? entryHref(remembered) : null;
}

function ListSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" role="status" aria-label="در حال بارگذاری">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-32 rounded-md" />
      ))}
    </div>
  );
}

function BotsHome() {
  const router = useRouter();
  const showAll = useSearchParams().get("all") === "1";
  const [bots, setBots] = useState<Bot[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  /** A redirect is under way: keep the skeleton instead of flashing the list. */
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.listBots().then(
      (list) => {
        if (cancelled) return;
        const target = landing(list, showAll);
        if (target) {
          setLeaving(true);
          router.replace(target);
          return;
        }
        setBots(list);
        setError(null);
      },
      (err) => {
        if (!cancelled) setError(errorMessage(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [router, showAll, tick]);

  const newButton = (
    <Button asChild>
      <Link href="/bots/new">
        <Plus strokeWidth={1.75} />
        کسب‌وکار جدید
      </Link>
    </Button>
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="کسب‌وکارهای شما" actions={bots && bots.length > 0 ? newButton : undefined} />

      {error && (
        <ErrorState
          message={error}
          onRetry={() => {
            setError(null);
            setTick((t) => t + 1);
          }}
        />
      )}

      {(!bots || leaving) && !error && <ListSkeleton />}

      {bots && !leaving && bots.length === 0 && (
        <Card>
          <CardContent>
            <EmptyState
              icon={<Store />}
              as="h2"
              title="هنوز کسب‌وکاری نساخته‌اید"
              description="کسب‌وکارتان را توضیح دهید؛ دستیار ربات تلگرام آن را می‌سازد و نگهداری می‌کند."
              action={newButton}
            />
          </CardContent>
        </Card>
      )}

      {bots && !leaving && bots.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {bots.map((bot) => (
            <li key={bot.id}>
              <Link href={botHref(bot.id)} className="block h-full rounded-md">
                <Card className="h-full gap-3 transition-colors duration-fast hover:border-brand">
                  <CardContent className="flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-2">
                      <h2 className="text-h3 text-fg">{bot.name}</h2>
                      <BotStatusChip status={bot.status} />
                    </div>
                    <div className="flex flex-col gap-1 text-small text-fg-muted">
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

/** /bots: sends the owner to their business (0 → onboarding, 1 or last used → it); otherwise lists them. */
export default function BotsPage() {
  return (
    <Suspense fallback={<ListSkeleton />}>
      <BotsHome />
    </Suspense>
  );
}
